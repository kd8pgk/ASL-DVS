#!/usr/bin/env python3

import argparse
import codecs
import configparser
import fcntl
import glob
import gzip
import hmac
import io
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import signal
import socket as _socket
import struct
import subprocess
import sys
import termios
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from pathlib import Path
from urllib.parse import urlparse, parse_qs

logging.basicConfig(
    stream=sys.stderr,
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

VERSION      = "6.13.82-pi02w"
BUILD_DATE   = "20261019"

CONFIG_FILE  = Path("/etc/sysmon/sysmon.conf")
DEFAULT_PORT    = 9999
DASHBOARD_PORT  = 8989
LOG_MAXLEN   = 500

WIFIMON_SHUTDOWN_STATE_FILE = "/run/wifimon/shutdown_state.json"

_DEFAULT_CONFIG = {
    "server":   {"port": str(DEFAULT_PORT), "host": "0.0.0.0"},
    "identity": {"callsign": "KD8PGK",      "node": "652701",
                 "label":    "AllStarLink Node"},
    "thresholds": {
        "cpu_warn_pct":  "50",
        "rss_warn_mb":   "200",
        "nr_warn":       "3",
        "nr_crit":       "10",
    },
    "services": {
        "pinned": (
            "__GROUP__:System\n"
            "ssh.service | SSH Access | - | 22 | tcp\n"
            "cockpit.service | ASL3 Cockpit admin UI | - | 9090 | tcp\n"
            "__GROUP__:ASL-DVS\n"
            "nodecontrol.service | ASL+DVSwitch Dashboard | - | 8989 | tcp\n"
            "sysmon.service | Sysmon Monitor | - | 9999 | tcp\n"
            "wifimon.service |  | - | - | -\n"
            "instmon.service |  | - | - | -\n"
            "44helper.service |  | - | - | -\n"
            "__GROUP__:Asterisk Core\n"
            "asterisk.service | ASL3 Asterisk/app_rpt | /etc/asterisk/rpt.conf | 4569 | udp\n"
            "allmon3.service | Allmon3 web monitor | - | 8080 | tcp\n"
            "analog_bridge.service |  | - | - | -\n"
            "mmdvm_bridge.service |  | - | - | -\n"
            "md380-emu.service |  | - | - | -\n"
            "stfu.service |  | - | - | -\n"
            "ircddbgatewayd.service |  | - | - | -\n"
            "nxdngateway.service |  | - | - | -\n"
            "p25gateway.service |  | - | - | -\n"
            "quantar_bridge.service |  | - | - | -\n"
            "ysfgateway.service |  | - | - | -\n"
            "__GROUP__:M17\n"
            "usrp2m17.service |  | - | - | -\n"
        ),
    },
    "asldvs": {

        "hidden_files": "",
    },
    "radio_presets": {

        "radio1_values": "",
        "radio1_title":  "",
        "radio2_values": "",
        "radio2_title":  "",
        "radio3_values": "",
        "radio3_title":  "",
        "radio4_values": "",
        "radio4_title":  "",
        "radio5_values": "",
        "radio5_title":  "",
    },
    "radio_tune": {

        "active_slot":      "0",
        "active_driver":    "",
        "simpleusb_values": "",
    },
    "ui": {

        "enabled_tabs": "overview,services,ports,journal,asldvs,reg,phone,tune,hardware,dvsm,stfu,m17,sdcard,edit",
    },
}

_log_buf: deque = deque(maxlen=LOG_MAXLEN)
_log_idx: int   = 0
_log_lock       = threading.Lock()

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


def _log(msg: str, stderr: bool = False) -> None:
    global _log_idx
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts}  {msg}"
    with _log_lock:
        _log_buf.append(line)
        _log_idx += 1
    if stderr:
        print(line, file=sys.stderr)

def _sd_notify(state: str) -> None:
    sock_path = os.environ.get("NOTIFY_SOCKET")
    if not sock_path:
        return
    if sock_path.startswith("@"):
        sock_path = "\0" + sock_path[1:]
    try:
        with _socket.socket(_socket.AF_UNIX, _socket.SOCK_DGRAM) as s:
            s.connect(sock_path)
            s.sendall(state.encode())
    except OSError as exc:
        _log(f"WARN — sd_notify failed: {exc}")

def _default_config() -> configparser.ConfigParser:
    p = configparser.ConfigParser()
    for section, pairs in _DEFAULT_CONFIG.items():
        p[section] = pairs
    return p

def load_config(path: Path = CONFIG_FILE) -> configparser.ConfigParser:
    p = _default_config()
    if path.exists():
        try:
            p.read(path, encoding="utf-8")
            _log(f"Config loaded from {path}")
        except Exception as exc:
            _log(f"WARN — config read error: {exc}")
    else:
        _log(f"Config not found at {path} — using defaults")
    return p

def _process_umask() -> int:
    try:
        with open("/proc/self/status", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("Umask:"):
                    return int(line.split()[1], 8)
    except (OSError, ValueError, IndexError) as e:
        log.debug("_process_umask: %s", e)
    return 0o022

def _atomic_write(path: Path, content: str) -> None:
    atomic_write(path, content, new_mode=0o644)

_DASH_UNITS = ("nodecontrol.service", "asl_dvs_dashboard.service")

def _dash_unit() -> str:
    for u in _DASH_UNITS:
        if os.path.exists(os.path.join("/etc/systemd/system", u)):
            return u
    return _DASH_UNITS[0]

def parse_pinned_services(raw: str) -> list:
    result = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("__GROUP__:"):
            result.append({"group": line[10:].strip()})
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 5:
            if parts[0] in _DASH_UNITS:
                parts[0] = _dash_unit()
            result.append({
                "unit":   parts[0],
                "desc":   parts[1],
                "config": parts[2],
                "port":   parts[3],
                "proto":  parts[4],
            })
    return result

def _get_pinned_raw() -> str:
    if CONFIG_FILE.exists():
        return _cfg.get("services", "pinned", fallback="")
    return _DEFAULT_CONFIG["services"]["pinned"]

_cfg  = load_config()
_pinned: list = parse_pinned_services(_get_pinned_raw())

def _read_abinfo() -> "dict | None":
    import glob as _glob
    try:
        files = sorted(
            _glob.glob("/tmp/ABInfo_*.json"),
            key=os.path.getmtime,
            reverse=True,
        )
        if not files:
            return None
        if time.time() - os.path.getmtime(files[0]) > 60:
            return None
        return json.loads(Path(files[0]).read_text())
    except Exception as e:
        log.debug("_read_abinfo: %s", e)
        return None

_BAUD_TO_TERMIOS: "dict[int, int]" = {}
try:
    import termios as _termios
    _BAUD_TO_TERMIOS = {
        230400: _termios.B230400,
        460800: _termios.B460800,
    }
except ImportError:
    pass

def _run(cmd: list, timeout: int = 5) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception as e:
        log.debug("_run: %s", e)
        return ""

def _run_with_stderr(cmd: list, timeout: int = 5) -> "tuple[str, str]":
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        log.debug("_run_with_stderr: %s", e)
        return "", ""

def get_hostname() -> str:
    return _run(["hostname", "-s"]) or "unknown"

def get_kernel() -> str:
    return _run(["uname", "-r"]) or "unknown"

def get_uptime() -> str:
    raw = _run(["uptime", "-p"])
    return raw.replace("up ", "", 1) if raw.startswith("up ") else raw or "unknown"

def get_load() -> dict:
    try:
        parts = Path("/proc/loadavg").read_text().split()
        return {"l1": parts[0], "l5": parts[1], "l15": parts[2]}
    except Exception as e:
        log.debug("get_load: %s", e)
        return {"l1": None, "l5": None, "l15": None}

def get_memory() -> dict:
    try:
        text  = Path("/proc/meminfo").read_text()
        total = int(re.search(r"MemTotal:\s+(\d+)", text).group(1)) // 1024
        avail = int(re.search(r"MemAvailable:\s+(\d+)", text).group(1)) // 1024
        return {"total_mb": total, "used_mb": total - avail, "avail_mb": avail}
    except Exception as e:
        log.debug("get_memory: %s", e)
        return {"total_mb": None, "used_mb": None, "avail_mb": None}

def get_swap() -> dict:
    try:
        text  = Path("/proc/meminfo").read_text()
        total = int(re.search(r"SwapTotal:\s+(\d+)", text).group(1)) // 1024
        free  = int(re.search(r"SwapFree:\s+(\d+)", text).group(1)) // 1024
        return {"total_mb": total, "used_mb": total - free}
    except Exception as e:
        log.debug("get_swap: %s", e)
        return {"total_mb": None, "used_mb": None}

def get_cpu_temp() -> "float | None":
    try:
        raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()
        return round(int(raw) / 1000, 1)
    except Exception as e:
        log.debug("get_cpu_temp: %s", e)
        return None

def get_pi_voltage() -> "float | None":
    try:
        out = _run(["vcgencmd", "measure_volts", "core"], timeout=3)

        m = re.search(r"volt=([\d.]+)V", out or "")
        return float(m.group(1)) if m else None
    except Exception as e:
        log.debug("get_pi_voltage: %s", e)
        return None

def get_throttle_state() -> dict:
    empty = {
        "available":     False, "raw": "", "bitmask": 0,
        "uv_now":        False, "freq_cap_now": False,
        "throttled_now": False, "temp_now": False,
        "uv_ever":       False, "freq_cap_ever": False,
        "throttled_ever":False, "temp_ever": False,
        "pwr_status":    "ok",
    }
    try:
        out = _run(["vcgencmd", "get_throttled"], timeout=3)

        m = re.search(r"throttled=(0x[0-9a-fA-F]+)", out or "")
        if not m:
            return empty
        raw     = m.group(1)
        bits    = int(raw, 16)
        uv_now  = bool(bits & (1 << 0))
        fc_now  = bool(bits & (1 << 1))
        th_now  = bool(bits & (1 << 2))
        tm_now  = bool(bits & (1 << 3))
        uv_ever = bool(bits & (1 << 16))
        fc_ever = bool(bits & (1 << 17))
        th_ever = bool(bits & (1 << 18))
        tm_ever = bool(bits & (1 << 19))

        if uv_now:
            pwr_status = "uv"
        elif th_now:
            pwr_status = "throttled"
        elif uv_ever or fc_ever or th_ever or tm_ever:
            pwr_status = "warn"
        else:
            pwr_status = "ok"
        return {
            "available":     True,
            "raw":           raw,
            "bitmask":       bits,
            "uv_now":        uv_now,
            "freq_cap_now":  fc_now,
            "throttled_now": th_now,
            "temp_now":      tm_now,
            "uv_ever":       uv_ever,
            "freq_cap_ever": fc_ever,
            "throttled_ever":th_ever,
            "temp_ever":     tm_ever,
            "pwr_status":    pwr_status,
        }
    except Exception as e:
        log.debug("get_throttle_state: %s", e)
        return empty

def get_disk_usage() -> dict:
    try:
        st       = os.statvfs("/")
        total_b  = st.f_blocks * st.f_frsize
        avail_b  = st.f_bavail * st.f_frsize
        used_b   = total_b - avail_b
        used_pct = round(used_b / total_b * 100) if total_b else 0
        return {
            "used_pct":  used_pct,
            "used_gb":   round(used_b  / 1_073_741_824, 1),
            "total_gb":  round(total_b / 1_073_741_824, 1),
        }
    except Exception as e:
        log.debug("get_disk_usage: %s", e)
        return {"used_pct": None, "used_gb": None, "total_gb": None}

def get_sd_health() -> "str | None":
    try:
        for line in Path("/proc/mounts").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[1] == "/":
                opts = parts[3].split(",")
                return "ro" if "ro" in opts else "rw"
        return None
    except Exception as e:
        log.debug("get_sd_health: %s", e)
        return None

def get_proc_count() -> "int | None":
    try:
        return sum(1 for e in os.scandir("/proc") if e.name.isdigit())
    except Exception as e:
        log.debug("get_proc_count: %s", e)
        return None

_UNIT_RE = re.compile(r'^[\w@.\-]+\.service$')

def _validate_unit(unit: str) -> bool:
    return bool(_UNIT_RE.match(unit))

def _detect_dashboard() -> bool:
    import socket as _socket
    try:
        s = _socket.create_connection(("127.0.0.1", DASHBOARD_PORT), timeout=1.0)
        s.close()
        return True
    except OSError:
        return False

def action_dashboard_status() -> dict:
    return {"running": _detect_dashboard(), "port": DASHBOARD_PORT}

def get_service_state(unit: str) -> str:
    if not _validate_unit(unit):
        return "unknown"
    out = _run(["systemctl", "is-active", unit], timeout=5)

    return out if out else "unknown"

def get_service_installed(unit: str) -> bool:
    if not _validate_unit(unit):
        return False
    r = _run(["systemctl", "list-unit-files", "--no-pager", "--no-legend", unit],
             timeout=5)
    return bool(r.strip())

_ROOT_EXEMPT_UNITS = {
    "asterisk.service", "fail2ban.service",
    "ssh.service", "sshd.service", "cockpit.service", "cockpit.socket",
    "sysmon.service", "instmon.service", "44helper.service",
    "nodecontrol.service", "asl_dvs_dashboard.service",
}

_EXECSTART_PATH_RE = re.compile(r"path=([^\s;}]+)")

def _stat_mode_info(path: str) -> dict:
    import grp, pwd, stat as _stat
    out = {"path": path or "", "exists": False, "mode": "", "octal": "",
           "owner": "", "group": "", "world_writable": False,
           "group_writable": False, "root_owned": False}
    if not path:
        return out
    try:
        st = os.stat(path)
    except Exception as exc:
        log.debug("_stat_mode_info: %s: %s", path, exc)
        return out

    perm = _stat.S_IMODE(st.st_mode)
    try:
        owner = pwd.getpwuid(st.st_uid).pw_name
    except Exception:
        owner = str(st.st_uid)
    try:
        group = grp.getgrgid(st.st_gid).gr_name
    except Exception:
        group = str(st.st_gid)

    out.update({
        "exists":         True,
        "mode":           _stat.filemode(st.st_mode),
        "octal":          format(perm, "04o"),
        "owner":          owner,
        "group":          group,
        "world_writable": bool(perm & 0o002),
        "group_writable": bool(perm & 0o020) and group != "root",
        "root_owned":     owner == "root",
    })
    return out

def _perm_verdict(*infos) -> "tuple[str, list]":
    verdict, reasons = "ok", []
    for info in infos:
        if not info or not info.get("path"):
            continue
        label = info["path"]
        if not info["exists"]:
            verdict = _worse_perm(verdict, "warn")
            reasons.append(f"{label}: not readable")
            continue
        if info["world_writable"]:
            verdict = _worse_perm(verdict, "fail")
            reasons.append(f"{label}: world-writable ({info['mode']})")
        if info["group_writable"]:
            verdict = _worse_perm(verdict, "warn")
            reasons.append(f"{label}: group-writable by {info['group']} "
                            f"({info['mode']})")
        if not info["root_owned"]:
            verdict = _worse_perm(verdict, "warn")
            reasons.append(f"{label}: owned by {info['owner']}, not root")
    return verdict, reasons

_PERM_RANK = {"ok": 0, "warn": 1, "fail": 2}

def _worse_perm(a: str, b: str) -> str:
    return a if _PERM_RANK.get(a, 0) >= _PERM_RANK.get(b, 0) else b

_AST_DIR = Path("/etc/asterisk")
_AST_FILE_RE = re.compile(r'^[\w\-]+\.conf$')

_RPT_SECTION_RE  = re.compile(r'^\s*\[([^\]]+)\]\s*(?:\([^\)]*\))?\s*$')

_RPT_KV_RE       = re.compile(r'^\s*([\w]+)\s*=\s*(.*?)\s*(?:;.*)?$')
_RPT_COMMENT_RE  = re.compile(r'^\s*;')
_RPT_NON_NODE_RE = re.compile(
    r'^(general|functions|telemetry|nodes|autopatch|macro|privatenodes|'
    r'dtmf|controlpanel|globals|contexts|channels|skinny|mfcr2)$',
    re.IGNORECASE,
)

_TEMPLATE_SECTION_RE = re.compile(r'^\s*\[[^\]]+\]\s*\(!\s*\)\s*$')

_USRP_RX_RE          = re.compile(r'USRP/([^:]+):(\d+):(\d+)')

def _rpt_callsign(kv: dict) -> str:
    cs = kv.get("callsign", "").strip()
    if cs:
        return cs.split()[0]
    for key in ("idrecording", "idtalkover"):
        val = kv.get(key, "").strip()
        if val.startswith("|i"):
            token = val[2:].strip().split()[0]
        elif val.startswith("|"):
            token = val[1:].strip().split()[0]
        else:
            continue
        if token and token.upper() not in ("NOTSET", "NONE", ""):
            return token
    return ""

_RPT_HDR_RE = re.compile(r'^\s*\[([^\]]+)\]\s*(?:\(([^\)]*)\))?\s*$')

def _rpt_scan_full(content: str) -> dict:
    sections: "dict[str, dict]" = {}
    defined: "dict[str, dict]" = {}
    origins: "dict[str, dict]" = {}
    missing: list = []
    cur = None

    def finish(c):
        if c is None:
            return
        merged: "dict[str, str]" = {}
        origin: "dict[str, str]" = {}
        for t in c["templates"]:
            base = defined.get(t)
            if base is None:
                missing.append((c["name"], t))
                continue
            merged.update(base["merged"])
            for k in base["merged"]:
                origin[k] = base["origin"][k]
        merged.update(c["own"])
        for k in c["own"]:
            origin[k] = c["name"]
        defined[c["name"]] = {"merged": merged, "origin": origin}
        if not c["is_tpl"]:
            sections[c["name"]] = merged
            origins[c["name"]] = origin

    in_block = False
    for line in content.splitlines():
        bare = line.strip()
        if in_block:
            if "--;" in bare:
                in_block = False
            continue
        if bare.startswith(";--"):
            in_block = "--;" not in bare[3:]
            continue
        if _RPT_COMMENT_RE.match(line):
            continue
        hm = _RPT_HDR_RE.match(line)
        if hm:
            finish(cur)
            opts = [x.strip() for x in (hm.group(2) or "").split(",") if x.strip()]
            cur = {"name": hm.group(1).strip(), "is_tpl": "!" in opts,
                   "templates": [x for x in opts if x not in ("!", "+")], "own": {}}
            continue
        if cur is not None:
            m = _RPT_KV_RE.match(line)
            if m:
                cur["own"][m.group(1).lower()] = m.group(2).strip()
    finish(cur)

    node_sects = {s: kv for s, kv in sections.items()
                  if s.isdigit() and not _RPT_NON_NODE_RE.match(s)}
    return {"sections": sections, "nodes": node_sects, "origins": origins, "missing": missing}

def _rpt_scan(content: str) -> "tuple[dict, dict]":
    r = _rpt_scan_full(content)
    return r["sections"], r["nodes"]

def _rpt_first_callsign(node_sects: dict) -> str:
    for s in sorted(node_sects.keys(), key=int):
        cs = _rpt_callsign(node_sects[s])
        if cs:
            return cs
    return ""

def _ini_sections(content: str, sect_re, kv_re, comment_re=None,
                  upper_sect: bool = False,
                  lower_keys: bool = False) -> "dict[str, dict]":
    sections: "dict[str, dict]" = {}
    section = ""
    kv: "dict[str, str]" = {}
    for line in content.splitlines():
        if comment_re is not None and comment_re.match(line):
            continue
        sm = sect_re.match(line)
        if sm:
            if section:
                sections[section] = kv
            section = sm.group(1).strip()
            if upper_sect:
                section = section.upper()
            kv = {}
            continue
        m = kv_re.match(line)
        if m:
            key = m.group(1).lower() if lower_keys else m.group(1)
            kv[key] = m.group(2).strip()
    if section:
        sections[section] = kv
    return sections

def _parse_sections(content: str) -> "dict[str, dict]":
    return _ini_sections(content, _RPT_SECTION_RE, _RPT_KV_RE,
                         lower_keys=True)

_REGISTER_RE = re.compile(
    r'^\s*register\s*=>\s*(\d+):([^@\s]+)@([\w.\-]+)(?::\d+)?(?:/\S*)?\s*(?:;.*)?$',
    re.IGNORECASE,
)
_REG_LIVE_NODE_RE  = re.compile(r'\b(\d{4,6})\b')
_REG_LIVE_BAD_WORDS = ("unregist", "rejected", "failed", "timeout", "timed out")
_REG_LIVE_ADDR_RE = re.compile(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{1,5})\b')
_REG_LIVE_COLS_RE = re.compile(r'^(\S+)\s+(\S+)\s+(\S+)\s+(\d+)\s+(.+?)\s*$')

def get_live_registrations() -> dict:

    out, err = _run_with_stderr(["asterisk", "-rx", "rpt show registrations"], timeout=8)
    if not out:
        return {
            "ok": False, "raw": "",
            "error": err or "no output — asterisk CLI may not be answering",
            "nodes": {},
        }

    nodes: "dict[str, str]" = {}
    perceived: "dict[str, str]" = {}
    for line in out.splitlines():
        m = _REG_LIVE_NODE_RE.search(line)
        if not m:
            continue
        node = m.group(1)
        cols = _REG_LIVE_COLS_RE.match(line.strip())
        if cols and _REG_LIVE_ADDR_RE.fullmatch(cols.group(3)):
            perceived[node] = cols.group(3)
        else:
            addrs = _REG_LIVE_ADDR_RE.findall(line)
            first = (line.split() or [""])[0]
            if len(addrs) >= 2 or (addrs and addrs[0] != first):
                perceived[node] = addrs[-1]
        low  = line.lower()
        if any(w in low for w in _REG_LIVE_BAD_WORDS):
            nodes[node] = "unregistered"
        elif "regist" in low:
            nodes[node] = "registered"
        else:
            nodes[node] = "unknown"
    return {"ok": True, "raw": out, "error": None, "nodes": nodes, "perceived": perceived}

def _reg_addr_path(addr: str) -> str:
    try:
        ip = ipaddress.ip_address(addr.rsplit(":", 1)[0])
    except ValueError:
        return ""
    if ip in ipaddress.ip_network("44.0.0.0/8"):
        return "through the 44Net tunnel"
    if ip.is_private:
        return "a private address (check NAT)"
    return "your public internet address (not the 44Net tunnel)"

_SAVENODE_KV_RE = re.compile(r'^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(\S+)\s*(?:#.*)?$')

_LOAD_RE    = re.compile(
    r'^\s*(load|require)\s*=>\s*([\w.\-]+\.so)\s*(?:;.*)?$'
    r'|'
    r'^\s*(load|require)\s*=\s*([\w.\-]+\.so)\s*(?:;.*)?$',
    re.IGNORECASE
)
_NOLOAD_RE  = re.compile(
    r'^\s*noload\s*=>\s*([\w.\-]+\.so)\s*(?:;.*)?$'
    r'|'
    r'^\s*noload\s*=\s*([\w.\-]+\.so)\s*(?:;.*)?$',
    re.IGNORECASE
)

def module_state(module: str, ast_dir: Path = _AST_DIR) -> str:
    target = module.strip().lower()
    try:
        content = (ast_dir / "modules.conf").read_text(errors="replace")
    except Exception as e:
        log.debug("module_state: %s", e)
        return "blank"

    found_noload = found_require = found_load = False
    for line in content.splitlines():
        ml = _LOAD_RE.match(line)
        if ml:
            directive = (ml.group(1) or ml.group(3) or "").lower()
            name      = (ml.group(2) or ml.group(4) or "").strip().lower()
            if name == target:
                if directive == "require":
                    found_require = True
                else:
                    found_load = True
            continue
        mn = _NOLOAD_RE.match(line)
        if mn:
            name = (mn.group(1) or mn.group(2) or "").strip().lower()
            if name == target:
                found_noload = True

    if found_noload:
        return "noload"
    if found_require:
        return "require"
    if found_load:
        return "load"
    return "blank"

def validate_asterisk_filename(name: str) -> bool:
    return bool(_AST_FILE_RE.match(name)) and "/" not in name and ".." not in name

def read_asterisk_file(filename: str) -> "tuple[str, str | None]":
    if not validate_asterisk_filename(filename):
        return "", f"Invalid filename: {filename!r}"
    return read_path_file(_AST_DIR / filename)

_SU_PIN_GPIO_N  = (1, 2, 4, 5, 6, 7, 8)
_SU_PIN_PP_N    = tuple(range(1, 18))
_SU_SRC_VALUES  = ("no", "usb", "usbinvert", "pp", "ppinvert")
_SU_GPIO_VALUES = ("in", "out0", "out1")
_SU_PP_VALUES   = ("in", "out0", "out1", "ptt", "cor", "ctcss")

_SIMPLEUSB_FIELD_SPECS = {
    "rxmixerset":  {"type": "int",  "min": 0, "max": 1000},
    "txmixaset":   {"type": "int",  "min": 0, "max": 1000},
    "txmixbset":   {"type": "int",  "min": 0, "max": 1000},
    "carrierfrom": {"type": "enum", "values": _SU_SRC_VALUES},
    "rxboost":     {"type": "bool"},
    "ctcssfrom":   {"type": "enum", "values": _SU_SRC_VALUES},
    "deemphasis":  {"type": "bool"},
    "plfilter":    {"type": "bool"},
    "invertptt":   {"type": "bool"},
    "preemphasis": {"type": "bool"},
    "legacyaudioscaling": {"type": "bool"},

    "rxondelay":   {"type": "int",  "min": 0, "max": 100},
    "txoffdelay":  {"type": "int",  "min": 0, "max": 100},
}
for _n in _SU_PIN_GPIO_N:
    _SIMPLEUSB_FIELD_SPECS[f"gpio{_n}"] = {"type": "pin", "values": _SU_GPIO_VALUES}
for _n in _SU_PIN_PP_N:
    _SIMPLEUSB_FIELD_SPECS[f"pp{_n}"] = {"type": "pin", "values": _SU_PP_VALUES}

_DVS_SECTION_RE = re.compile(r'^\s*\[([^\]]+)\]\s*(?:;.*)?$')
_DVS_KV_RE      = re.compile(r'^\s*([A-Za-z_][\w]*)\s*=\s*(.*?)\s*(?:;.*)?$')
_DVS_COMMENT_RE = re.compile(r'^\s*[;#]')

def _dvs_parse_sections(content: str) -> "dict[str, dict]":
    return _ini_sections(content, _DVS_SECTION_RE, _DVS_KV_RE,
                         comment_re=_DVS_COMMENT_RE, upper_sect=True)

def read_path_file(path: Path) -> "tuple[str, str | None]":
    try:
        content = path.read_text(errors="replace")
        if len(content) > 65536:
            content = content[:65536] + "\n; [truncated — file exceeds 64 KB]"
        return content, None
    except FileNotFoundError:
        return "", f"File not found: {path}"
    except PermissionError:
        return "", f"Permission denied: {path}"
    except Exception as exc:
        return "", str(exc)

_IAX_CONF  = Path("/etc/asterisk/iax.conf")
_RPT_CONF  = Path("/etc/asterisk/rpt.conf")
_AB_CFG    = Path("/etc/dvswitch/analog_bridge.cfg")

_IAX_SECTION_RE = re.compile(r'^\s*\[([^\]]+)\]\s*(?:;.*)?$')

def _iax_parse_sections(content: str) -> "dict[str, dict]":
    return _ini_sections(content, _IAX_SECTION_RE, _RPT_KV_RE,
                         comment_re=_RPT_COMMENT_RE, lower_keys=True)

def _iax_collect_iaxrpt_candidates(sections: "dict[str, dict]") -> list:
    _IAX_SYSTEM = frozenset({
        "general", "authentication", "globals",
        "radio", "allstar-sys", "allstar-public",
    })
    candidates: list = []
    for sname, kv in sections.items():
        if sname.lower() in _IAX_SYSTEM:
            continue
        if sname.isdigit():
            continue
        sec_val = kv.get("secret", "").strip()
        if not sec_val:
            continue
        cid = kv.get("callerid", "").strip()
        if "<" in cid:
            cid = cid[:cid.index("<")].strip().strip('"')
        candidates.append({
            "name":     sname,
            "secret":   sec_val,
            "callerid": cid,
        })
    return candidates

def _iax_collect_registers(iax_content: str) -> list:
    registers: list = []
    for line in iax_content.splitlines():
        m = _REGISTER_RE.match(line)
        if m:
            registers.append({
                "node":     m.group(1).strip(),
                "password": m.group(2).strip(),
                "host":     m.group(3).strip(),
            })

    _rpt_http_path = Path("/etc/asterisk/rpt_http_registrations.conf")
    _rpt_http_content, _rpt_http_err = read_path_file(_rpt_http_path)
    if not _rpt_http_err:
        for line in _rpt_http_content.splitlines():
            m = _REGISTER_RE.match(line)
            if m:
                entry = {
                    "node":     m.group(1).strip(),
                    "password": m.group(2).strip(),
                    "host":     m.group(3).strip(),
                    "source":   "rpt_http_registrations.conf",
                }

                if not any(r["node"] == entry["node"] and r["host"] == entry["host"]
                           for r in registers):
                    registers.append(entry)

    _savenode_path = Path("/etc/asterisk/savenode.conf")
    _savenode_content, _savenode_err = read_path_file(_savenode_path)
    if not _savenode_err:
        _sn_node = ""
        for line in _savenode_content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            m = _SAVENODE_KV_RE.match(stripped)
            if not m:
                continue
            k, v = m.group(1), m.group(2).strip()
            if k == "NODE":
                _sn_node = v
            elif k == "PASSWORD" and _sn_node and v:
                if not any(r["node"] == _sn_node for r in registers):
                    registers.append({
                        "node":     _sn_node,
                        "password": v,
                        "host":     "register.allstarlink.org",
                        "source":   "savenode.conf",
                    })
                _sn_node = ""

    return registers

def _dvsm_read_iax_conf() -> dict:
    content, err = read_path_file(_IAX_CONF)
    if err:
        return {"raw_ok": False, "error": err,
                "bindport": "4569", "bindaddr": "0.0.0.0",
                "requirecalltoken": "", "calltokenopt": "",
                "iaxrpt_ok": False, "iaxrpt_secret": "",
                "iaxrpt_callerid": "", "registers": []}

    sections = _iax_parse_sections(content)
    general  = sections.get("general", {})

    bindport  = general.get("bindport",         "4569").strip() or "4569"
    bindaddr  = general.get("bindaddr",         "").strip()
    rct       = general.get("requirecalltoken", "").strip()
    cto       = general.get("calltokenoptional","").strip()

    iaxrpt    = sections.get("iaxrpt", {})
    iaxrpt_ok = bool(iaxrpt)
    secret    = iaxrpt.get("secret",   "").strip()
    callerid  = iaxrpt.get("callerid", "").strip()

    if "<" in callerid:
        callerid = callerid[:callerid.index("<")].strip().strip('"')

    iaxrpt_candidates = _iax_collect_iaxrpt_candidates(sections)
    registers         = _iax_collect_registers(content)

    return {
        "raw_ok":             True,
        "error":              "",
        "bindport":           bindport,
        "bindaddr":           bindaddr,
        "requirecalltoken":   rct,
        "calltokenopt":       cto,
        "iaxrpt_ok":          iaxrpt_ok,
        "iaxrpt_secret":      secret,
        "iaxrpt_callerid":    callerid,
        "iaxrpt_candidates":  iaxrpt_candidates,
        "registers":          registers,
    }

def _dvsm_read_rpt_conf() -> dict:
    content, err = read_path_file(_RPT_CONF)
    if err:
        return {"raw_ok": False, "error": err, "callsign": "", "nodes": []}

    sections, node_sects = _rpt_scan(content)

    callsign = _rpt_first_callsign(node_sects)

    nodes: list = []
    def _flag(kv: dict, key: str, truthy: "tuple") -> bool:
        val = kv.get(key, "").strip().lower()
        return val in truthy

    for nid in sorted(node_sects.keys(), key=int):
        kv   = node_sects[nid]
        rxch = kv.get("rxchannel", "").strip()
        um   = _USRP_RX_RE.search(rxch)
        nodes.append({
            "id":                    nid,
            "private":               int(nid) <= 1999,
            "rxchannel":             rxch,
            "usrp_rx":               um.group(2) if um else "",
            "usrp_tx":               um.group(3) if um else "",
            "propagate_dtmf":        _flag(kv, "propagate_dtmf",        ("yes","1","true")),
            "propagate_phonedtmf":   _flag(kv, "propagate_phonedtmf",   ("yes","1","true")),
            "remote_dtmf_allowed":   _flag(kv, "remote_dtmf_allowed",   ("1","yes","true")),
            "phonesendlinks":        _flag(kv, "phonesendlinks",         ("1","yes","true")),
        })

    public_nodes  = [n for n in nodes if not n["private"]]

    return {"raw_ok": True, "error": "", "callsign": callsign,
            "nodes": nodes, "public_nodes": public_nodes}

def _dvsm_read_ab() -> dict:
    _AB_CANDIDATES = [
        Path("/opt/Analog_Bridge/Analog_Bridge.ini"),
        Path("/etc/Analog_Bridge/Analog_Bridge.ini"),
        _AB_CFG,
    ]

    for cand in _AB_CANDIDATES:
        content, err = read_path_file(cand)
        if err:
            continue
        sections = _dvs_parse_sections(content)
        usrp     = sections.get("USRP", {})
        rx_port  = usrp.get("rxPort",  "").strip()
        tx_port  = usrp.get("txPort",  "").strip()
        address  = usrp.get("address", "").strip() or "127.0.0.1"

        if rx_port or tx_port:
            return {
                "raw_ok":  True,
                "error":   "",
                "source":  str(cand),
                "address": address,
                "rx_port": rx_port,
                "tx_port": tx_port,
            }

    for cand in _AB_CANDIDATES:
        content, err = read_path_file(cand)
        if not err:
            sections = _dvs_parse_sections(content)
            usrp     = sections.get("USRP", {})
            return {
                "raw_ok":  True,
                "error":   "",
                "source":  str(cand),
                "address": usrp.get("address", "").strip() or "127.0.0.1",
                "rx_port": "",
                "tx_port": "",
            }

    return {
        "raw_ok":  False,
        "error":   "Analog_Bridge.ini / analog_bridge.cfg not found",
        "source":  "",
        "address": "",
        "rx_port": "",
        "tx_port": "",
    }

def _usrp_pairs_scan() -> dict:
    rpt = _dvsm_read_rpt_conf()
    chans = [n for n in rpt.get("nodes", []) if n.get("usrp_rx")] if rpt.get("raw_ok") else []
    bridges: list = []
    ab = _dvsm_read_ab()
    if ab.get("raw_ok") and (ab.get("rx_port") or ab.get("tx_port")):
        bridges.append({"bridge": "Analog_Bridge", "listen": ab.get("rx_port", ""), "send": ab.get("tx_port", ""),
                        "source": ab.get("source", "")})
    m17 = _m17_read_config()
    if m17.get("raw_ok") and (m17.get("usrp_local_port") or m17.get("usrp_dst_port")):
        bridges.append({"bridge": "USRP2M17", "listen": m17.get("usrp_local_port", ""),
                        "send": m17.get("usrp_dst_port", ""), "source": m17.get("ini_path", "")})
    pairs: list = []
    used: set = set()
    for n in chans:
        a, b = n["usrp_rx"], n["usrp_tx"]
        match = [x for x in bridges if x["listen"] == a]
        if not match:
            pairs.append({"node": n["id"], "a": a, "b": b, "bridge": "", "state": "no_bridge"})
        for x in match:
            used.add(x["bridge"])
            pairs.append({"node": n["id"], "a": a, "b": b, "bridge": x["bridge"],
                          "state": "ok" if x["send"] == b else "mismatch", "send": x["send"]})
    unpaired = [{"bridge": x["bridge"], "listen": x["listen"], "send": x["send"], "source": x["source"]}
                for x in bridges if x["bridge"] not in used]
    return {"version": VERSION, "rpt_ok": bool(rpt.get("raw_ok")), "pairs": pairs, "unpaired": unpaired}

_STFU_AB_CANDIDATES = [
    Path("/opt/Analog_Bridge/Analog_Bridge.ini"),
    Path("/etc/Analog_Bridge/Analog_Bridge.ini"),
]
_M17_INI_CANDIDATES = [
    Path("/opt/USRP2M17/USRP2M17.ini"),
]
_M17_PLACEHOLDER_ADDRESS    = "0.0.0.0"

def _m17_read_config() -> dict:
    ini_path = ""
    content  = ""
    for cand in _M17_INI_CANDIDATES:
        c, err = read_path_file(cand)
        if not err:
            ini_path = str(cand)
            content  = c
            break

    if not ini_path:
        return {
            "raw_ok": False, "ini_path": "", "error": "USRP2M17.ini not found",
            "callsign": "", "address": "", "name": "",
            "m17_local_port": "", "m17_dst_port": "", "m17_gain": "",
            "usrp_address": "", "usrp_dst_port": "", "usrp_local_port": "",
            "usrp_gain": "",
            "display_level": "", "file_level": "", "file_path": "", "file_root": "",
        }

    sections = _dvs_parse_sections(content)
    m17_net  = sections.get("M17 NETWORK", {})
    usrp_net = sections.get("USRP NETWORK", {})
    log_sec  = sections.get("LOG", {})

    return {
        "raw_ok":          True,
        "ini_path":        ini_path,
        "error":           "",
        "callsign":        m17_net.get("Callsign", "").strip(),
        "address":         m17_net.get("Address",  "").strip(),
        "name":            m17_net.get("Name",     "").strip(),
        "m17_local_port":  m17_net.get("LocalPort",    "").strip(),
        "m17_dst_port":    m17_net.get("DstPort",      "").strip(),
        "m17_gain":        m17_net.get("GainAdjustdB", "").strip(),
        "usrp_address":    usrp_net.get("Address",      "").strip(),
        "usrp_dst_port":   usrp_net.get("DstPort",      "").strip(),
        "usrp_local_port": usrp_net.get("LocalPort",    "").strip(),
        "usrp_gain":       usrp_net.get("GainAdjustdB", "").strip(),
        "display_level":   log_sec.get("DisplayLevel", "").strip(),
        "file_level":      log_sec.get("FileLevel",    "").strip(),
        "file_path":       log_sec.get("FilePath",     "").strip(),
        "file_root":       log_sec.get("FileRoot",     "").strip(),
    }

_M17HOSTS_DEST = Path("/var/lib/mmdvm/M17Hosts.json")
_M17HOSTS_URLS = [
    "https://hostfiles.refcheck.radio/M17Hosts.json",
    "https://m17-project.github.io/hostfiles/M17Hosts.json",
]
_M17HOSTS_UA             = "sysmon M17 host updater - KD8PGK"
_M17HOSTS_TIMEOUT        = 45
_M17HOSTS_MIN_BYTES      = 2048
_M17HOSTS_MIN_REFLECTORS = 10
_M17HOSTS_STALE_SECS     = 24 * 3600

def _m17hosts_validate(raw: bytes) -> dict:
    if not raw:
        return {"ok": False, "count": 0, "generated": "", "error": "file is empty"}

    if len(raw) < _M17HOSTS_MIN_BYTES:
        return {"ok": False, "count": 0, "generated": "",
                "error": f"only {len(raw)} bytes (need >= {_M17HOSTS_MIN_BYTES}) — truncated or an error page"}

    if raw.lstrip()[:1] == b"<":
        return {"ok": False, "count": 0, "generated": "",
                "error": "body starts with '<' — that is HTML, not JSON"}

    try:
        doc = json.loads(raw.decode("utf-8", "replace"))
    except Exception as exc:
        return {"ok": False, "count": 0, "generated": "", "error": f"not valid JSON: {exc}"}

    if not isinstance(doc, dict):
        return {"ok": False, "count": 0, "generated": "",
                "error": f"top level is {type(doc).__name__}, expected object"}

    refs = doc.get("reflectors")
    if not isinstance(refs, list) or not refs:
        return {"ok": False, "count": 0, "generated": "", "error": "no non-empty 'reflectors' array"}

    usable = sum(
        1 for e in refs
        if isinstance(e, dict) and e.get("designator")
        and (e.get("dns") or e.get("ipv4") or e.get("ipv6"))
    )
    if usable < _M17HOSTS_MIN_REFLECTORS:
        return {"ok": False, "count": usable, "generated": "",
                "error": f"only {usable} usable entries of {len(refs)}"}

    meta = doc.get("_refcheck_metadata") or {}
    return {"ok": True, "count": usable, "generated": str(meta.get("generated") or "unknown"), "error": ""}

def _m17hosts_fetch() -> dict:
    import urllib.request as _urllib
    import urllib.error   as _urlerr

    last_error = "no source URLs configured"
    for url in _M17HOSTS_URLS:
        try:
            req = _urllib.Request(url, headers={"User-Agent": _M17HOSTS_UA})
            with _urllib.urlopen(req, timeout=_M17HOSTS_TIMEOUT) as resp:
                raw = resp.read()
        except _urlerr.HTTPError as exc:
            last_error = f"{url}: HTTP {exc.code}"
            continue
        except Exception as exc:
            last_error = f"{url}: {exc}"
            continue

        v = _m17hosts_validate(raw)
        if not v["ok"]:
            last_error = f"{url}: {v['error']}"
            continue

        try:
            _M17HOSTS_DEST.parent.mkdir(parents=True, exist_ok=True)
            existing = _M17HOSTS_DEST.read_bytes() if _M17HOSTS_DEST.exists() else b""
            if existing == raw:
                os.utime(_M17HOSTS_DEST, None)
                return {"ok": True, "changed": False, "source": url,
                        "count": v["count"], "generated": v["generated"], "error": ""}
            _atomic_write(_M17HOSTS_DEST, raw.decode("utf-8", "replace"))
        except OSError as exc:
            return {"ok": False, "changed": False, "source": url,
                    "count": 0, "generated": "", "error": f"write failed: {exc}"}

        return {"ok": True, "changed": True, "source": url,
                "count": v["count"], "generated": v["generated"], "error": ""}

    return {"ok": False, "changed": False, "source": "",
            "count": 0, "generated": "", "error": last_error}

def _probe_socket(port: str, proto: str) -> bool:
    try:
        flag = "-tlnp" if proto == "tcp" else "-ulnp"
        raw  = _run(["ss", flag], timeout=4)
        return f":{port}" in raw
    except Exception as e:
        log.debug("_probe_socket: %s", e)
        return False

def run_quick_tests(pinned: list) -> dict:
    results: dict = {}
    for entry in pinned:
        if "group" in entry:
            continue
        unit = entry["unit"]
        if not get_service_installed(unit):
            results[unit] = "na"
            continue

        state = get_service_state(unit)
        if state not in ("active", "activating", "reloading"):
            results[unit] = "fail"
            continue

        ok = True

        port  = entry.get("port",  "-")
        proto = entry.get("proto", "-")
        if port not in ("-", "parse", "", None):
            if not _probe_socket(port, proto):
                ok = False

        cfg_path = entry.get("config", "-")
        if cfg_path not in ("-", "parse", "", None) and ok:
            try:
                p = Path(cfg_path)
                if not p.exists() or p.stat().st_size == 0:
                    ok = False
            except Exception as e:
                log.debug("run_quick_tests: %s", e)
                ok = False

        results[unit] = "pass" if ok else "fail"

    return results

def _ss_tlnpu_fetch() -> str:
    return _run(["ss", "-tlnpu"], timeout=6)

def _parse_ss_entries(raw: str) -> list:
    entries = []
    for line in raw.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 5:
            continue

        proto = parts[0].lower()
        if proto not in ("tcp", "udp"):
            continue

        local = parts[4]
        if not local or local == "*" or ":" not in local:
            continue

        port_str = local.rsplit(":", 1)[1]
        addr     = local.rsplit(":", 1)[0]
        if not port_str.isdigit():
            continue

        proc_raw = " ".join(parts[5:])
        pid_m  = re.search(r"pid=(\d+)", proc_raw)
        proc_m = re.search(r'"([^"]+)"', proc_raw)
        pid    = int(pid_m.group(1))  if pid_m  else 0
        proc   = proc_m.group(1)      if proc_m else ""

        entries.append({
            "proto": proto, "port": port_str, "addr": addr,
            "pid": pid, "process": proc,
        })
    return entries

def check_port_duplicates() -> dict:
    raw = _ss_tlnpu_fetch()
    if not raw:
        return {}

    seen_pid:  "dict[str, set]" = {}
    all_procs: "dict[str, list]" = {}

    for e in _parse_ss_entries(raw):
        key = f"{e['proto']}:{e['port']}"
        if key not in seen_pid:
            seen_pid[key]  = set()
            all_procs[key] = []

        if e["pid"] not in seen_pid[key]:
            seen_pid[key].add(e["pid"])
            all_procs[key].append({"pid": e["pid"], "process": e["process"] or "unknown"})

    return {k: v for k, v in all_procs.items() if len(v) >= 2}

_state: dict = {

    "hostname":   "…",
    "kernel":     "…",
    "uptime":     "…",
    "load":       {},
    "memory":     {},
    "swap":       {},
    "cpu_temp":   None,
    "pi_voltage": None,
    "throttle_state": None,
    "disk":       {},
    "sd_health":  None,
    "proc_count": None,
    "start_time": time.monotonic(),

    "quick_tests":    {},

    "port_conflicts": {},

    "reg_live":       None,
    "reg_summary":    None,

    "needs_restart":  False,

    "wifimon_shutdown": {"active": False},
}
_state_lock = threading.Lock()

def _read_wifimon_shutdown_state() -> dict:
    try:
        with open(WIFIMON_SHUTDOWN_STATE_FILE, "r") as f:
            d = json.load(f)
        if not isinstance(d, dict) or not d.get("active"):
            return {"active": False}
        return {
            "active":  True,
            "reason":  str(d.get("reason", "")),
            "trigger": str(d.get("trigger", "")),
            "since":   d.get("since"),
        }
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        return {"active": False}

def get_state_snapshot() -> dict:
    with _state_lock:
        return dict(_state)

def _update_state(**kwargs) -> None:
    with _state_lock:
        _state.update(kwargs)

_BG_STALL_SECS   = 180.0
_HTTP_STALL_SECS = 25.0
_PROBE_EVERY     = 10.0
_bg_beat = time.monotonic()
_http_ok_at = time.monotonic()

def _health_probe_loop(host: str, port: int) -> None:
    global _http_ok_at
    import http.client
    while True:
        time.sleep(_PROBE_EVERY)
        conn = http.client.HTTPConnection(host, port, timeout=5)
        try:
            conn.request("GET", "/healthz")
            resp = conn.getresponse()
            resp.read()
            if resp.status == 200:
                _http_ok_at = time.monotonic()
        except (OSError, http.client.HTTPException):
            pass
        finally:
            conn.close()

def _heartbeat_problem(now: float) -> str:
    if now - _bg_beat >= _BG_STALL_SECS:
        return f"background poll stuck for {int(now - _bg_beat)}s"
    if now - _http_ok_at >= _HTTP_STALL_SECS:
        return f"web server not answering /healthz for {int(now - _http_ok_at)}s"
    return ""

def _sd_heartbeat_loop() -> None:
    try:
        usec = int(os.environ.get("WATCHDOG_USEC") or 0)
    except ValueError:
        usec = 0
    if usec <= 0:
        return
    every = max(1.0, min(10.0, usec / 1e6 / 3))
    stalled = ""
    while True:
        problem = _heartbeat_problem(time.monotonic())
        if not problem:
            if stalled:
                _log("heartbeat: healthy again")
                stalled = ""
            _sd_notify("WATCHDOG=1")
        elif problem.split(" for ")[0] != stalled.split(" for ")[0]:
            stalled = problem
            _log(f"heartbeat: {problem} — letting systemd restart SysMon", stderr=True)
        time.sleep(every)

def _bg_poll_loop() -> None:
    global _bg_beat
    _log("bg_poll: started")
    poll_count = 0
    while True:
        _bg_beat = time.monotonic()
        try:
            _update_state(
                hostname   = get_hostname(),
                kernel     = get_kernel(),
                uptime     = get_uptime(),
                load       = get_load(),
                memory     = get_memory(),
                swap       = get_swap(),
                cpu_temp   = get_cpu_temp(),
                pi_voltage    = get_pi_voltage(),
                throttle_state= get_throttle_state(),
                disk       = get_disk_usage(),
                sd_health  = get_sd_health(),
                proc_count = get_proc_count(),
                wifimon_shutdown = _read_wifimon_shutdown_state(),
            )
            poll_count += 1

            if poll_count % 3 == 0:
                try:
                    qt = run_quick_tests(_pinned)
                    _update_state(quick_tests=qt)
                except Exception as exc:
                    _log(f"bg_poll: quick_tests error — {exc}", stderr=True)
                try:
                    pc = check_port_duplicates()
                    _update_state(port_conflicts=pc)
                except Exception as exc:
                    _log(f"bg_poll: port_conflicts error — {exc}", stderr=True)

            prev_reg = get_state_snapshot().get("reg_summary")
            if poll_count % 3 == 0 or not prev_reg or prev_reg.get("state") != "ok":
                try:
                    rl = get_live_registrations()
                    _update_state(reg_live=rl, reg_summary=_reg_live_summary(rl, prev_reg))
                except Exception as exc:
                    _log(f"bg_poll: reg_live error — {exc}", stderr=True)

            if poll_count % 360 == 0:
                try:
                    st = _M17HOSTS_DEST.stat() if _M17HOSTS_DEST.exists() else None
                    if st is None or (time.time() - st.st_mtime) >= _M17HOSTS_STALE_SECS:
                        r = _m17hosts_fetch()
                        if not r["ok"]:
                            _log(f"bg_poll: M17Hosts.json refresh failed — {r['error']}", stderr=True)
                        elif r["changed"]:
                            _log(f"bg_poll: M17Hosts.json refreshed — {r['count']} reflectors "
                                 f"(source: {r['source']})")
                except Exception as exc:
                    _log(f"bg_poll: m17hosts error — {exc}", stderr=True)
        except Exception as exc:
            _log(f"bg_poll: error — {exc}", stderr=True)
        time.sleep(10)

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>System Monitor</title>
<style>

@font-face{font-family:"Readex Pro";font-style:normal;font-weight:400;font-display:swap;src:url(data:font/woff2;base64,d09GMgABAAAAAC2sABAAAAAAZgwAAC1LAAE0ewAAAAAAAAAAAAAAAAAAAAAAAAAAGoEAG7JWHIYsBmA/U1RBVEQAg2wRCAr5ON9SATYCJAOHaAuDfAAEIAWEIgcgDAcbFlZFB2LGOAAw457LKGqiHDWVKEr2KJD9f0hujIEXoF4tu4phMmSIOuGMYNLMoJGGYbmrbW6R78v3vXfP/6zq2Wf2FYauiUYcmM0jJJltD/g5/XsvEEgIUCAEiRoRJQbEhAhigQCBQEJLgVIqUKNmk85rApM6/e1voTKrza3b6KqyeSFyE4+nkOYNE2QSXf1mpkbMSHc8//1+wH7tcx8m1vBm5lE04tmbR2hMZwiJkKCSzP7fR21WVZCcdIX1MGorrqctGVjLiJ4LfMl73TJmdt9+vzcLjVI4nZBJhURIJNuE5Rs5JNHFdBEbxAb7Msg8mS/7ZJ/sFft3U3MvZBzwwxhDdanKCtcC+B9aZ2sLLSyUh3EPTjxUtTU830/9pD5zt7W3aVVpXSjcn6fAEBj29J5i7fWLtnTZu+NQb+8arWflElT9JwCFJYBtQSmlDw8KbMNDSCgLw/n/dfqu71n1OS9hldDplHTj2SkArN27X+nZwjjGgOyADG0tf5L9yfmsj/qIkzMWcOoou+SkgDABjgQb4t6NhmXGYZ17utff+7a+F2o6S1yZDEcjRkTs93v7/bD1Ctmf/MvX7Ekt5WURCU7ISEZEgmfP43cBCAACADUAFBbCAeEShKhQA1FvDsRc86HueQSRIVk+BikTO9RwOwAiaUMWQSj+vLcOMvsVwvmYOfcIrD8cAE/EAHPxpeXVQHysv2MaEJ+ODvQAURIAKE1XfOqR/h5IBYBCaoM96LMrp8Ig7Lxu570Q561nt6TpMRrKstw/eUO2z4/5MN8rGfsYkYoWTmimzvzZMBNzcT6envbj3H1UF83j/uX094vBRovYlU0rsOrXwrV7HV7nF87+69/eUpNYm2ALbE3b1K1ve3GH+h3xWMqOp3ZK7LRkp+078/D27p0rofIhUgDg4LUgSF+USCYN6X+XgIwqHZPYFBISZCrFKPTMmKyshJwCROrVUwmLU+vSxarPbDZzzeU1YpTPXof4jTmiyrgJNU45o847zgr7wIciUhyqdqSBYwXHC04UvFvjbA3UWNHJCoyTiN4hcJYABqmOXo8k90+Dr5UmEGHCgg0HLjz4iO6PcayTjnOinuwbg7EokpG4BW35eHK6LMlIRkfFujL3+HR9MPobfd434O1FtL/igAIHJTlUD/PWYrxnsMB2qDtwi1GIQseaJQIrnOh82FP4Q1q1T4qPBS1saBmRM1ouPnxQd39YgNHouokI4oT7igrK2Ehy4S0gSORKb6JBHCnBI3RhefjEcsgi/0A8/6xAjSacvYd5jq65XKjqhlXV9ALIp0CDOoRorAKnrxF4CoxQwPNDuI/jbIgC7Sur9oc2tRAWIQnZoAKGJ45XOsmcgOtaHULiWT+sSbwctBGaXWQWosXFSTRvEqikojpe3TnaKsXS6ytqmytFnH4VDtIVZTAkkQyWlJ3kas7UK1T9d1ZaFUpKoxCD198qJJQh0Gg0Go127vuzPljyBIEVMCSRDJaUCF+UFoheC8BUZRFsOHDhwUcUGQqMmCihlDLM2LDj6Dv7iwvqBh68+PAToZkWWonSRjudV0qUdLWgr0mgnSL4zE0IIkxYsOHAhQcfUVxSQ1WkjrSdUxwZABgxUUIpZZixYccRdzbDBcCNBy++eC2TCIBmWmglShvtdF6pq1V9rehvksjHf3D2hw6pzvFZAviSNILYJxcxVVmADQcuPPiIIkOZERMllFKGGRt2HDhx4caDF9/x/qbUool0bQYttBKljXaNRVGHTJ37iyAF+EIaxPTYUgGGYRiG4Tqn/7Z1mkS/oKjPG61HKdhKryFF+/rkGsPkzFxRcrJvKDIKJkoopQwzNuw4cOLCjQcvvjSxQRAEQRC0uH8qpAYKhiSSwZKyk1wFLRCu1PXTSHpqcpPIgJW4s05fyQxmMsCs3xhBkAQAkQ2BoMLIAJADIBcAunsSJAHClXscJcECAAAqKnbXaS/j+QLcQTPbKrbFz1W9wEeJBe8GqfDvaDpJrCGnBnlpp7X+hs+8cf2Ctutlq7sx/X+wdes5oXPd95/LfXAa6FBk+r3rda0EeMWPAo9XM15tamGooKLCrdK9DNvcZ3T6WOhdHePAMmoSWj6qxrdRinYVnkFbR6ZzPx9Dte6C2g1A9cCmDULIQYsOoj5X5kCfXQR2w+ufIknG12WSBgljxlEV33KqvCzvbM9pPO1hLhHac/HeMB2NNW+INAMvk4qqBxCFmpXVLue8GOEDOKAdZXOWKGNy4W2Sl5nMKMmSfUPLK7JBZCySOFDGVFdZ3i+HNFBF6FRFT3tbWw+4pFp01F3dQ9CPTMIvy5RPlEloX17FSlkzl1zpYj0f1o7zbi+SC0M56Jp/fiIhc6gkP6VpkTxQtvm0c8sAYrXpLCBj4LyTun5Mk7UzjsEt1xbxZJ1nGcSOJwyN4/GX888BLVlOi2c18HDa12MZ2CVgMyryWUvifV5OraPapJUSNWVqcw+SV67M5Of+48n4f4mPNvOXyZchWPjzaJ7JFV9nySbixaDpmt89h0JcXHxCmOo9HAGCIwnIW9axSAzveODupmXo3O0qy/X85Fvjw1tUhZ11x6GsripLTyu3Y3QvqL3hAoZnffwU8CgH8f5yVfEbTpQ8EqTb5MRLrdpPlxdqg3ZbqanSXMl4vqTT5ApJS9W5FVaCX+bmXAs/L7lXypXMPgS5XldluZ3vZvm24h2u8ZhKBagWZ8YzwDnPJ/6+LqiK1JptmLSSAs2onCGDeZuE8x43k8z9plqlLrsWyPItgx4sVf/42QSVBoEDQECEQ0aVjcksl1WQRoVaNvXm8xgxqscpZ/R529tmetdZA1AmiBQYqVIlwcHhIkiHyJAtSY4cPEREecjI0lBQMFB97c+HEBCeVXQ0CLHJUWTwJPF8UkrJVIZPbcg0cQGtYhl0hkRv0ljjKBu7Ag5D5YwjXHywyg2b3xQKmFTBOE6FGji1hqDe0DX0M4U1xftHdEB1wgjFDVHCpOsyqKnxXNP0StFnxGYYiv54kZlmmWK2yTLHEMw1bIOGYMhkmmdw5odMgoUlNDgWhuPsThGUmmZJkvzjUXhpMAgkaIGRSwHlIbcOaCUYQQUjqOAkU7BCliyhCOHB2QzMEFK7PgidkjZ3iqMQUrdBKnmk9NshYkdD09FOJXIxRFIEL2mSIcnCkBxhSroSuT9fmhEydKOBSpjkFQXeQbuQtsUKKPy6qVD4ZEPIJQHIMSKs1VR9hgwb3Ut3Hva+T7/NJb95GBQQORYZttgSSy2zwqoYFWOOLHp6+fof+sYlP0P8XIRaWnEaHmKsDLXYXrWicjDCGa7t6tJAl6uulO0jnfsxYqP8nOTcqzcXWIu6XQFBGIWICT3SFOODlosToEQna2EEWeqMwTiGFYDW/FMEiiMJgFIp9A5lOyI5vP7b3oU0ME7XRWGJl6SAoVwQQQUJqOUevB8z8DMqtzzQH20z+ZQXlUq54E4HA0ovslQ3E7qo8vq2qyzh6weuLbevX3Gz7vqXb670Hf46ePLE8N7BSFOXm6OTmubJzbHNU5qnNseB//uEhx6a3gfeh3t6p0PoP/72LlD7dFc8Cq1P97Z3Q+erdEu/zJWFsuzgNc/Omt4PzwAGYKQFTPEMGWqYwgWRFEEFI1hJkuSj8bJweB8v3mydt3wcLEy6jx0ILU0p2UBItd2JypYPWcwzn68qF+w1QCy6WMkIekFJ3TgNCo8IUX0P5Jo51B6NylMBaxm8QtEBEg3p1wAGqCmbBsD5nE2ERSAp9QPdWQJ44+L+GR5zMESoWWSVNYCthgVDtrECA5DZQ2zXzReBvnG1DcBLcMw8Z3NIYo4FrQjJZ9STKVgEBmHoDEM8ajAXunMeVJBqT0OC906ahjwjGaBvTz0AX/XmyL2UMWpvHwYYS83c/z/nfeEMxrHZmKttAkj6esQ4f+PKAd0DnQDAgIGgYlHAvyLOlV9+SX0IQQDmPJYYQJKoxpTpAdCQAICDjBr0DIWQAT7PKlHPCzYpXydIpmTWj1NGb6EnDCKjkEFlsBg8VvaTBMAgZ7D96BxGPoOiyw8CgEtfyF388tLwpf4fzwBBAqB0AiDPaf/7Cru94T2Hfe2KD71vwkmHfGfUMSPGvOo1P/vJJft8AIGDR5AhB1EuEjIKKho6JgERsSISUipqGlo6ZxzxpsvG3WdgZePgUs4vIKhWvQZhjSJiOsUlTDVNnxn6zTTbKZ877Vd77PWlb3zlW1/42D2fWOCcSf/3qYc+84uttnngNx854JEtFjpvpx122S8ZCiNFEqxUabJlmiJLoTz5CqRj4GJh4+P4AY+SjJxCMaEupYxMzEqUsbDzcfPwqlGhUhWnJlHNWrRr9aM2vbpN12NAh1neddZbEEgTCwDAvwAA+QdAdgLI/A7k3giQ9DrA7A0AAADtIqJVnOIQtV16bbXw+bAw6sItokG0FSGty/pFb0tANPyzxWpBfKpoTcU8vHJ84I0u/Y8UeM6ODdMsU1sRLg0ATFZYv2+UNEezRu3RV4lmAQdGhfOgoLJYGDfGJzAiwCwpOZQlI9SJWocHJMgya/cwximsUeSHEDZmqCLPUlAqdLH7ZgjcRxd+UY+K6IdfVstExYPoK8cl/R2IInS9s89eBCyXM7BWfN+3jrUWDXgWoZDgklxunqukNRFqxTq7boXSS0fTky0JFjzI/WZQKrBpo+g4rC0KjdDxn8xtdl/ZkHnJak5kDE9s3Bt6h/b2juDC66m9Pga6N3osEQ/c7Xhhi3xVLQciKqdSZt1Nl+vNnPsxmWJDShnCOduAADzfFgwo0rNKyG9E0BI48Cw2iSqzi0xShKA7jDOGiwfUoPvqDXv40IwukSlr3sa7MfMgmsFBMGTvM1vEe0O3RD/A4dOVSZMiZGEFXTy/zFiMjQaETNy6PAhoBhRloO9KPgsXYFAzmWlADDJK3GEefJVXvxZY1dcgJJ1RFaYRCO823R2vqvqmmcv7dfyuGkoW0y/pnFGkCknIUG5J7vli8jHdJSopxKyUJaA5+aUbnuJlRDdUFrMrffEENGRiUJJ8c63YllFeDOKr30XJZpQ++rAjY5oeAg1zKG3v4A0SUHM4wIv72yJVmLflsYalcou2EV3GoxuVak9eWQ+6bLR9fP/weThuvlWneD1m3qUTHKFtbN+QuTpwYk2nUPERMAZ10pz9oa58p8NFo4xHepA8eRKX+UhrSLGphG7e6MqLYHbRHsXYner59pYn2HSdWcHQaquIcgtXFYuQLW0y9DSWsum2FyiNsDwugAaUxBtg6O6PeXCrHAg0BRr3dpxkMyHitTlvvR8J2g6MqRJE5WdRGAqMWHy6jBPRAeNUTiQs2Dmn7dIhcZWXv3/fGyDZwSZutNlbfKoODsnrme6OzwHmJ818NM5MxIUSTh8ED9xTwgSes4s/fHmmFJduEZXQ9NZP9UGmTj6G5PiTWxHHqKddfokPO0o1hOY9pGT5572iBD/ocCGWUhMDcgKi5PefvW7id03W9fvga7GjlXt9h9WHmJ6LwfufqYJ54r2trSqYiXt6TYvW4JOTn7TMZ//oODLdTcf3epfOStAm5ZhjFW96A7ojRXpwOtUQMvJHLXXg4t/vz/meoaSikkuMZJZy0gWZtOt9SWYC4wn/UNEfe+A5wq6a2s7XeIRJssSwPv0VSXt+kYQsFyHzZH4C89HfRJPq/ObjczR7Woj4eEE3iYb1FFgCOzgQLqVomusgOWwEf3b8TqNaSazRj6sqNN+IVfEI3cPddv/wzQ/F7dzKTTzaNjMvf30f7jDBO82+IZs+KGNBYW371x9+9+nn1Hl8B3pLr5wKJ0zY9bFxZ6Y5NvrBIqRy3SnKADenQU8NHsypnMefxczXM226rorKZypHZVZWyJDxFolNuatswaOrCyXKAuXOvKBIH3OcsBiOe1Jgxm3vNRF4pjqkI2kMU5x4UkZWdJflck/gCB/sPdQ5rllav4fhg/8KeLBI+Q9xqcjH0QCSqmIcaEA3bGfeozdRNthL8iZxlG/eRYh7q55jNfQe2JN03CFvzJRqUwCNbVH4XpVU57ZfyfBnhUwDArKYSmT8tOrLIx6rMj1PaQel/UDe8nwYjGx8TJjJTUpRkNeW0kRZ88ervD8o06PittEpmhVjoiSsK8p6Zg7ENr/qMUaZyb3xTThUWdb5I1+5EBEasy2qcYWo0gjGyLT/W1qSzb+7iZ3cCjGweNzyPCVIFKffmIUedxH0KAftvefVuMhN1hs/q3lW/SZNlMecjrXsM2/eVGC6cn3DbpXFkAQ371E2I0+j+QRMJtNGzMplGMf+MGgPrzuhzONja2Bb+OZHQLmekSD0jyp3zTp5t0TTd/LVHyo9eTri9THb4DiE9jaJtCu0kfodYzyw4e3wEjfzc04q02yavSunB1Fb61Ub5ShiyK545vlnTP3QXROS0mDxMKycSsRc1nu8Y0UlNj7Kogso0tRNRaJTvbym4HuumsotC+0XaAmAhRLNUB2VGXJKjpCe/YbbSyY3ypq90HeRc0dqN6ZYDMLOuPou0FClsNSuKPVYGCijvFf/+CPPPpLuua2IS7VBnhGmJG4qwVGclEFh3KLrebgabiu2rlT8TX+E/6I/FRrwzHc5qOEBourL4pQQ4qtiFZVf4zOHh3F3PSo7ZD9DavmjfMokGi+1IPzRzppjgDvJ2D4hW0DDInkhOD45JO3er4ZQV922EO0jYI2f5WjiYwNYjM8kEEgb/JeBYz6yvbY+Cz7anGOtD3Cc4AcGnNo+3vFG1zVJv4WTSqK6xmOE+kxtkJ8LsG0KBYQX87iw44kjt+rhUkLc44uG4mtd0k5FofvO1vaemcUrVH3iiBg1suX3pTzi9pn8+ZxlXi3jZXTpz9TsXBKvflVSV86Y9HXFiU3itkdhjRikRSNvYSWDnsPDIOnbjtJKho/509gZX376SHiXa7+823bXF3mehLy2LLGEUl/lz2I7blZdiLftb8+WW6koXtfvwen3iSbUF+q8r23nOO757fqLQWqMIuAGYCn8irNrqdhanBGX9NXZazIlLwiGCZtlOYBm38lC11xy8SyjgoPeN0XlgjbxMX0kdNJuyvLkX2e9eRxT9GQkSNSSIB/S4FIJSUsU0H7dPC6N4YeyAJ9vBteFZkudlHxH0BVfJj89+DfecRuP3sijNo7iHpTnwl7h4ey75QUmu1d2RIp9RVG5k8nfAVkugw2JYciTcUonLe+Ymya/6OvC27L4S/nhcc+NoutVUMT5AI793lJlO1Zuu4wm8yFPhSE/D/PFbQzrcIGaR2JB2WzeLd/OYBHmYsk2Be8Ub7SKFy+cePR7zArgas1GxVxm5YSEnzQnaaOlo+FkrwcfT6PrcmU0PgaK35KtPUi8BpJGiV279rlwXWB5sJfPhnYmvW/llUslbp2W6Y4rEkcl3TpGQ9FEcOnXKnD80d3zca7cM81oUGysfBU3gm/qb2iCuB933kIDRHrk3IFu2cxMRXzoCU43uuhf9Hmo7N60zH5LZjjrDno5k+rSW/39CwmHfEHGeA9hfOa2PbzkXAuJ3xrCCLNDW3fg9vHjpZI4JF8Zfzbi/oDcTP7KHdn3Cra08Zx+5RwutE1wbI18aUCvLw0uJF5zKHk+hZJW/nZNYfGb8YkSm0ZJTzsqPJY4TLvyGllyWjcCC3CeQVVDq3xp0KcejkTnadyqVlpAu8TlfaNBLFNUc0ot7LBWz2oqs9SztMx7Mzo1dVMD4tZ8aJvI9s1V1EQkiwIByXB106DCt6dJtFtTyXyK2qjXU8PbKpia0XqQy8OE8Ldyy/JtE8cT/pv+xEploiJhnq/dE0ZhoiuRECZeTMBGXPlSbXtUu6Tcp13c1rpUU66JUSs0Gxzui61ipTbMtdu4Ya2a3+R0NPHVfAep4Us68daX07SFRBTnkPVVV/QVgXiie0IjV24SJC4mwB2b8XBGLNA8cvDEsD6xbL1hc54dXV/ACX3DHRyO1ce6l8oZofcqmTD+WfLcnp6nQuMrC2NpHUG79XV0kWr3KM1T/9vKQLbErp9eejj1abzz88mo9YfIq3hr6rooHdomom+Y/kikTsMs9vzWPdG+m78P60tp1UMaG1bgvPM1Ta3KJYGAconCTvGqKFrj96OokyehquaW2FlNxcUCDCyr+AtlqY3ZpPMa+xMWGGJMln9skzpPQ+htE1Q96cVRk0lGbTLoDxEGDpBP7aTTd5wkHwixe9Ghdc1tTfrDr3/0HhubnhquNyTXqbgj+EdBZIoZjLEyvTHabig5laI+ZOzJf7fmaO956vcb6Oykfdy9oMfVLrFJbZ5quaNBU8r7Sk/OPr26Q54bDrJrCuxifVldt9JeMbdU7PN+XKlS8V/CU3Pv4wfi02o4h25xbCXRGWq4Uv1O4q/ExWqYkVyxyOmeHzzYPaqShQIymTIkk4VUo/GDQff8RU6Q543PG3n1FPPrsYpn4g/8v218dWHBOPz+4/jMFf+bNT4iOzOJ22pYYIwOGl+6farrRW9ApVw/uOzwwI/jvv//b+mhQ0D4Wp+7ePVnmsLlC/DzrYEPJfftFt/bokVAi7QWPr3kK82St5TzMzZm2DrAFHwq99KyxN+BdaS7ryZgUW3Rb/IiJ/sdq/WXbkWZqY4vKy/u/hOnCvKlTrnop9fqcw0bUitepF3H/peTQhUFHHO++Ns8q/UzFxV+xilDm7wITtQRDXcu5TOqtrCUdj47YFDLK2okGr61IKrwzraxfTnc0JDVNjdYwu2wesMCtX2atWSGN62Gdv1RZi4pFM2HvD6xNWpTB6kz8O3ZtN/mkzA9jdunqUplnmzHUc4CaMSxrLmx8totw/Gf48E/nIXWzxmu6Y6yoWCwdN50Z01E6pIKQ2qVIOSSyGQCvVmlFjpJgYfz9Lus8/x+gD6HPM5+3cc6x+PcWYVyr1RcoVJJQj6ZlMx84NE5/pmtBxbO3ee0DAWD5qFep4vvzt+IFn7SEp+MLyDm/+ey5+XWy1wyQaVGA4BdJp9eoGEdvS7LoE/LbbF4qoVSZUCsDo3QhNR6oyWsNGcL/fvadYGK4i7KQk9N6eJet6tFZJPw/QoZvxySCFIRQnKFBXpc648SzM9w2p9lZFn6CobBhKuYb3fOCZTyO5zeNoFBVccz21hN2LR9pIpppO+o9Qi4eymWhKrExa8tlXuOnV1OhMVuCd/h4EsZczCswHu3M3Lf/zbHrU4vbN3domsB5WVdD4vMDX5ZTy4q9rC5DnXHSCBRwRb7Bpy2oWDQOjTg9NAW/tUyU1Y3L36rjNPqsLazDAaFTyIMqtWikFeikHulHFGp+GMM7sm4jbxhY5AjMgWl/BaPOa6XDBVaaNmW8sJSVXohNKTH09XDTAWdamN8DYNz+Cgg9R1ewLDJSIhzVUX+kDjpM+d6W4oBS24h7NmV1PvXH5EfCZPxyb/f/c1tBSF4+894cKYn+sSDMs4eusRGHd/8oHUkQZ9BNpbLeFGPMaGxSbUUVGEiGxLFpWqLknJfbio0gTs93o23WIXzz3U6hoJBAV3FX14V+yIyj1QYQjGU80hkMi9DKPC7LUxlWWTv5Fjl//zZr5Lru2uJuX9EZodY4gPbMxgMlA45OaQ1nOM9W1o2KaTTRMKgSiUIHOBKkQQBcGtO7TOJ4BN39rsGYv5/dZY8tqvXaR4KBsuGepxOvrNgNVr4yer4dVQuc0kEQbX6mCJSgaLif0SBOz2x56U9fjubm3V5aWHvkbMZ5CR7iMqCxzhrl6TIYfzUSZNkX43+P7NQ9uL2/K0ebvEv35OLFLZqnobrzvnCYzCz3v8pJzev91gmYeSl0UN5FDONrbxHlyidNXzYg5O7GDu0o5/lS7U2jZpbHlTdtry3ceLHKdzVSr3Vb34cfeDUdsUMjpJ6gdwlIz937VaOPGAXt+pLVC0NxYe3RFZGYPVz8ec+ezUWiMETo6tUFUUs9rjAYQ4aqPeZZRRTPD3eQz6y1s+Chz8QeretErz+7NSrBLhwmBCHRauia5Sla1U7hlclDhJcz/rbVnphz2vf//I9ZcnIN8nfUHI+TDe5n33nnX91ruGzQ7DtctdD+DI5OHfXYs/XthcGrsVWDQ19Rai/DMrajC5CZsOianxMndsAT63gb6SVq6Rs11WhQm0tvWKLGCKey7QrSsTKXFYkHWAXOniM2+fhwEqJQyBwSqQCt0MokThFQrdEInC6BEVOegtPUEGnWwS8FpDiQv11Jdt7ewW0PxSayQHmYNQTXLVgAQc87H9BwddynW+1mxI50a5+4Tt5IpCACKPii7tIIMtMYqy7wqTO+OF8pQpnr2wV642NclWtnvoPy6Jx12/dW1KfgL9w3m6bLFilXpahobIPl/D5R5u4Wc7Nq6mBr24FRLFniyf/XT3TSSgqZ6xhBCR289TpJdCqXn453zjW/ljSULuragJgOnpLvUbrrw6uUGhhT+cJAp/zc4j32nTlAsFQTGtl/LDulft7yeaYwRC3OSw9M8xAVtdzzBZOg5ZT2KKewTOHX+nST///p9JGeqgvr3PVVy6K0NBaaoiX+kwD02yOdv47LKuYyzYf4woflfFFbOuX0Mecc7otdijdTpoNDNQyVVvWqKNjJbkZ1UWFo0yNoaZNVVLSpjLUaJgvFAYYi44xnTx9WeNUjaWd+wadzszex+VuyWbS6Js5Jgb/PJl8QcBgCC6Qyef5MKn/6Dha2fm1i8rVtxj17UZXWV+PxaGsY1vM3Gp5wcskJzc8XrnPUcv/VMTl097mc/oJQnbaABzFFdll/EqNlldll0okNim3SqvhVdplIg/Dp1SWMxjdSmUjLECyK+gsS1Sva+Lis8GS6mxrW/mKPGtKdlbWqvK6To9UrDhXRPl0KNNq1m20wW4cZWcAK8ZnUYoKiFcL03874u6o4y6xn8Ba2irOWh8kq1+Vs3mnAPu83+7fw7y3PnvjRUm2r/OtTVPsox9YYWNqwf9KPTf9RJq/gPRvYdaxp/mkne85du/OmH/p8VkGLX2MYaxywmhKmSPiNrEbzAoxw0FPOZ6WQ39e+8q9KzzVSTFPtD2YezufdJpU8FNu/k9QjVspPDVm/3rHKi4cxHNPyqmUnqDoQj5Z7DSqWfPSqQWp3+HT+yhU+cnSvHQSEZ+X/xeRlE7aTjyalXWMmDuSnXUUXknxETnIHkOzkR2OMs4MpOYNep1A/HS8/bNxmIFnajnMBvrrTwrqDkfYYzn4DXeVxzPzKeSCdW1MWnHZI5B3e/Arkpcand3O0uSV+GVdjL/7rPs6xjrnM58WrKO46Y97KLR1f348mJfSg3bje+6SWobCEpGraorlsppKs3VKQ++Gj1wbALGVn4G6Hsc+mubmh2XvV9zP/Fxeyec83ud+Htf/GWydk9Kf3OngmHs1xF5NS9xhsSlf6sI5n1r1adN6tUG0Iwu9c8bDp4lf21tlq/pnr7x5g+9UWasga2nB2+b2gjEznJya/yu/FGH4oL7eyehsO91sf7m9OfZXrNq2gDsAzOODvkW/rls7PKnm6R3Oqe/09wtgU/AeVzoXmJ8h6DuHc9A+CIqg2aA0XxKXSy5lGqG5sqahjZhl35epFCLNBrWPhjLUPj3SLFRk7gfhOfdIn1hDd0++zQ/MDUHw5BASfL3u7qb9QbCcXN03ZAjW/ER5fwOzsGKa4utIlJqVXrWy4kp6PgX0336/rnqFRH6i9lmWI7ym2PohuuWzm7Nfx5/6IK74Vr555/rh4fE8ZCCIEEjI7BACnOPij5UtO+rWqFtblSsrZ1We2LDkLXtvaFFRY5W832nnDTmam7Ratvs7emY067PbSouNKRBbJdwKrYzZUhasU2jo6ZfZQwWvdShVxvEcWjHXmduo8pVNnaur6dyjG+gu3dTu4E31+KbznDIb4dsqjnVfFc2VRpOwrhdZbUw9oVBtK+D/wa2Xic1QFm69t/fM2m+FznyVOtQkKZH4GWvO+hWSLiF9QxWZtKxmwaU1Gz96atMGnGumyR4zBWtnVtHKyv8tMReLFnnZaomXdZrXsKJpviBuqgoYWmjw2NDP0lZr5E0mS3FLTG2vmeh+/snn1TqwLjpZU0DJuyUc5i5ZevRfiVISaJBYuJas2DSdBVn1XYFokJWVXnysqbA81+0XMGSWSkYihRciuQWvKQLKsEioXMbO0ud0zmI7iLZyvVhg9wuLcY42joSYX/1Gc6HHxt8vVUkCDUWwCusb1kaj2mGfTwD6sNbnRaBNxW3Fxc+bWjW6iEmPh7u12MSykN7leN/ZQeQ+m8rm4rZx8+4v4fg+t+WqvcZOcXm5uNNoEneU+ztFRuMEDD1kMo7gge8AKGqOG0s6ysqkTMJYJqtk3WKHZFdwp+i21Csq8kgkNIlXLJX5xPKx9omCRZx2v3jGkTs9zJUMxqt0V358+LEiq5mQLsnW8gH3VJFTIHCIiwROh0ByIg+JxYBxBLE1r7guP79Om5fndBXo5yqwntkT3QPOC89En2mlPR19Gnj+O5abO8ffHds5tTna0nogOg1Ig4qQTFahVAqQpOhIziiqnOU7HY1Rp9M9Fm10OMjZ9G2By00me1wF+S4PZdyuvXPejYcvODZaNsd98FntSm8ultboi9aEzrYy9vB3f/1i2RWFd9ReYiPNJc5xfn7uyGnLFFtxLKZ12NqK4p7i+Eo2d/FfPDrRvXlLjp1GSyWd78yzZtW+rS/OYHinBPjOeEu+gvrnfud/JErfmyrzjVrqG3U1L9fc5mZ/b6jdhFRl/evDDfeEv3b9KjkTfhQGxeOGSw0w7I80/h1parYYzI2R06D4Mnwv/O+57E8o2dnUj4V8nJ4kfJIVu0FZ6BP0yc3MonwCCm/40/AnEw2fNkAfRubt/MDG8J2X+LACNmJmIH/3OQAKSviX8M/Upl+a2E+vTKyE9kuZ4wcmvxBfTc2WULz2Uo8xa9PTlz9PO5+aZSB6UNHLEkAHLoonowY6UHo/7YzhWZy5MVW5NQ2Cm1+PymQLn6zUZK2VJoumR/unj929ysp96nqo+ztY/OF4/LNxpltil/Oqi4t5tQ65RH7daos1/BqHQuTNvYGy2ZgbpNx/ULY68u1miV3Br9ZuBBwVe9YazQzS35jvTSGy+N7LflVuBn8ON45lkX0Rc8VT82Eskt3gbIbFzaH+vtqdc2iFmwZ/NlIodyjUn6YdaZSfqPeU8m3uxZzcC7m5J4g5F0HSSTxwg1GUmm4y2XBTDC7FdasyamqGxPiYZh67C+WLfRQfbH0Qyy/TETLoL2VccM0wihwFdHYhf8hKgNbH7BxqQR67st+TzhC8f8ErbzjaBzvvj6FY2gAL71vnxTxvhdbVZir8OYKol3aHvNHId2gX+SK1yfuKSLyQ+3WxPylvu7Bz8Olojl/rMBTlLhhL+F+M4jIerPIjZn7EFiSs0IHDea8L0BMhALD+eF42/fnQ8Tx++HC/32n/S8Ks/s0YfO0/rzEZTX/cfzx/Xn24x9fU/n4RQ2r6Y+fj+fO3wz3+vfb3nzC9IMXfNmgY5vH/sP34f1p3/MfWH/93SwN/WwWkAIG1nCKwPS+bHr8AwM/GaBFv+xCAwkM/CfCR8yNM3exgDKvc2Ed63/S+2nT9f8dza2/mNmOrvXsG4zrcjfO9b3pfrb1+Ig5dSoob7dO0v9n+avtr21xvT0cjEtc19oh374h3xB0RK1iHz6s3zXYW877pvkqZ6xhm5io3TmHoKgIcUvkB8aKvzoMAiaUImPLB8qxWGD6vOangyvZqQJ3ZsayiYS2gSMo65H5lDU+wlrvzdTrWcy9P8QBP8yDP8DDPcv++fQOE+yv3J9oX+CiTki482+8BCIblAvjqumub9dm057q+pnWrR9RXIqWNQEyrEYC8a5vRfzHZZATmRyfwsRkEqJ2ys5quiVagurzBwjFQ1FEi2Hf9DdA+qjfsWQBQ34diL/gihoUzcdHXlXqxYq4y15kbzJ0n8i4o2+fnS13Iz/epu6/Qx3ul/wHQ2/vDHD5vGADMBwUA/XS9LNzzljSocw+NNIO87drSeUsbQA+LfNw9LzjIJ7gB8h4DRjaCfCxy3kb9Bkpz8yN8wj1vSYM6oJb6Vmedj7vnAYQqhwfo274ydZvUJZPvV4aon3trWElV/ZKVnesEbcf/Ip+AZTbTigNlAFGXnQLgEpEnLyHkwKiNVwA5Zu8qACcX5kmI3p8O3ADdC71e4TLK/VC4zKrjMtiNc2nFgTKAqJuQ3A7UzAEtU9qFXJ5YAjB7ob+ybX5cGPbbmUwAeofKAnr+LaelNoE5R5a4C/M2UZoimHfpyRDOKRLc0up5izL1Uc4J7IQjmvM0iWWGTihKTTRzlnA96N2VZZ8LCwei7IxgpYE+myNcSaAF6M/xtu7UeO5gonILOq/OscnDNt2+9hRHbm1V/zqW52ojNi9vtlNJ18rQuJGaVFBmy/9gFkG+y965gwj8wt7TKHMqXxHgH2+qYpZk10qCDdOctpUh5G7vpbFqPvBy2zEiHwIAOfPlWO/hjpZM0++pGMxVAPDt2WWtAAC/fr90Oen8979xfOsBgIUCAEDA7y0BQED+E1IHS5v6fdwoWqaC5ytdFyTPa9pmlHzB3tR25orp1IbD8n8x+rM0P3IzbMt3zxLK+R5SHWpWq7vgxDNAHkdBJlIzpI1RiY+92X2UY8aeSfXM8578NVkz+7Z5Hv7t9BzT1so9JPJFeK2HPDtO5BFwPIRLD8LryWqSAUxfxR0SpwcMTanpi3zVserWhcE9oaQ8+T06bn/zrlc47Sk/eXGCbeZwS7OJ5Llwfhrf7JdJMowyEW7uKUFajAOMUuY4JI+QScr8xZSVTbIJJpReM9vQst+tZLrMtCFOC2keUjccqslCnG600eGPhGBoTGOjGT5autFSQJYwUWrps4IknZSpw46TJlFF8WPbWMxlphlxZdGuAmqbh5h8oAFMrkNpVHiwIJlIzE2+c57UfKl+pDBulqLNCPpIZKOyXHcteCJD1tAsyKBkxcgc3ik9BC3EbFLUkp/nhBSrn3DOEDqpu0dAXGz8Ji03RpJmKTm/5mZcH+CudwnmV8o5Tz5cspWNk7+hDlGPK2zucKVQl0eZqt02tDQ8JkgydsqgYE+Np1oxBLBYVSfpf3m2vp0NdbxCy0UAoIL539wNNLGeBrqjl/OQCtlQvKqb/wUvAwhYYaWw9cq9BAHwrzYpIlIh2pCkvh/eQhjIhgOAw0DejSA6fDcqw9m7MXQ+vzsJJ4S7kxVGfhcWK96HIQCEdN+NAC1zvz5JRl5k06vPoH5d4hIGMCjJKeiLVg90aGUzUTGda/aG9OsVOtUJ7S6FxSzSxFj0m2mNQMIu2ldPNpCRiesy2ky/jVT70plO5sGvoqiZvEW7aaw9br3fZ+irxwpx+O7+cbN0i9qughT//hpGAUGZ7WBkaT1K4lId4Ahmal1g2kVTPRh+BoWmrkXwTrdBfTAWwRFYL6oHUu3odoo69QZg/lSYl1JqD/x/ngx8jfUAAA==) format("woff2")}
@font-face{font-family:"Readex Pro";font-style:normal;font-weight:700;font-display:swap;src:url(data:font/woff2;base64,d09GMgABAAAAAC8EABAAAAAAZgwAAC6kAAE0ewAAAAAAAAAAAAAAAAAAAAAAAAAAGoEAG7JWHIYsBmA/U1RBVEAAg2wRCAr5SN8hATYCJAOHaAuDfAAEIAWEFgcgDAcb1VWjoqz2ppjBcR42Dh6G22YUJZRzqOw/HHBDBvSJr0SENNWA0/FS21vVOrY1VBsiq4rXRpewDA8/JyHOzI9XxI9jP/GS6iy1IzQ5RSsP9fvxO3vf+ypAE5Fk6lEt6nSiVkswnelUEt5JYvsDP7feH2OwDdjYRmyDZcCCkaMWRWzkkHJEhIpK23kqBnaAlacYfWHcWad3Z51eev7vN9cnFeDkziDv0GLeNZOXm7Qza0X0udDf6S/mvuCF5Yn/Qz7vzPvNth7voC2JLabQamoFaUZNQx6iynNpa1RWtFTU2tK2TE/LTNCKMiVDJZoG0SAWxBaxHMO+LJLn2JP8EbNbsPQbKWn1CwV2khK+AQWoZA6bq9Y+pCLaJu6n7NSB2Wz7fSh2Q7RlTcmW7f0EZCbgxP+zabYz3ux78vGGUMrLIfWAVbjlppr9u97R7EQn2Tra1YGkQ+lAYLNyMLfy4wDbCZcAIJ0uL7IDSBWWANDnpelTNenapOc2RdekqMIDufxledAVg5ArkVF4rMqGGkpV+2k6tL6aUoXDKITu9vQJder8r2nT/x6l7zx6UagVLhO1kuJMZqmbT3chFF2rcDlUJOfcaRCKQaIM47Eh5jzy7MterLgiiwyxO99eK/c4Q1NCMA/jBaFpRghhRDDCu67P7RqbC+Y6sAmjAAPeuL0pBNAOzAQKDIQRwswOkSYLIkcHRKcuKO99gvDhLhBLCC0DFOEGAR2MQQmGeyYqIeV6het8D2lfacaFjx+0kojmtmRZciZQvmwuqwHKd0Wt9UCBBsymjNNHm+vBE6jBi4IZ9GthT268mmff7IC4xO68P/lvnonRnw+ZC7OujzKWHyoKd6GeKFodpbp0lYUd7ZXe+NjHo74b6Uj6+dzr+MNhQesSKKw9qVVONaXaePadS1fAf+i/X3iiOReii9Q6v66uG+ullzmNOEzQ1Ynryqbe63U3AnRtaU6HEgjhAbTAieXFe8colB0jeP7FC13w/OdsUkRycnRqEYJEScCmQyhmkkoiJ1TLVSFMVajTqJ1e57+0GbZZkh32SrHfARlGjMpywilO51yQ65oxBTzsnXJg0uEZR9mx1fOLa/wdyv6B4yNujqM4R+QCETf+YzwfSJ7Ew6WDJxRsHFw8fAJCktFuDm/CUcceu2vTEY417vzLtHQsbevkENpwJm/m6PbMjvXWyE3zil+3w9mBYtfIblR0gLZ3XuY9MrJDGOF6esTiNZ4DE83+aZBk5M7YDuTPLbeTh8bg4vWlhhIZSxO5Ng7GZrgheclUFuJYeiHmBdmFTv0NEtX80WkMiAOzcAZTXxPytbU3YjEyPHDYoGxOJP6kzKRffdiox9Nsnh6EtDCg7EXJFILVuCWJTwojMe+5BwuWaXUcBzuh7QpjaggGCfPVrubdUkJS1XFnElxdPs0H5Tw26ngYzCE+p5NZxzgmW81pIirySWoOwzYrfELETuMAHV9kxCk5LEQzirlBc4fhsUefYhq9Rr3vZ7ab5pOqKw7gNC+HzKcSFEVRFJXaT6JGGIoEGZkbNHcYHhUuAX6eotoYbMkcwsXDJyAkqaJnxNCKFSdeAj0DYzHtlRnZAlY2SVIUKDSeS5FiJco/qpxVtVjjQqcdGVxwa0LBxsHFwycgJAnl09QDYVX4ZkVU0cBsc8w1z3wLLLbE0nDZKszACiutsjrcRqsA2Ge/Aw465LBjH51crnGZ5oVBbkdMe1bG02lXieDSwhNKoQ+wJXOAi4dPQEhSRQ/F0IoVJ14CPQMjEzMLK5ukdspKsjEUaC6E8VyKFCvJpVFVhqD8pASSBq7Do0yOAoQQQggf4/hvLdEM+kOavr3ZZLIHc6PqvAf6Nn2aeD07KpmeLNEDMUwrVpx4CfQMjEzMLKxskiYHG4AILkWKlSgf7QlJDcUNmjsMjz36BNSESLOu4Ml3YBb1IDORQ9NY46wmLVq1/WeEFzQQSBCIYG58gD5gAFDa0YAG7as6DpHjAEhCGY+trTxaDHIdGBzKBdgm3wGDltYI8JMireV3OTqG/U347D0neacV8ODurtFZON1YRVZ/Wd4Pd3fGptKG7amzw/kZBwGYoHhiaWqq4mbHvlV2oKbJmTIsCMazanNsF2Un7amf2lmwy9EGixneQOq7wtne7LSn7WCnsSu4Ce3ZEM5Yk/Ky97rxVDBNz1xlDqk5FJ/xj9NLVZjDMSLA0e5ElxrTx2QbnM5XHJXjlZdces/5zmcHwZw97+DKp+F/NGS2ElDUgUVzKWGJVXkmR07LyIuhjLsVQ5oOShu1/mYnLrRQT+iwB+eSQxgkkoCS2YSt0SuNfV/0ThmATQ6sOnoUtLlMUsnwowXfzU2Dtxr6F4ue2lcZaJivkpOmEyNbmF14yTeKtuXbjiBOBrHrZn7bM6ENzlNQKnFEncMm3kuSmzxTH1xaRwMG7xKOLd31YbWHAAFLYMTgVrZzELu2rQU0+Fjn4wdCvZbq09NZuGUrv/l/4djC4b61QtPf6rweyw5LoCZJwoI3orc+L+KbHpXJefkbi2j6Jem2Uj1ajkcaBsRWyQrDLB02ibTc2HH1XW48Phc4H14f9UWwQhBDq1ZIYzaHKdFyXQE3h1oRCNsz3YVG3Tc4bijSGE5902NbUJyvHWePEe3RVLTA9AQKGliwRSIoETiTjVE/vinOr2WofEXGZVMkjmM5n+Doi1+0ZUkm01mPCr32dRVAuEj+sZrNbmCzAotPf6r145dkrbuoAJ/LqDfvm8vm75HG7bCnT2O6dXEC+f+DoUVMBIB2f3xZ4HRS/n6ivdkITMqKAWmcWnsw9pgnR/IHVhmzjn4pQONGpRs3qm/9Ag+BBdpRYNEFI2FL4EfHTiNNNr0cXayGbVbvhFManXVWi/MuaIWihfDgxpMnNCwsPi/eED5I0MjIBCgoAtDR4QUJwhKslU8IISLGJrm/jQgpyWTEkduBQqi4U1MojHQaWyRcBB+R9BdFPJ2NomdAZWQwk40wS4KRTK4U0qTSk93GSpMFK5tecsg07owgV358t0AZlHJQrIIUlfRWRZRq20+NBh4aKdXEIM22TIs2RO301UEvneSaQC8TSTCJWF1KcBgcMISXgDwXLiRQwnwGGoFvUXDw3HgRUJkbP1JUUr87RV3DDSi4AQUsCMCADl8EwWs+SbQEiHjmSRA/gW8keg/FP4xT7554nJVAlN7JUJZ6OtkOgQdwwMMH7mCBDDa8lfIj/gxvmMi0WYMdQ0BGdQ5K8w1UoaWePn0zSBAKaKDPsFwu1RpN1G3YDpre56pbP/LEC38EBQiyqbr16NWn36DpZ5Ttd2AXTu5+a8xDTzyFeDqA0jdyEg5i/xBKz8jgqH4IsLrnjqEvCAMSpo3j4c3+iJjCU8/zu6czjKmabBArVnQwkYyHA0tw8wXOjGNg5vE5mer50udJ1Y06KJiY/0JQeNDAdHFQ36AcB/f+zs46D1nEzWM5CsZ5oNXNcyBAAVEU87rVo7T+QmXs4+aiYgZS1Z3MY+EuI0vcq8TMhY5X6YPFbyfmDra+l2w4GHyNDS5/nZ70dBvIwF390A2+NjDvo+/j3eMx8R7xnvFYwf3d6/DhukawfVbfUAeOf/ztC8j+rqqiCFzfNZTUQvmOWjSjE1PQ/3DmD211zTBfUAEEr9X0VJ9aiQkIPICCGzBAw/0lji8e21v9QrOdcSMYeOYDzhFG8mNmC6gn9wKFJFAym6Sr9CSzn46DMHIMdwOnduijMiaPUrRDFJR+kQ7JfokSIA2GqbbsRyb3h8iu7gqEBK/CR9CiWUuBMQCP4u5jjQiObM/P6v0NpEBxqumJEUgGOdyERB0g6DpFrMOaJYLy57PPsBCocAZlkdW8BgAenrn7J9TMIBwiE7j5yScmzzidUGxSV+y6dB/uTTJ0aS+j3EG50xxgdbro2EeVeOv4N0EFLAD/f85twjqsRyS3V2skUL+o1GZhpa+jwFBuEFMKCsCORhZesTTHgSAAF76sbEWGqBQxE5TwB6QQRH8718CrVhCCrKDjQWggYqh+mqGiTPG1jcKisYJZHJaAQ/oagKEUoq17QGYFsoIwtp4VH37/lv54MvdJ/6MrgPAHpjsG4rz199QT231rnwdeGnPVqOP2+t5mhw3bb4utnnrsiZ2uQWDhePFBRuHHH12QYAxMbCISUjJyIdTCaISLdMoBpz034oNoOnpGZslSpLLLlmOcXHkKlCpXoVK1Go2aNGvR7oQ7TvrZJjvc89B937nrhvdumuyiZ4645Q+3/WSNtT564brdPvnGFJesN2SDXdzn0X9sNAxPeCQERL5oAgSi8sbCx8ElxPMjAZVQCkoRxKrEiaGVIFa8RAZJLKxssqRJl8EkX5FC45VweaRYg1p16rUq0+a8C85AIBkQAP4B4jeIJoCut2DAU4D6Nqi6ASgJUQi3Rq0Hiqqqv4gMXUMAqKCJEpRLJcWl16YjGikCbCIre02N4kh2UtXvxRf9TUY0YXqAQpe2cxXkjKhtRLZMG6GNe9jEO8qntGEDo4xPgUatYLjJbnrGiCHTmnsvrSPeUTRH7wXlPozhcCkqwfIoD7B0dopdSmSyxc9uo5DRFPXGB8FrPTScC/AP4WDe1VFCYhNDI4gs6o5B9BTZ0KLgYLSXBRT44BWnY4hENFhAJZHlH6V6zRkRQAxAW0IUf5WoEFkjiUe8hJu83ESATrS58dFJaExAYrQXNkbxWiJoxa7cWExbRAxHQ8PAQIcDh7PbPQ3mfP1VAp0iFlEYFF9i1oLg4Lk8XlnUPTq7LCUK7dUCuMYPx/l7xphwEDHQ66a+rglW6Ba/y6O0ITWQw7SypK4q8tByqaIj3CmkiiwviASp2z2higRzSjZYVS/aJ+D9yMFMbjmZAC+gnmCIMVrck3bqmc9zGxj9qGdgkC1ygndhZsBtH4F29jerlU+fj2EL9MVEE/CebF/aYf4L9eC5A8aO6VQlSVKjpZAwqeSxEN0ZLBrdaKqTmEqa7qb0BKNQoVx5YEF8vkDemFMws4UNE8Qx6OZUpGydDS6YdNMgln+OSZEFvzDH1UyZAW9GLOby6cbCqGeQZ5xMO7ePyCo142IdPqA08OJyH9Si2lpSMFopr9iX7Pl3C3kF2Me3v2M2HVXGSh9jZOR0nicZU+J1AOLrCcoF/W2mzEiNOeGadGXGAbVbLmR4Pm/bTj1C29CQY4lPTQ4Qv6PsfFULkT86mLKIdmKAXRqjQQQWCSRTM5jyFxut4jb/U493Rc0FV2lcWRnB1pr9cTpkwwdXGNXakqurPirVVanXRiSvurDqw118x7QUp6plgisjMAudutBBNSes1E+xdGkCmoUKDSL5ViVehmfOjP1xMV/RKOmTUXJXuRUAPvpZDSU3yzeCdzIehR13HxLCaihdeVT57B6ind5iid1QbJ15fCA3hHJdFlpmJdMLNvZJW9rcpUxmBdPFcrD1uV5A4oFbfw0UmzXl3EOUb1AZAlx5g5eNh4I0IV1kOx6FE5D0RW1MRpx3w1uYSCmJ1n0yFprHugmiDu8ePJWLaxZpXq0m5DOJ/HKES7sfH+2VrR4WQBCs2ScdjvAih11IXWXM+NN0z74qW1mq9VOaUnIXFaDKm9HRzojzTkUfm09LPQBWb8H56lft5GFmTzKWbFQtJbjC+NOxTX4wrtRzA++FODuTUHhf1Cxnzoe+v/039AtJIbW0Fwj1nhuTy8H4MngPszGOgBV/LksrOGdIWABrdvkxhCTU4Qyx1ecLRR5mk2tYAR3lLxKIafVu7CVUnlgozQH0B9PFa+A2XyiZrq+wxoGcbWSK2caT1cS4beNFTUVRhRe38JtKS3KLi6nnzatxcQgfbSuKfs+O8LbxGDOsggIi3lZYXxhER1rhs7LbOB6VjXYP0GB5cJFuDtvLUdDoBWaUfVU2cz72cu4XZVKAaz9hAEAkWE0bc/RQxd2n+dHzOrx7M8ecJ+s7sm1KCA0QXYE68tr1ooDRID2YvAwS0jjQLKIMHGmxKkzjKgi01c2DLHgTo6fys3Xpha9rzIyISG7VFURD2ogVDMaRdLAaSityIcHyadCICdkO5qMEgrG2opuIFv156YFXayuvc6ESoFzUOVuFzu2NaiC57pVUqp7hN4tbrwweG6hWdB5VofUmKod9V07qEezwWqGRw0JXSdzjT5vbrb7TDDmqTronwcY7eqdoUV1c81TzoL0wP/wq5KFCVcyu1lWV81uXog9d+2gd7bx+OfagX+TU7CRxbKO6MwF2/UyFMdywHzm541yjax2liEpUoMyTo/nEc62TE0kpDtuph4lih4tu2rtA9OuHn0cB0DhelY01eEkoyG+FnnVGMASQ24vdulVZulxJAwIRC1rKdzF6grUM8o8Z8dFIlXzTSY7f4kfLWwCwCHjwUxhDzdI+nvdnOdsneGAIi0KYfiMt5qT2zrXY6lL48JxLRddwkmh6PvLgYtFcYhM7iKuwjqziZI+0VIRXYInsYZYH2Rc2J5CKZu473h1/hQVHW7LEAXhHvZ1o1rqcUsD5aPFORrvXaycdJqoSTNI9nBHiUgyfxpsmbjrT+mHRrQTrcTSPaLBFs3BgryzTH/O03OrrFjyLk3EBrS2NqwDA4EKVn4J1XaZwIUOFxGQB3C6RU+TChupHeJdKg8h/Y22z/Bv+cP8Ff0qqkrsVQjCI7xRsib5uFUUUXzpZUMjide9ewpsHVHrmFxkCw4AKKjZw9tIv5zS8wPPj0QsohifV8wrbAWO6MnZRLqKNY/rsAgAGpsd7jf4qQZjFH4AUQq1+DFH9dOPYpwX2nZE7sFVp9YmmutT3aW8LkgWVyGNR8sloIZFk6eBU7lh3GNmB5FzHqY5q1BEdYV+Oo/TGHHaCs8TnoJxgULRqQ/+6cvh8DVf6x/B8XLEYMGHBzrt14yDxVkzhvjotqojh2gVjjxX5zs4RvM3+ZMgwuHDXcxjPRZJgHVwuAvONTrop1cKsyKQlTQxP2s/uEE3XTZBHQ2Y3bQukoA3EVwzmjMSPmiFzYuDIn/VYgo9w2rPAv4Cg7jy1pd0e4vU3hiPT2x7CFsi9Q+mFVbM0Zgq5VECAKkkhkdEWm3xmLIxQuzIWMNR561lGxgylB11Lm6DVR3/wQzOYPtzbSJtmTTTz/nF6yqyieNIrJ2lJxriQKBY2ekMjB0nDfHYrBnnd2U5v5c7Y2H/AfUpv+NTuTnAdXbrQQIrmgXqMvsiqWxn1ghO8DETtPKISnrvYRgM7ipohZsDLYjx8cX2hcTMtqxiBf0DCODiaSt3k7pVmtjO1yzW4mTLjk8hC/PktY9xFPek4eEedRNGI5jR1snrvliKNpEo3cafSNPxE3UE4+ZFiWjPkKGqaDFgFPEWxB22F04EiaSTmw/U0+kKhQSYdmS6mSSdawVT7tLf/Qmwd05XzhlNkT8qCPMjWFIiqSxRUcdz5j2G+Apl58IQB0Rl7pfnHCWI8T0j8eE9+KwFfC/DNoylDn0sOLVbMcTzPaBxNleoZLspTCq3KYRRWZOsfRaKp9xacIeaQwBcfxHTFl7282hA7ZLkRE+o8n4GghhgJ3XA9u4msHMP/NwIoIwtIIzv6i0sJHx8bTuU8/hoo+lzcAU1PgqYHPF+O+M0xz6BNpy0wz3k9B583sDtgWSsbnKPh1mKROjkiJtregL5iUPEtIRqeXReWS41YM3e55CU/oGFt8KKeyTRFiB9rv6wdFmPt/WEuV1i/PTW8r6RoUGNXjaemq25Xtj9N5oeKTHRNsDU0JMhWmkwPZXYzyel9E9OlpYHgHBWmTFXl5Su7U1KVU/Pyp6hSJ7U55ogT6c8CLXJ5oOVZIl08fy5w2Z2GTiKbMb9z9NXCxOXJC4eCZ9fMdrwqt4/m4ufVzqsJXLZ4GazCZg5qiorUfampEX2lRTM1GVHlwZnqPZV1ynRBmNTCqAxOlsuZSdOTmDKmrruWRks7Oc1K80PhDIrGnLQOGeBGt48W3guXE1ZeXgm2+e2r2+cvWz+F4I4V6IiNY78WlUmIweRAUwQ1vmfJoiW16WpO2sMMJty9Kp0/ruDbjhHe9ABUVnOx80jRLH7ksteKFV9W1wDu5uLR4Tv5ngtxJu4piWFUxMfrPOeW3iE9GQ0f3CqwLlSVcfPw6KrJCKbWwx5JZLyAJVh7v8bl0vTbUzngKlIirj6N5kR9hHKkrBPrg/l0q1TGXsFwi8WGYME3mixakZuphpmsT8k3DKHmkzE8POdoqK4iJqZcp4+pqYjV9b9Guhv8eVmB1Ayuf0P5KhoGSHJFZGCibz0qoX4i1kNZPb5qstOj3IpN/x/qWENNVFxpoi6uokZrWPnpp73aXYHnszdOnEUrN9Po0y4wuyAeWznXotJVtCp0JXINfedMMuHlAsYM/apMwSDdJE+wjO/QmMq7EixV5S9ThdLg49Vkosh3tKU6h/sHxxRiMZZN0sBb/tiy1GV3+TDF3TloSumy79mxWUBfz+Xvkwo2D++xJ3cNmCA4YGTfgOsE4dKRKmbvp6iX3a5dgSPw4NbIrqqGeXhdJ8FVNmHfjErKjHLKnte9Ij1JHhTXXllRv/3WSO/wAvbyefDxfqR/743bYbTBc7jJ0x3XZB/001LOiC+Ad4GLNu/MPXU26pTiuM9KH0M5aJvb3kXplq4mNjW/Hz22FIpN4gsi4dU94/PfTYqw6ouEmrT4Mh5W5RCGmBTiH7fkUGKGPEsX+30u3OBD+LSdRHti30g3J24wBMP3WHW6MNSkEP92eRw55sJKv4Ali+nC+qNSiTDRylNxW14aq38xciwEnrPbYJroiBWUm2yFokhrozG+E5LB7vfKvplAeLmTRH9i36jOsOtCHIFFSBb5SpGnn7DWNb6gcGJkkiKZUh2UKGuDASwvgeyQmqWenUt/Wp+Cy6FzbrON1ebYLodDO6nKVDvI0z2SSMfSebz0R1LJo3QIxaZMNBu7Uh3GronmFHO7ip5ddSrvMVWw8ItQ4LWIRztufZ9dRZ2gAiLWUGuMhfCDrzUbeTo/IzO6Mnvo2VLPjk8B/+kSyah+vu6xVPZYx+eJSyb9LQARJrndqO+wakQFRnOuWKVKFYUlLS5kCqjpjFR5t6L8bXVkRlpMJaPL6tT1t9tSprNU3/N53ylZLOVDPv97VUuPl261cOVCFknXRD0CemxOr9E00R4nLLdYi0UxkXlCvZlbhMUPB+TGIJTAjZvoovqjUikv0cRVsjNe2qrk+utEhCp5mCw9TRnO/9wnb73QgSNN2kxiptHEuZMH8wch6nlCN29yRNMnR6BM/eWNPOduYZmdKbM06RLaUx0JkxqMpuDalyktbKx7x4qXiYIym7GKF18u7PlNLP2tV8hv/k0i+a0JzM/WxuI3zLRzZdo0hchlNg5FsajqdX7aLY8p2jSaGBzkIbJ9UohExI+Vyw6WHBI8dw4CbsZOMpgsr4eIFlVhkRzdkhqCe2MHy+VUYfC/qQ2kcKy+i/BkVeSEz/9dSkjPhp5dOPK2yeluBjN+psFEXoEen7bV+TqOJnr5/IeWuvuD9BRqfIZS7DLrhyJC64V+sumPKTFDkfJ5fAoKgDl//N1rils3HpveY7J22dOYiJWe0Y1daXbU/WNmBq/kC8bz/2Iet+WLWPilBTq4OuU1tl6J8aDv0vT92xWY1lfjS9NYIYYqo5bqoWknVZsMIWmcjsbUwpZcXuKYWDKm4/HTf5SKH6Udlp1ab8YiKWb7KpNRPrCzMaWwWeYV3fp9XoDIO+wPjrHWFNtlT+Ni1Sa9QE/J9KYa3btWvCWf56Zd0wV1DuL4qwmz4+Zljd4mFJOeHZDs2WSh+Kdufx6IBWKTOxTRRRm/pwRxvTWvp+Ao2NY1Hm8M7Cy1nqWMto4XRcpSyQbulsxC+O4GhVD6egoWv25p/3XrrzqWBn6lqSNTi2WwAyv5a3lcXewxIsPKFXQkCmdnW+7wp/sw5vOF3eKPaz6aoqrqolMSSoRRNg1r10cmyZGeGJIXo410FUVeb5+5fCa0rBha8f/AnLI58C82OkMlK9RbhhTKFxK/oOk3Kdoh8jL32m83zkphw5sfSXv7ppdOm7PnFxKM7CRtLcrOqMMWtuKairK2HiC1t9BPN1FhbuM2tfkm83TdhvDk6+yYu6Ks8rrT619klVeeOw4zn3fSkQxQHGrA934Nqy38bUYR9fATUu5zUBUGlqqpfUeKPPO0fn0wc5BfHZwUFsI2XxJGhsaq9W3RbVZF8PkEbC71FZt7L8jvYnDg/mK4ME2ZJJaYQ0IlliSJMjRJIrOGhEjNNrEqi3aMzTlCC/iOxbkMdmxhX5ZxXVMTE2leiP/VWDA/wdBQUWNoSkgwNtVUGBvgtlLDz1hsDF56sahusUC5bNsyiGVnXPqRNFXXQKZ4w+q/LPXjZKM12VmhXBdXrI7OjaX/wkrQWKtXbqHY8pdBMDZrsikse1JK4i8cetCDUQaz8y7bR5AXwSvefOQhG71g15cXn+ubw4khaex/ufZQk6muIw7y1DmoP0Pqrs2hGfqKts86A1SMvTtuVV7ZHANTwqIeD2KM4Zj+5fveW4ok6oULEjYzv9vIrHzL1FdotdUmo6G+LQH44YUCk0GYpyHQ8pVFAa7131gH76zg2xjml0zLI50pSyiKKY6Lroiz6dpb9JbZTPw+VtDpLwxW0B4Gc58XHIGT5Km1Sy77pGEaQIwyt4YbC2KEsY0L846kFv7Ai4jLqlYm6qqVcVkRvJGC7v7vjWphijrGWNiqsQwGHRwIpA4OB9MOLaUGLjlIVVHTHX7+joxAaobD38+RDtejvh85cc1odopEUePjosq1VkNrmyFJU8A36YTZKi7eEGjmpNY7d2Q2MF/vDGaufcNkXJnHou26CtewymSlNDsiSuxMVqhVNoXYGRUhyU5ShpbTTonEp2lBT8WiJ9AMHI8D8vRWg7Mu2jsYtN6ZZY7XV+II3mM+5OR7yeG/JymU0cb4EFFN1x5T4KE82I0Vv2PJUqkSsv8BX0JvgPfBO/Wzxk8cynuIzWjLzF7S5hGyJZSX/Qj4a225tkMR7xcQV15J8plQeWM3OW3//Wr4xpNh9nMpUumz/AM2kXyX+BOFKY+pO1/m799Gm3b2590MzmSEGZtrhhOepuzCtFhxfopGw/2pWGr9zurDKyZGJXoYY8WRhgSVcFwiS5RGWk72nUCiLPclzwCt56AId6L0DS9xQAQncWIDo5fJ3TOT9U8tM8QeqxX9amcyo+Rg2cdlNusZohTKZbLvUYrfYTL5KGUNqZVIHPQll/kS+2HIk3urWWr9R0LktvhE6f0N8ZIIg04prDKwpIb0wnStOD9ZI7xHme5L6aQQl1N8OwF9a2TR7RGYihOPSUU/CcWPZCIE9kuvej3IuEXeLqCwbnEZb7cI2FMPL4fy/+cQerG9MdZtVi22n9A7U4UVP5IKP/Js5j3sSbMJfdgebZhC7J3Y40dZ6WPpk756x+qxvPp9C40S85VM+8B/k9b4LlmTy1IbXRp1frQyND3X+NW4MiT6IBSPyURPsfQRWHibnclaAmmMtynh41hhhqK9qULTelyX5voRdtwVPEsRCFOf8Sv8LFUoSHkGG13eA0hXRljegMZjIEaTNyWfRZje4jPnU0eeJn9aDHYwTJPblvWOMAANHSNzO0auLe7N7WUuxk/P0M7ecb3gPodGtq2lfrTB+urAn4XrqGQhqO8uylkEEd/NfDLziFRFhSd7C3uBdXRC0tSfZ8/qfibd5mblxeceq6nOHc2Lg+Kj4+zukeqa3BHyu0HzokHttegkFjMgQQKFqhPdom5J9zdqKEx3FVb6cZol0zBcJCPamGIjEWwUY0oUksFyG5SB9hqKv21M++fePkmZHztiOB1RSWyC1HDKk93ibultFoD9+ETx9CXOKatWTAfZ8cuDF0+EhbsYhEsC5uyDF6MeLOCS8c8uN4aSmbfBtP3V/DDSz34PmpgP9hyP+fWSgzXnwGE4Qtv1xGvnz3nxHUeRziPQE5Qf34lI+5HceK8uLPvJHhszPGwL2lQOm/nLZjjTA66hnBlhLpdqML09/dii3jOGBvtUWV6GotlkFEwyFhVEhAuOMpm+LGTxV5U+kSuSm0PFmREKXklihlMdxnz3gP9b0MKF0TERfUT6C46OnK1Iiq/qiMwu3xDZWhO7qtTAr7ZZawUmhc7rcibfsDOTYcKTkmiIMCFEiKNcnUthhgTbpKxhMJpsBxesqlAb/73tHx6ZUapIVDlZCTGXptg86+h+P/xNoXzGoX2tDkPs2m3nsaldWkt5vC2zNZNRUjyrXcZ+d0UqNDDzOOm6pfOktXpnVmwFCz7H/BIXnqlRjI9NjHCVagwrR4cXKROfpUTNgtweQdoGh7/v5u+zgn6Yj78qDg1NLg2xK9IoCcKJGbkDr45RODUBhEhlRQbDSrfYA4JCE7P40/wUOQEW8czU8QfsTKZgApXQ1lyZFWykmeyREqk+U7yen1X09k8C+TXdGKBODZElKpWhjtIQmOGbPBBRUho5kJISOSBkrE5O6Y8orQkRqhuzLsaliSyIiWKv6/Sk8PSBLxRVrhgCtS0zgJrVSvXtilfWPDf5abJiq2QOh6wqNg4Bh10HiY2tlNntgbhYBFIdNieg3piadbpGo0HfIHfWqM4R6PX8cWpDYmODTp+oSg9VpKvVlJquUIVlKpRK8GRmhmYmcHP0xPCqH95OFDxkc3HcyO+Kei5wvV5jcd/hhS8BOz00SSK1yEI4bJMoFJQkschlUqvkDnH5zv+PRHqzztd33a/y4P7bDWmnNi3fBBmXZ66auZI3Y9UMSEixd5lNXakOJjDtX5EgJ65x7fMeNGiDkHp83NMHRetUTk6pG1jeWzqxrGBNZi0E1sUUqDTOyEhNDsyYgnPegM581U1lSYkzt7i84oestJLi7MzEN34fSP4BpI9+lI+kAH/Shx2bcrKLysbl5J0rLs4bX1IM8djiubHi9N7qytCooG9mkgkvFson6pMJZdEKZ8xXtTeRPaCOsLZPKBaGX6EdE4z7WTTbgbuRxsLvJuzMYOPWVMOxsGTKSa6ZQ16PXXXwRCLRFFvWGJlkrgyZ1VnwcQM96MisIGZQ1xAxMZBRablXzTGRjGepThLbSE6IajpWztAw/95lYtADXDfNlYzx7OMG11bXV64rxB22/fB43XRZ94MVngjhxQJ4odvb+7kX+D9P/3M6zFZXVLoKKsuriguKKioKx4PkfN/XvnhM7y+nUcuW0IJay2iB5YO0JfT+Miq1/J07Tw8sGwCdofdV78sHPa96oMo7cUrWfnPWvq/kvh+LYYd3byXltzlhSsY+c8Z+0Gn6/uz7FNv/Z795dObymTD5MrGzAPMCfxFLjme0jLeVp/pWF7449+1mnG9CYDMSz8z8Dn6ouv3qw2xbOOArv2vpe9iyYV2gA9lIA9vQwTVhbHo4zS9k2y2/8DXkJeiSh9xfNqZ5Gb/TnHV/ClvGRpbeHnFZ1HaVzBkVKXOmKsPCUpRSZ1SEPCdFpawgZh0JCjqSRSS2XwySnBIfVTlUcmdElMxpV4WpU1TvRVRFnXJi9hG6ZEFgvXOXgsSnoblR8qNI8FUk/kHMf0KVXKMd3ookVzPh77YQmogvl+9FwGz+ts5auXc2bDeFWhtZk6ElfcG8btfjrbhgcSYD/s5mNZCZLPcGNrvBncV0a2DZiQYfXwORaCASDKAdT5TWByd5EMJF43BRcQ6NL67hYQPeRxSeg3cb84P0zvLUclj2CWvzu/wT3qvOn+BlrEuX6cLJAsa4hxYsnO+lI2LuaYlsh4h3ilHQaLEb4HzzU0pk240WWPmGZy9PUXgbtL8TT6/Om1ZNXWAKhr/Xcfea2dyoM1zePiuXbd7LTfdt9yWTuD9xMP9PmT0hoAPn40Yu1VuSIkniVZ8rsd53oERITxDAUjODfCYEGeoySgVc1y9myb9MASAwAANVXQyLXQgny4sfpg2Cu+cBPxBwv+UjWChJDvMbYwUqLviXigOGdBeCyQRlKvU0CMpeFhYY1cSrAxYmKD0NIkIWFvwvJLxHwwvgeyvcdm8ZQCro4REIgY6SibWjbkj0DQaUhSnG2C7AEW/zsNvBoecbDlvmRSLWIGoG4QkqXDhKuhQcW1YEFr3bpA95bV6CgpKaIGoOjI6o1AE1JbVA1ByY2yQMLUZjJwFZ8RYGxJGO7uMzEHKGAzR54ypck6u55MwCGOOR5ezHLzLO0x42rmXcHhRMKDNAHBAznTTLnsXZizn2meugeQ6Z74gFDjxeKFE++bn8yHpGiDyeUUVg3UcAwVlyDbyUvL/VnAztPnu1uLb4hR8fM2sYYgYZBnHGVpsvQPFNq2sYHhP8TVqV70Dhmc314h1Hk1FDSjFw+Ao63+yEct6/BNYv80a5AAj4Kynlsj9Zo8D1Vlf8xa9cS6+k19Ib6e1z+Q7Mv/P09Tjy9MPpP31w45b3X2DIep9iul92A64ClDdnT5KXtrIao3VXc0nXYlrbK5ygrIr0LC/1r75O2EB8BFKQwRXfaAIOfydlcb9Cz3IRgYip8GQs71Y9y0tnrk6zl1mN2cYX/YQEu+TL4cleMlfmy6bRAYavxUQsoz9Xfniyl8xN5iOB6IwG2TmIjYN93QRxIEkJfD+JWAD+7JB5cZlzoIUXSkGWvWSuzFcAFrLoooPsJXMJYu7ZiqqM9JTKRVo3ymDT6aAa0xewuB5wOCD92wrKXQXKmbvGS3a0lQdoqfSidwmSHzYAVj+qY6gpiEY8VHZyQl+u4WRcpJWHhCmNiF4nTlZklfuR5Qw78tOyy4tDJ8j62KQYL6sTdSg4oBrUu7LDwgnB/vlOdIxk7H6DxdMD/5Th/ute24r64n72jSOxIY/XLq7dpol2LwujqGZfis/6CLMtz/qbwOzInb6FQy8e+RVfcEX5nbRNceUE66olOismYfMbiSGjE2Koj81dC61AhQAx88fOBbXoI0H7f4Cb2yvA+2fVLgA+/3XX9rX9y7719cUABAYKIMDfiRCPBK7//aBBXK+rH7UQ9SjYNllPXdrjnD1Iuu1w0OA8dF4HOFm17/EG6fHqKGUDbsixVcR9Qaw4w+pZFu27hNTmk+TyLs3iZVDwqfd7Ev/Ow+5/Mjb3Ve7Vi7HK2YX2Lfswbae9uMDWcILNdaaP1YXMZePguThzMkkpmYXeNZTZxZxECeEAIpXunG0CK5NDbuw+WgzSFuYooucME1+D/deNAxbYAhDpx8mlzz1vkboWPfP4tU8iuMfzrnQqEqTWcYf8AqoWIh1/9ItsRsbSXkXHXrcZ5Ju5mF1HVDVzeehN4d8lyM3AaiJ2pRTNJmqC4CzHCxcttQQpwcty1DRipxMnNsJMJU49NmcqOQKdp4VZP9E4J4yGdvBPPIiB8WEBsodH0u9stcS0Y6mCtPRS5uLmEN/+ILRpMMXCz9IxyHbkhLCcE12HyLNBZHcRZZAwA7CxjRAeWoY5uFyH/TfH/hUYsiBy3irhigo/0XBMcHcfkfiX9JwjOjhQ9Qtp47D9fQj5h0ehKIlWenQyqxJShaBOotBklDFMzRJaPUGG8bW+tPX0JYCILUmnwCPH7Jp0B68yVZJGBJhA+KF8Fc/Ct/BSvNnzIH+QSl3WFhmUby4wTpt2BhTSmgMB/in+K13sKay8ruu3mckNUmN1m1egP4JiX38UTxf6u1EZ64/GCPR3RwtjD4ygRA6HALRHZn8EGHE1o8g9hYg/n5hCr0GjCZpVqVCpFYuKglIUlkyVyoSld6VIKes0CYdmDYlVO7ykxUrURlalBo+1WEWk0mrV2K1oofdQhSqycJtiIUo0qBOqABdPkRa2d1uiRpV6oZo1eeNd22IbTDdY7RxSCjGeqhEjlZ07G8WAfueXs527ogTOhj5Yle1QjyWdvRx2Gk7GLSZoFFDBjR0sKlIvxgz4gZUr0qZWKzcAKams6a/ztf9PmwMA) format("woff2")}
:root{
  --bg:#0d1117;--surface:#161e2e;--surface2:#1e2a3f;
  --border:#2e4060;--border2:#3a5278;
  --amber:#ffd040;--amber-dim:#6b4800;
  --green:#00ffb0;--green-dim:#005538;
  --red:#ff3d5a;--red-dim:#6b0e20;
  --blue:#22d4ff;--blue-dim:#083a58;
  --purple:#d466ff;--purple-dim:#52087a;
  --teal:#00ffe5;--teal-dim:#004840;
  --orange:#ffaa22;--orange-dim:#703800;
  --lime:#d4ff00;--lime-dim:#425200;
  --pink:#ff44cc;--pink-dim:#700050;
  --fcs:#00c4a0;--fcs-dim:#004840;
  --text:#ffffff;--text-bright:#f0f8ff;--muted:#ffffff;
  --sans:"Readex Pro",Arial,Helvetica,sans-serif;
  --mono:ui-monospace,Menlo,Consolas,"DejaVu Sans Mono",monospace;
  --fs-xs:.66rem;--fs-sm:.72rem;--fs-base:.8rem;--fs-md:.9rem;--fs-lg:1rem;--fs-logo:1.21rem;
  --ov-btns-w:290px;
}
button,input,select{font-family:var(--sans)}
textarea,pre,code{font-family:var(--mono)!important}

*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--sans);
     height:100vh;height:100dvh;  
     overflow:hidden;display:flex;flex-direction:column}

header{background:linear-gradient(90deg,#0f1a2e,#161e2e 50%,#0f1a2e);
  border-bottom:2px solid var(--amber);padding:.45rem 1rem;
  display:flex;align-items:center;flex-shrink:0;
  box-shadow:0 2px 0 rgba(255,208,64,.25),0 6px 30px rgba(0,0,0,.7)}
.logo{font-family:var(--sans);font-size:var(--fs-lg);color:var(--amber);
  letter-spacing:.1em;
  text-shadow:0 0 10px rgba(255,208,64,.9),0 0 30px rgba(255,208,64,.5),
              0 0 60px rgba(255,208,64,.2)}
.logo-sub{font-family:var(--sans);font-size:var(--fs-xs);letter-spacing:.22em;
  text-transform:uppercase;color:var(--amber);margin-top:.1rem;opacity:.75}
#hdr-right{margin-left:auto;display:flex;flex-direction:column;align-items:flex-end;gap:.15rem}
#hdr-uptime{font-family:var(--sans);font-size:var(--fs-sm);color:var(--amber);
  letter-spacing:.08em;text-shadow:0 0 8px rgba(255,208,64,.5);white-space:nowrap}
#hdr-version{font-family:var(--sans);font-size:var(--fs-xs);color:#6b4800;
  letter-spacing:.14em;text-transform:uppercase}

#ql-bar{background:#111828;border-bottom:1px solid var(--border);
  padding:.4rem 1rem;display:flex;flex-wrap:wrap;
  justify-content:center;align-items:center;gap:.5rem .6rem;flex-shrink:0}
.ql-btn{
  font-family:var(--sans);
  font-size:var(--fs-xs);
  font-weight:bold;
  letter-spacing:.06em;
  text-transform:uppercase;
  text-decoration:none;
  padding:.3rem .7rem;
  border:1px solid var(--amber-dim);
  border-radius:4px;
  color:var(--amber);
  background:rgba(255,208,64,.06);
  white-space:nowrap;
  flex:0 1 auto;
  text-align:center;
  transition:background .15s,box-shadow .15s}
.ql-btn:hover{
  background:rgba(255,208,64,.16);
  box-shadow:0 0 8px rgba(255,208,64,.3)}
@media(max-width:640px){
  #ql-bar{gap:.45rem .5rem}
  .ql-btn{flex:0 1 calc(33.333% - .5rem);min-width:5.6rem}
}

#zone-status{background:#111828;border-bottom:1px solid var(--border);
  padding:.28rem 1rem;display:flex;align-items:center;
  flex-shrink:0;font-family:var(--sans);font-size:var(--fs-sm);overflow:hidden;
  flex-wrap:wrap;row-gap:.15rem}
.sf{display:flex;align-items:center;gap:.35rem;padding:0 .8rem;
  border-right:1px solid var(--border);white-space:nowrap}
.sf:first-child{padding-left:0}
.sf:last-child{border-right:none;margin-left:auto;padding-right:0}
@media(max-width:600px){
  #zone-status{overflow:visible}
  .sf-temp{padding-left:0;border-left:none;
    flex-basis:100%;border-right:none;
    border-top:1px solid var(--border);padding-top:.25rem;margin-top:.1rem}
}
.sl{color:#fff;font-size:var(--fs-xs);letter-spacing:.12em;text-transform:uppercase}
.sv{color:var(--text)}
.sv.ok{color:var(--green);text-shadow:0 0 6px rgba(0,255,176,.4)}
.sv.warn{color:var(--amber);text-shadow:0 0 6px rgba(255,208,64,.4)}
.sv.hot{color:var(--red);text-shadow:0 0 6px rgba(255,61,90,.4)}
.sv.cyan{color:var(--teal);text-shadow:0 0 6px rgba(0,255,229,.4)}

#zone-cmdbar{background:var(--surface);border-bottom:1px solid var(--border2);
  padding:.38rem .6rem;display:flex;align-items:center;
  flex-wrap:wrap;gap:.3rem;flex-shrink:0}
.tab-btn{font-family:var(--sans);font-size:var(--fs-base);font-weight:bold;
  letter-spacing:.08em;text-transform:uppercase;padding:.38rem .8rem;
  border-radius:4px;border:1px solid var(--border2);background:var(--surface2);
  color:#fff;cursor:pointer;transition:all .15s;user-select:none;
  flex-shrink:0}
.tab-btn:hover{color:var(--text-bright);border-color:#fff;background:#253550}

.tab-btn.active{
  color:var(--ta,var(--teal));
  border-color:var(--ta,var(--teal));
  background:rgba(var(--ta-rgb,0,255,229),.08);
  box-shadow:0 0 10px rgba(var(--ta-rgb,0,255,229),.1);
  text-shadow:0 0 8px rgba(var(--ta-rgb,0,255,229),.6)}
.cmdbar-spacer{flex:1;min-width:.2rem}

.radio-btn{font-family:var(--sans);font-size:var(--fs-sm);font-weight:bold;
  letter-spacing:.05em;text-transform:uppercase;padding:.3rem .6rem;
  border-radius:3px;border:1px solid var(--amber-dim);background:rgba(255,170,34,0.08);
  color:var(--amber);cursor:pointer;transition:all .15s;user-select:none;
  flex-shrink:1;min-width:0}
.radio-btn:hover:not(:disabled){color:#fff;background:rgba(255,170,34,0.25);
  box-shadow:0 0 8px rgba(255,170,34,0.3)}
.radio-btn:active:not(:disabled){transform:scale(.92)}
.radio-btn:disabled{opacity:.25;cursor:not-allowed;box-shadow:none}
.radio-btn.empty{opacity:.4;cursor:not-allowed}
.radio-btn.active{background:rgba(255,170,34,0.45);box-shadow:0 0 16px rgba(255,170,34,0.7),0 0 8px rgba(255,170,34,0.9),inset 0 0 12px rgba(255,170,34,0.4);
  color:#fff;border-color:var(--amber);font-weight:600}
.radio-btn.spinner{animation:spin 1.2s linear infinite}
@keyframes spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}

@media (max-width:1200px){
  .radio-btn{padding:.28rem .5rem;font-size:var(--fs-xs)}
}
@media (max-width:900px){
  .radio-btn{padding:.24rem .4rem;font-size:var(--fs-xs)}
}

.btn{font-family:var(--sans);font-size:var(--fs-base);font-weight:bold;
  letter-spacing:.05em;text-transform:uppercase;padding:.38rem .85rem;
  border-radius:4px;border:1px solid;background:transparent;cursor:pointer;
  transition:all .14s;white-space:nowrap}
.btn:hover{filter:brightness(1.6);box-shadow:0 0 12px currentColor}
.btn:active{transform:scale(.95)}
.btn:disabled{opacity:.35;cursor:not-allowed;filter:none;box-shadow:none}
.btn-sm{font-size:var(--fs-sm);padding:.22rem .5rem}
.btn-red{color:var(--red);border-color:var(--red-dim)}
.btn-amber{color:var(--amber);border-color:var(--amber-dim)}
.btn-green{color:var(--green);border-color:var(--green-dim)}
.btn-blue{color:var(--blue);border-color:var(--blue-dim)}
.btn-teal{color:var(--teal);border-color:var(--teal-dim)}
.btn-muted{color:#fff;border-color:var(--border2)}
.btn-purple{color:var(--purple);border-color:var(--purple-dim)}
.btn-orange{color:var(--orange);border-color:var(--orange-dim)}


#zone-content{flex:1;overflow-y:auto;position:relative;
  padding:.8rem 1rem calc(1.6rem + env(safe-area-inset-bottom, 0px))}

#zone-content::-webkit-scrollbar{width:4px}
#zone-content::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}

.tab-panel{display:none}
.tab-panel.active{display:block}

#restart-banner{display:none;background:#2a1400;border-bottom:1px solid var(--amber-dim);
  padding:.32rem 1rem;font-family:var(--sans);font-size:var(--fs-sm);color:var(--amber);
  text-align:center;letter-spacing:.06em;flex-shrink:0}
#restart-banner.show{display:block}

#wfm-shutdown-overlay{display:none;position:fixed;inset:0;z-index:9999;
  background:rgba(0,0,0,.85);backdrop-filter:blur(4px);
  align-items:center;justify-content:center}
#wfm-shutdown-overlay.open{display:flex}
#wfm-shutdown-box{background:linear-gradient(135deg,#2a0a0e,#1a0608);
  border:2px solid var(--red);border-radius:8px;padding:2rem 2.2rem 1.6rem;
  min-width:320px;max-width:90vw;box-shadow:0 20px 90px rgba(255,61,90,.4);
  display:flex;flex-direction:column;align-items:center;gap:1rem;
  text-align:center;animation:wfmPulse 2s ease-in-out infinite}
@keyframes wfmPulse{
  0%,100%{box-shadow:0 20px 90px rgba(255,61,90,.4)}
  50%{box-shadow:0 20px 110px rgba(255,61,90,.75)}
}
#wfm-shutdown-hdr{font-family:var(--sans);font-size:var(--fs-md);letter-spacing:.22em;
  text-transform:uppercase;color:var(--red);text-shadow:0 0 12px rgba(255,61,90,.8)}
#wfm-shutdown-msg{font-family:var(--sans);font-size:var(--fs-lg);color:var(--red);line-height:1.6}
#wfm-shutdown-sub{font-family:var(--sans);font-size:var(--fs-sm);color:#ffffff;letter-spacing:.03em}

#login-screen{display:none;position:fixed;inset:0;z-index:9999;
  align-items:center;justify-content:center;
  background:rgba(4,7,13,.86);backdrop-filter:blur(2px)}
#login-screen.open{display:flex}
#login-card{width:90%;max-width:320px;background:var(--panel,#141a24);
  border:1px solid var(--border,#2a3444);border-radius:10px;
  padding:1.4rem 1.3rem;box-shadow:0 12px 40px rgba(0,0,0,.5);
  font-family:var(--sans)}
#login-card h2{margin:0 0 .2rem;font-size:var(--fs-lg);color:var(--amber,#ffd040);
  letter-spacing:.02em}
#login-card p.sub{margin:0 0 1rem;font-size:var(--fs-base);color:var(--muted,#8a95a8)}
#login-card label{display:block;font-size:var(--fs-base);color:var(--muted,#8a95a8);
  margin-bottom:.3rem}
#login-pw{width:100%;box-sizing:border-box;padding:.55rem .6rem;
  background:var(--bg,#0b0f16);border:1px solid var(--border,#2a3444);
  border-radius:6px;color:#fff;font-size:var(--fs-md);font-family:var(--sans)}
#login-pw:focus{outline:none;border-color:var(--amber,#ffd040)}
#login-btn{width:100%;margin-top:.8rem;padding:.6rem;border:none;border-radius:6px;
  background:var(--amber,#ffd040);color:#1a1300;font-weight:600;font-size:var(--fs-md);
  cursor:pointer}
#login-btn:disabled{opacity:.5;cursor:default}
#login-btn:hover:not(:disabled){filter:brightness(1.08)}
#login-err{min-height:1.1rem;margin-top:.6rem;font-size:var(--fs-base);color:var(--red)}

#offline-bar{display:none;position:fixed;top:0;left:0;right:0;z-index:1000;
  background:#3a0a0a;border-bottom:1px solid #8b1a1a;color:var(--red);
  font-family:var(--sans);font-size:var(--fs-base);text-align:center;
  padding:.35rem 1rem;letter-spacing:.06em}
body.offline #offline-bar{display:block}

#toast-stack{position:fixed;bottom:1.5rem;right:1.2rem;display:flex;
  flex-direction:column-reverse;gap:.45rem;z-index:1200;pointer-events:none;
  max-width:92vw}
.toast-item{background:#1a2438;border:1px solid var(--border2);border-radius:8px;
  padding:.55rem 1.2rem;font-family:var(--sans);font-size:var(--fs-md);
  color:var(--text-bright);box-shadow:0 8px 40px rgba(0,0,0,.8);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  opacity:0;transform:translateX(2rem);transition:opacity .2s,transform .2s;
  pointer-events:none}
.toast-item.show{opacity:1;transform:translateX(0)}
.toast-item.ok{border-color:var(--green-dim);color:var(--green);
  box-shadow:0 0 20px rgba(0,255,176,.2)}
.toast-item.err{border-color:var(--red-dim);color:var(--red);
  box-shadow:0 0 20px rgba(255,61,90,.2)}
.toast-item.info{border-color:var(--amber-dim);color:var(--amber);
  box-shadow:0 0 20px rgba(255,208,64,.2)}

.stub-panel{display:flex;align-items:center;justify-content:center;
  min-height:200px;font-family:var(--sans);font-size:var(--fs-base);
  color:#fff;letter-spacing:.1em;text-transform:uppercase;
  border:1px dashed var(--border);margin:.5rem 0;border-radius:5px}

::-webkit-scrollbar{width:4px}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}
.hidden{display:none}

.ov-card{background:var(--surface);border:1px solid var(--border2);
  border-radius:5px;overflow:hidden;
  box-shadow:0 4px 20px rgba(0,0,0,.4);margin-bottom:.65rem}
.ov-card-hdr{background:#131c2d;border-bottom:1px solid var(--border);
  padding:.38rem .9rem;display:flex;align-items:center;
  justify-content:space-between}
.ov-card-title{font-family:var(--sans);font-size:var(--fs-xs);letter-spacing:.28em;
  text-transform:uppercase;color:#fff}

.ov-row{display:grid;
  
  grid-template-columns:10px 1fr 64px 78px 72px 90px 46px var(--ov-btns-w);
  align-items:center;gap:.45rem;
  padding:.42rem .9rem;
  border-top:1px solid var(--border);
  transition:background .1s}

.ov-card-hdr.ov-hdr-grid{display:grid;gap:.45rem;align-items:center;
  grid-template-columns:10px 1fr 64px 78px 72px 90px 46px var(--ov-btns-w)}
.ov-hdr-owner,.ov-hdr-mode,.ov-hdr-status,.ov-hdr-port{
  font-family:var(--sans);font-size:var(--fs-xs);letter-spacing:.14em;
  text-transform:uppercase;color:#fff;text-align:left;white-space:nowrap}
.ov-row:hover{background:var(--surface2)}
.ov-row.not-inst{opacity:.38;pointer-events:none}

.ov-name{min-width:0}

.dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;display:inline-block}
.dot-on{background:var(--green);
  box-shadow:0 0 8px var(--green),0 0 16px rgba(0,255,176,.5)}
.dot-off{background:#4a6a88;
  box-shadow:0 0 4px rgba(74,106,136,.8)}
.dot-fail{background:var(--red);
  box-shadow:0 0 8px var(--red),0 0 12px rgba(255,61,90,.4)}
.dot-warn{background:var(--amber);
  box-shadow:0 0 8px var(--amber),0 0 12px rgba(255,208,64,.4)}
.dot-unknown{background:var(--purple);
  box-shadow:0 0 8px var(--purple),0 0 12px rgba(200,100,255,.4)}

.ov-name{font-family:var(--sans);font-size:var(--fs-md);font-weight:bold;
  color:var(--text-bright);overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;cursor:pointer;text-decoration:none}
.ov-name:hover{color:var(--teal);text-shadow:0 0 8px rgba(0,255,229,.5)}
.ov-name.ni{color:#fff;font-weight:normal;font-style:italic;cursor:default}
.ov-name.ni:hover{color:#fff;text-shadow:none}
.ov-state{font-family:var(--sans);font-size:var(--fs-sm);text-align:left}
.st-active{color:var(--green);text-shadow:0 0 6px rgba(0,255,176,.4)}
.st-failed{color:var(--red);  text-shadow:0 0 6px rgba(255,61,90,.4)}
.st-inactive{color:#fff}
.st-notinst{color:#fff;font-style:italic}
.st-unknown{color:var(--purple);font-style:italic}
.ov-port{font-family:var(--sans);font-size:var(--fs-xs);color:#fff;
  text-align:right;white-space:nowrap}
.ov-nr{font-family:var(--sans);font-size:var(--fs-xs);color:#fff;
  text-align:right;white-space:nowrap}
.ov-nr.nr-warn{color:var(--amber);text-shadow:0 0 6px rgba(255,208,64,.4)}

.ov-owner{font-family:var(--sans);font-size:var(--fs-xs);color:var(--text);
  text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ov-owner.own-ok{color:#fff}
.ov-owner.own-warn{color:var(--amber);text-shadow:0 0 6px rgba(255,208,64,.4)}

.ov-mode{font-family:var(--sans);
  font-size:var(--fs-xs);color:#fff;letter-spacing:-.02em;
  text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ov-mode.perm-warn{color:var(--amber)}
.ov-mode.perm-fail{color:var(--red);text-shadow:0 0 6px rgba(255,61,90,.4)}

.pc-ok {font-family:var(--sans);font-size:var(--fs-xs);color:var(--green);
  text-shadow:0 0 4px rgba(0,255,176,.4);white-space:nowrap;text-align:center}
.pc-dup{font-family:var(--sans);font-size:var(--fs-xs);color:var(--red);
  text-shadow:0 0 4px rgba(255,61,90,.4);white-space:nowrap;
  text-align:center;cursor:default}

.pc-empty{display:block}

.ov-btns{display:flex;gap:.28rem;justify-content:flex-end;
  flex-shrink:0;flex-wrap:nowrap;width:100%;min-width:0}

#ov-global-bar{position:sticky;bottom:0;background:var(--surface);
  border-top:1px solid var(--border2);padding:.45rem .9rem;
  display:flex;flex-wrap:wrap;align-items:center;gap:.5rem}
#ov-global-lbl{font-family:var(--sans);font-size:var(--fs-xs);letter-spacing:.2em;
  text-transform:uppercase;color:#fff;white-space:nowrap}

@media(max-width:900px){
  .ov-row,.ov-card-hdr.ov-hdr-grid{
    grid-template-columns:10px 1fr 64px 72px 90px 46px var(--ov-btns-w)}
  .ov-mode,.ov-hdr-mode{display:none}
}
@media(max-width:600px){
  .ov-row,.ov-card-hdr.ov-hdr-grid{grid-template-columns:10px 1fr}
  .ov-owner,.ov-mode,.ov-state,.ov-port,.ov-nr,.pc-ok,.pc-dup,.pc-empty{display:none}
  .ov-hdr-owner,.ov-hdr-mode,.ov-hdr-status,.ov-hdr-port{display:none}
  .ov-btns{grid-column:1 / -1;justify-content:flex-start;margin-top:.3rem}
}

.s3-card{background:var(--surface);border:1px solid var(--border2);
  border-radius:5px;overflow:hidden;
  box-shadow:0 4px 20px rgba(0,0,0,.4);margin-bottom:.65rem}
.s3-card-hdr{background:#131c2d;border-bottom:1px solid var(--border);
  padding:.38rem .9rem;display:flex;align-items:center;
  justify-content:space-between}
.s3-card-title{font-family:var(--sans);font-size:var(--fs-xs);letter-spacing:.28em;
  text-transform:uppercase;color:#fff}
.s3-card-meta{font-family:var(--sans);font-size:var(--fs-xs);color:#fff}

.s3-controls{display:flex;align-items:center;gap:.4rem;
  padding:.42rem .9rem;background:#131c2d;border-bottom:1px solid var(--border)}
.s3-scope{font-family:var(--sans);font-size:var(--fs-sm);font-weight:bold;
  letter-spacing:.05em;text-transform:uppercase;padding:.22rem .65rem;
  border-radius:3px;border:1px solid var(--border2);background:transparent;
  color:#fff;cursor:pointer;transition:all .14s}
.s3-scope.on{color:var(--teal);border-color:var(--teal);
  background:rgba(0,255,229,.07)}
.s3-scope:hover:not(.on){color:var(--text-bright);border-color:#fff}
.s3-filter{font-family:var(--sans);font-size:var(--fs-base);padding:.25rem .55rem;
  background:var(--surface2);color:var(--text-bright);
  border:1px solid var(--border2);border-radius:3px;outline:none;
  flex:1;min-width:0;transition:border-color .15s}
.s3-filter:focus{border-color:var(--amber);box-shadow:0 0 6px rgba(255,208,64,.2)}
.s3-filter::placeholder{color:#fff}

.s3-gen-row{display:grid;grid-template-columns:10px 1fr 64px 78px 82px auto;
  align-items:center;gap:.55rem;padding:.38rem .9rem;
  border-top:1px solid var(--border);cursor:pointer;transition:background .1s}
.s3-gen-row:hover{background:var(--surface2)}
.s3-gen-name{font-family:var(--sans);font-size:var(--fs-base);
  color:#fff;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.s3-state{font-family:var(--sans);font-size:var(--fs-sm)}

.s3-gen-row2{display:contents}

@media(max-width:900px){
  .s3-gen-row{grid-template-columns:10px 1fr 64px 82px auto}
}
@media(max-width:600px){
  .s3-gen-row{grid-template-columns:10px 1fr}
  .s3-gen-row2{
    display:flex; grid-column:1 / -1;
    align-items:center; justify-content:space-between;
    margin-top:.25rem;
  }
  .s3-gen-row2 > button{justify-self:start; width:max-content}
}

#dpanel-overlay{display:none;position:fixed;inset:0;
  background:rgba(0,0,0,.55);backdrop-filter:blur(3px);z-index:200}
#dpanel-overlay.open{display:block}

#dpanel{display:none;position:fixed;right:0;top:0;bottom:0;width:380px;
  background:var(--surface);border-left:1px solid var(--border2);
  flex-direction:column;
  box-shadow:-4px 0 40px rgba(0,0,0,.8);z-index:201;overflow:hidden;
  --panel-accent:var(--teal)}
#dpanel.open{display:flex}
@media(max-width:480px){
  #dpanel{width:100%;border-left:none;border-top:1px solid var(--border2)}
}

#dpanel-hdr{
  background:linear-gradient(90deg,#0f1a2e,#161e2e 50%,#0f1a2e);
  border-bottom:2px solid var(--panel-accent);
  padding:.65rem .9rem;flex-shrink:0;position:relative;
  box-shadow:0 2px 0 rgba(0,0,0,.3)}
#dpanel-close{position:absolute;right:.7rem;top:.55rem;
  font-family:var(--sans);font-size:var(--fs-sm);color:#fff;
  cursor:pointer;padding:.1rem .45rem;
  border:1px solid var(--border2);border-radius:3px;transition:all .14s}
#dpanel-close:hover{color:var(--red);border-color:var(--red-dim)}
#dpanel-unit{font-family:var(--sans);font-size:var(--fs-lg);
  color:var(--panel-accent);letter-spacing:.06em;
  margin-right:2.5rem;margin-bottom:.15rem;
  text-shadow:0 0 8px color-mix(in srgb,var(--panel-accent) 50%,transparent)}
#dpanel-desc{font-family:var(--sans);font-size:var(--fs-base);
  color:#fff;margin-bottom:.42rem}
#dpanel-badges{display:flex;gap:.35rem;flex-wrap:wrap}
.dpbadge{font-family:var(--sans);font-size:var(--fs-xs);
  padding:.15rem .5rem;border-radius:3px;border:1px solid}
.dpbadge-state-active {color:var(--green); border-color:var(--green-dim);background:rgba(0,255,176,.07)}
.dpbadge-state-failed {color:var(--red);   border-color:var(--red-dim);  background:rgba(255,61,90,.07)}
.dpbadge-state-other  {color:#fff;      border-color:var(--border2)}
.dpbadge-enabled      {color:var(--teal);  border-color:var(--teal-dim)}
.dpbadge-disabled     {color:#fff;      border-color:var(--border)}
.dpbadge-info         {color:#fff;      border-color:var(--border2)}
.dpbadge-warn         {color:var(--amber); border-color:var(--amber-dim)}
.dpbadge-crit         {color:var(--red);   border-color:var(--red-dim)}

#dpanel-body{flex:1;overflow-y:auto}
#dpanel-body::-webkit-scrollbar{width:3px}
#dpanel-body::-webkit-scrollbar-thumb{background:var(--border2)}

#dp-own-zone{margin-top:.15rem}
.dp-own-row{display:grid;grid-template-columns:78px 1fr;gap:.5rem;
  align-items:baseline;padding:.12rem 0}
.dp-own-lbl{font-family:var(--sans);font-size:var(--fs-xs);color:#fff;
  text-transform:uppercase;letter-spacing:.1em}
.dp-own-val{font-family:var(--sans);
  font-size:var(--fs-xs);color:var(--text);word-break:break-all}
.dp-own-val.warn{color:var(--amber)}
.dp-own-val.fail{color:var(--red)}

.dpzone-lbl{font-family:var(--sans);font-size:var(--fs-xs);
  letter-spacing:.22em;text-transform:uppercase;color:#fff;
  padding:.42rem .9rem .28rem;background:#131c2d;
  border-top:1px solid var(--border)}
.dpzone-lbl:first-child{border-top:none}

.dpbtn-row{padding:.45rem .9rem;display:flex;flex-wrap:wrap;
  gap:.3rem;border-bottom:1px solid var(--border)}

#dpanel-output{margin:.55rem .9rem;background:#0a1020;
  border:1px solid var(--border);border-radius:3px;
  min-height:100px;max-height:220px;overflow-y:auto;
  padding:.5rem .7rem;font-family:var(--sans);
  font-size:var(--fs-sm);color:#fff;line-height:1.65}
#dpanel-output::-webkit-scrollbar{width:3px}
#dpanel-output::-webkit-scrollbar-thumb{background:var(--border2)}
.dp-out-ok  {color:var(--green); text-shadow:0 0 4px rgba(0,255,176,.3)}
.dp-out-fail{color:var(--red);   text-shadow:0 0 4px rgba(255,61,90,.3)}
.dp-out-warn{color:var(--amber); text-shadow:0 0 4px rgba(255,208,64,.3)}
.dp-out-dim {color:#fff}

.pt-controls{display:flex;flex-wrap:wrap;align-items:center;gap:.4rem;
  padding:.42rem .9rem;background:#131c2d;border-bottom:1px solid var(--border)}
.pt-proto-btn{font-family:var(--sans);font-size:var(--fs-sm);font-weight:bold;
  letter-spacing:.05em;text-transform:uppercase;padding:.22rem .65rem;
  border-radius:3px;border:1px solid var(--border2);background:transparent;
  color:#fff;cursor:pointer;transition:all .14s}
.pt-proto-btn.on{color:var(--blue);border-color:var(--blue);
  background:rgba(34,212,255,.07)}
.pt-proto-btn:hover:not(.on){color:var(--text-bright);border-color:#fff}

.pt-legend{font-family:var(--sans);font-size:var(--fs-xs);color:#fff;
  padding:.35rem .9rem;background:#0e1622;border-bottom:1px solid var(--border)}

.dot-legend{display:flex;flex-wrap:wrap;gap:.55rem 1rem;
  font-family:var(--sans);font-size:var(--fs-xs);color:#fff;
  padding:.35rem .9rem;background:#0e1622;border-bottom:1px solid var(--border)}
.dot-legend-item{display:flex;align-items:center;gap:.32rem;white-space:nowrap}

.pt-table-hdr,.pt-row{display:grid;
  grid-template-columns:10px 70px 52px minmax(0,1fr) 58px minmax(0,1fr) 76px;
  align-items:center;gap:.55rem;padding:.38rem .9rem;
  border-top:1px solid var(--border)}
.pt-table-hdr{background:#131c2d;border-top:none;
  font-family:var(--sans);font-size:var(--fs-xs);
  letter-spacing:.14em;text-transform:uppercase;color:#fff;cursor:default}
.pt-row{cursor:pointer;transition:background .1s}
.pt-row:hover{background:var(--surface2)}
.pt-port{font-family:var(--sans);font-size:var(--fs-md);
  font-weight:bold;color:var(--text-bright)}
.pt-proto{font-family:var(--sans);font-size:var(--fs-sm)}
.pt-proto.tcp{color:var(--blue)}.pt-proto.udp{color:var(--green)}
.pt-process{font-family:var(--sans);font-size:var(--fs-base);color:var(--teal)}
.pt-pid{font-family:var(--sans);font-size:var(--fs-xs);color:#fff}
.pt-service{font-family:var(--sans);font-size:var(--fs-sm);
  color:var(--amber);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pt-service.unknown{color:#fff;font-style:italic}

@media(max-width:600px){
  .pt-table-hdr,.pt-row{grid-template-columns:10px 60px 40px 1fr}
  .pt-table-hdr span:nth-child(n+5){display:none}
  .pt-pid,.pt-service,.pc-ok,.pc-dup{display:none}
}

.jl-table-hdr,.jl-row{display:grid;grid-template-columns:10px 1fr 82px auto;
  align-items:center;gap:.55rem;
  padding:.42rem .9rem;border-top:1px solid var(--border)}
.jl-table-hdr{background:#131c2d;border-top:none;
  font-family:var(--sans);font-size:var(--fs-xs);
  letter-spacing:.2em;text-transform:uppercase;color:#fff;cursor:default}
.jl-row{cursor:pointer;transition:background .1s;user-select:none}
.jl-row:hover{background:var(--surface2)}
.jl-name{font-family:var(--sans);font-size:var(--fs-md);font-weight:bold;
  color:var(--text-bright);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.jl-state{font-family:var(--sans);font-size:var(--fs-sm)}
.jl-btn{font-family:var(--sans);font-size:var(--fs-xs);color:var(--purple);
  border:1px solid var(--purple-dim);border-radius:3px;
  padding:.15rem .45rem;background:transparent;cursor:pointer;
  white-space:nowrap;transition:all .14s}
.jl-btn:hover{filter:brightness(1.6)}
.dvl-agent{display:flex;flex-wrap:wrap;align-items:center;gap:.45rem;
  padding:.55rem .9rem;border-bottom:1px solid var(--border)}
.dvl-agent-note{font-family:var(--sans);font-size:var(--fs-xs);color:#fff;flex-basis:100%}
.dvl-group{padding:.35rem .9rem;background:#131c2d;border-top:1px solid var(--border);
  font-family:var(--sans);font-size:var(--fs-xs);letter-spacing:.2em;
  text-transform:uppercase;color:var(--purple)}
.dvl-row{display:grid;grid-template-columns:1fr auto auto;align-items:center;gap:.45rem;
  padding:.4rem .9rem;border-top:1px solid var(--border)}
.dvl-name{min-width:0;font-family:var(--sans);font-size:var(--fs-md);font-weight:bold;
  color:var(--text-bright);overflow-wrap:anywhere}
.dvl-sub{font-family:var(--sans);font-size:var(--fs-xs);font-weight:normal;color:#fff;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dvl-note{padding:.3rem .9rem;border-top:1px solid var(--border);
  font-family:var(--sans);font-size:var(--fs-xs);color:var(--amber)}

#jp-overlay{display:none;position:fixed;inset:0;
  background:rgba(0,0,0,.8);backdrop-filter:blur(4px);
  z-index:500;align-items:flex-start;justify-content:center;
  padding:1.5rem 1rem}
#jp-overlay.open{display:flex}
#jp-box{background:var(--surface);border:1px solid var(--border2);
  border-radius:5px;width:100%;max-width:960px;
  max-height:calc(100vh - 3rem);max-height:calc(100dvh - 3rem);
  display:flex;flex-direction:column;
  box-shadow:0 20px 80px rgba(0,0,0,.9)}

#jp-hdr{background:linear-gradient(90deg,#0f1a2e,#161e2e 50%,#0f1a2e);
  border-bottom:2px solid var(--purple);padding:.55rem 1rem;
  display:flex;align-items:center;justify-content:space-between;
  flex-shrink:0;
  box-shadow:0 2px 0 rgba(212,102,255,.2)}
#jp-title{font-family:var(--sans);font-size:var(--fs-base);color:var(--purple);
  letter-spacing:.08em;text-shadow:0 0 8px rgba(212,102,255,.4)}
#jp-ctrl{display:flex;align-items:center;gap:.4rem}
#jp-close{font-family:var(--sans);font-size:var(--fs-base);color:#fff;
  cursor:pointer;padding:.15rem .55rem;border:1px solid var(--border2);
  border-radius:3px;transition:all .14s}
#jp-close:hover{color:var(--red);border-color:var(--red-dim)}

#jp-toolbar{display:flex;align-items:center;gap:.4rem;flex-wrap:wrap;
  padding:.35rem 1rem;background:#131c2d;
  border-bottom:1px solid var(--border);flex-shrink:0}
#jp-info{padding:.25rem 1rem;background:#131c2d;border-bottom:1px solid var(--border);
  font-family:var(--sans);font-size:var(--fs-xs);color:var(--amber);flex-shrink:0}
#jp-info[hidden]{display:none}
.dp-copy-row{display:flex;align-items:center;justify-content:space-between;gap:.5rem}
#jp-grep{font-family:var(--sans);font-size:var(--fs-base);padding:.25rem .5rem;
  background:var(--surface2);color:var(--text-bright);
  border:1px solid var(--border2);border-radius:3px;
  outline:none;width:180px;transition:border-color .15s}
#jp-grep:focus{border-color:var(--amber);box-shadow:0 0 6px rgba(255,208,64,.2)}
#jp-grep::placeholder{color:#fff}
.jp-lines-btn{font-family:var(--sans);font-size:var(--fs-sm);font-weight:bold;
  letter-spacing:.05em;padding:.22rem .65rem;border-radius:3px;
  border:1px solid var(--border2);background:transparent;
  color:#fff;cursor:pointer;transition:all .14s}
.jp-lines-btn.on{color:var(--teal);border-color:var(--teal);
  background:rgba(0,255,229,.07)}
.jp-lines-btn:hover:not(.on){color:var(--text-bright);border-color:#fff}

#jp-body{flex:1;overflow-y:auto;padding:.7rem 1rem;
  font-family:var(--sans);font-size:var(--fs-sm);color:#fff;
  line-height:1.75;background:#0a1020;white-space:pre-wrap;word-break:break-all}
#jp-body::-webkit-scrollbar{width:4px}
#jp-body::-webkit-scrollbar-thumb{background:var(--border2)}
.jp-err{color:var(--red)}.jp-warn{color:var(--amber)}
.jp-ok{color:var(--green)}.jp-dim{color:#fff}
.jp-ts{color:#fff}

.ed-section{padding:.65rem .9rem .5rem;
  border-bottom:2px solid var(--border);background:#111828}
.ed-section-title{font-family:var(--sans);font-size:var(--fs-xs);
  letter-spacing:.28em;text-transform:uppercase;color:#fff;
  margin-bottom:.45rem}
.ed-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
  gap:.5rem .9rem;margin-top:.35rem}

.ed-field{display:flex;flex-direction:column;gap:.2rem}
.ed-field:hover{background:rgba(255,255,255,.02);border-radius:3px}
.ed-lbl{font-family:var(--sans);font-size:var(--fs-xs);
  letter-spacing:.18em;text-transform:uppercase;color:#fff}
.ed-inp{font-family:var(--sans);font-size:var(--fs-md);padding:.3rem .48rem;
  background:var(--surface2);color:var(--text-bright);
  border:1px solid var(--border2);border-radius:3px;width:100%;
  outline:none;transition:border-color .15s}
.ed-inp:focus{border-color:var(--amber);box-shadow:0 0 6px rgba(255,208,64,.2)}
.ed-inp.invalid{border-color:var(--red);box-shadow:0 0 6px rgba(255,61,90,.2)}
.ed-err{font-family:var(--sans);font-size:var(--fs-xs);color:var(--red);
  margin-top:.15rem;display:none}
.ed-err.show{display:block}

.ed-textarea{font-family:var(--sans);font-size:var(--fs-sm);
  padding:.45rem .55rem;background:var(--surface2);
  color:var(--text-bright);border:1px solid var(--border2);
  border-radius:3px;width:100%;min-height:220px;resize:vertical;
  outline:none;line-height:1.6;transition:border-color .15s}
.ed-textarea:focus{border-color:var(--amber);
  box-shadow:0 0 6px rgba(255,208,64,.2)}
.ed-count{font-family:var(--sans);font-size:var(--fs-base);
  color:#fff;text-align:right;padding:.45rem .9rem;
  border-top:1px solid var(--border);background:#111828}
.find-bar{display:flex;align-items:center;gap:.35rem;flex-wrap:wrap;margin-top:.4rem}
.find-inp{flex:1 1 10rem;min-width:0;font-family:var(--sans);font-size:var(--fs-sm);
  padding:.35rem .5rem;background:var(--surface2);color:var(--text-bright);
  border:1px solid var(--border2);border-radius:3px;outline:none}
.find-inp:focus{border-color:var(--amber)}
.find-count{font-family:var(--sans);font-size:var(--fs-base);color:#fff;min-width:5.5rem;text-align:center}
#uf-hdr .find-bar,#allconf-hdr .find-bar{margin-top:0;flex-wrap:nowrap}
#uf-hdr .find-inp,#allconf-hdr .find-inp{flex:0 1 11rem;width:11rem}
#uf-hdr-right{flex-wrap:wrap;justify-content:flex-end}

#ed-action-bar{
  position:fixed;bottom:0;left:0;right:0;
  padding:.65rem .9rem;
  padding-bottom:calc(.65rem + env(safe-area-inset-bottom, 0px));
  display:none;  
  gap:.5rem;align-items:center;
  background:var(--surface);
  border-top:1px solid var(--border2);
  z-index:200}
body.tab-edit #ed-action-bar{display:flex}

body.tab-edit #zone-content{
  padding-bottom:calc(3.8rem + env(safe-area-inset-bottom, 0px))}

#allconf-overlay{display:none;position:fixed;inset:0;
  background:rgba(0,0,0,.8);backdrop-filter:blur(4px);
  z-index:500;align-items:flex-start;justify-content:center;
  padding:1.5rem 1rem}
#allconf-overlay.open{display:flex}
#allconf-box{background:var(--surface);border:1px solid var(--border2);
  border-radius:5px;width:100%;max-width:900px;
  max-height:calc(100vh - 3rem);max-height:calc(100dvh - 3rem);
  display:flex;flex-direction:column;
  box-shadow:0 20px 80px rgba(0,0,0,.9)}
#allconf-hdr{background:linear-gradient(90deg,#0f1a2e,#161e2e 50%,#0f1a2e);
  border-bottom:2px solid var(--teal);padding:.55rem 1rem;
  display:flex;align-items:center;justify-content:space-between;
  flex-shrink:0;box-shadow:0 2px 0 rgba(0,255,229,.15)}
#allconf-title{font-family:var(--sans);font-size:var(--fs-base);
  color:var(--teal);letter-spacing:.08em;
  text-shadow:0 0 8px rgba(0,255,229,.4)}
#allconf-info{font-family:var(--sans);font-size:var(--fs-xs);color:#fff;
  padding:.38rem 1rem;background:#131c2d;
  border-bottom:1px solid var(--border);flex-shrink:0;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#allconf-close{font-family:var(--sans);font-size:var(--fs-base);color:#fff;
  cursor:pointer;padding:.15rem .55rem;border:1px solid var(--border2);
  border-radius:3px;transition:all .14s}
#allconf-close:hover{color:var(--red);border-color:var(--red-dim)}
#allconf-textarea{flex:1;background:#0a1020;color:#ffffff;
  font-family:var(--sans);font-size:var(--fs-base);line-height:1.65;
  border:none;outline:none;padding:.8rem 1rem;
  resize:none;tab-size:4;white-space:pre;overflow:auto;
  min-height:300px}
#allconf-textarea::-webkit-scrollbar{width:4px;height:4px}
#allconf-textarea::-webkit-scrollbar-thumb{background:var(--border2)}

.ed-collapsible-hdr{display:flex;align-items:center;justify-content:space-between;
  cursor:pointer;padding:.65rem .9rem .5rem;
  background:#111828;border-bottom:2px solid var(--border);
  user-select:none;transition:background .14s}
.ed-collapsible-hdr:hover{background:#182030}
.ed-collapsible-title{font-family:var(--sans);font-size:var(--fs-xs);
  letter-spacing:.28em;text-transform:uppercase;color:#fff}
.ed-collapsible-chevron{font-family:var(--sans);font-size:var(--fs-base);
  color:#fff;transition:transform .2s}
.ed-collapsible-hdr.open .ed-collapsible-chevron{transform:rotate(90deg)}
.ed-collapsible-body{overflow:hidden;transition:max-height .25s ease}
.ed-collapsible-body.collapsed{max-height:0 !important}

.tab-vis-row{display:flex;flex-wrap:wrap;gap:.35rem .9rem;padding:.3rem 0 .15rem}
.tab-vis-lbl{font-family:var(--sans);font-size:var(--fs-sm);color:#fff;
  display:inline-flex;align-items:center;gap:.32rem;cursor:pointer;
  user-select:none;white-space:nowrap}
.tab-vis-lbl input[type=checkbox]{accent-color:var(--amber);
  width:14px;height:14px;cursor:pointer}
.tab-vis-lbl.locked{opacity:.55;cursor:default}
.tab-vis-lbl.locked input[type=checkbox]{cursor:default}
.ed-hint{font-family:var(--sans);font-size:var(--fs-xs);
  color:#fff;line-height:1.5;margin-top:.15rem}
.ed-hint.live{color:#fff}  

@media(max-width:600px){
  .ed-grid{grid-template-columns:1fr}
}

#modal-overlay{display:none;position:fixed;inset:0;
  background:rgba(0,0,0,.72);backdrop-filter:blur(3px);
  z-index:900;align-items:center;justify-content:center}
#modal-overlay.open{display:flex}
#modal-box{background:var(--surface);border:1px solid var(--border2);
  border-radius:6px;min-width:320px;max-width:440px;width:90%;
  box-shadow:0 24px 80px rgba(0,0,0,.9);padding:1.5rem 1.5rem 1.1rem}
#modal-msg{font-family:var(--sans);font-size:var(--fs-md);
  color:var(--text-bright);line-height:1.55;margin-bottom:1.2rem}
#modal-btns{display:flex;justify-content:flex-end;gap:.55rem}

.ast-row{display:grid;grid-template-columns:1fr auto;
  align-items:center;gap:.55rem;padding:.42rem .9rem;
  border-top:1px solid var(--border);
  cursor:pointer;transition:background .1s;user-select:none}
.ast-row:hover{background:var(--surface2)}
.ast-name{font-family:var(--sans);font-size:var(--fs-md);
  color:var(--teal);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

.ast-port-line{font-family:var(--sans);font-size:var(--fs-xs);
  color:#fff;padding:.1rem .9rem .1rem 2.2rem;
  border-top:1px solid rgba(255,255,255,.03);
  white-space:pre;overflow:hidden;text-overflow:ellipsis;flex:1}
.ast-port-line:first-child{border-top:none}
.ast-port-lines{border-top:1px solid var(--border);background:#0d1520}
.ast-section-lbl{font-family:var(--sans);font-size:var(--fs-xs);
  letter-spacing:.18em;text-transform:uppercase;
  color:#fff;padding:.28rem .9rem .1rem 1.1rem;
  display:block;user-select:none}

.ast-checks{border-top:1px solid var(--border);background:#0b1622}
.ast-check-row{display:grid;
  grid-template-columns:110px 1fr 52px;
  align-items:center;gap:.4rem;
  padding:.22rem .9rem .22rem 2.2rem;
  border-top:1px solid rgba(255,255,255,.03)}
.ast-check-row:first-child{border-top:none}
.ast-check-title{font-family:var(--sans);font-size:var(--fs-xs);color:#fff}
.ast-check-value{font-family:var(--sans);font-size:var(--fs-sm);
  color:var(--text-bright);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ast-check-pass{font-family:var(--sans);font-size:var(--fs-xs);
  color:var(--green);text-align:center;
  text-shadow:0 0 4px rgba(0,255,176,.4)}
.ast-check-fail{font-family:var(--sans);font-size:var(--fs-xs);
  color:var(--red);text-align:center;
  text-shadow:0 0 4px rgba(255,61,90,.4)}
.ast-check-none{font-family:var(--sans);font-size:var(--fs-xs);
  color:var(--amber);text-align:center;
  text-shadow:0 0 4px rgba(255,208,64,.3)}
.ast-check-info{font-family:var(--sans);font-size:var(--fs-xs);
  color:#fff;text-align:center}
.ast-check-warn{font-family:var(--sans);font-size:var(--fs-xs);
  color:var(--orange);text-align:center;
  text-shadow:0 0 4px rgba(255,170,34,.35)}

.reg-card-status{font-family:var(--sans);font-size:var(--fs-xs);
  font-weight:600;letter-spacing:.06em;text-transform:uppercase;
  padding:.1rem .5rem;border-radius:3px;border:1px solid var(--border2);
  white-space:nowrap}
.reg-card-status.pass{color:var(--green);border-color:var(--green);
  text-shadow:0 0 4px rgba(0,255,176,.4)}
.reg-card-status.fail{color:var(--red);border-color:var(--red);
  text-shadow:0 0 4px rgba(255,61,90,.4)}
.reg-card-status.warn{color:var(--orange);border-color:var(--orange);
  text-shadow:0 0 4px rgba(255,170,34,.35)}
.reg-card-status.info{color:#fff;border-color:var(--border2)}
.reg-live-note{font-family:var(--sans);font-size:var(--fs-xs);color:#fff;
  line-height:1.5;margin:0 0 .6rem}
.reg-live-note code{color:var(--teal)}
.sf-reg{cursor:pointer}

.ph-note{padding:.6rem .9rem;font-family:var(--sans);font-size:var(--fs-sm);color:#ffffff}
.ph-ro{padding:.4rem .9rem;font-family:var(--sans);font-size:var(--fs-xs);color:#ffffff;border-bottom:1px solid var(--border)}
.ph-blk{border-top:1px solid var(--border);padding-bottom:.35rem}
.ph-blk:first-child{border-top:none}
.ph-blk-hdr{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;padding:.45rem .9rem 0;font-family:var(--sans);font-size:var(--fs-sm);font-weight:bold;color:#fff}
.ph-kv{display:grid;grid-template-columns:minmax(110px,32%) 1fr;gap:.18rem .8rem;padding:.35rem .9rem 0;font-family:var(--sans);font-size:var(--fs-sm)}
.ph-kv .k{color:#ffffff;font-size:var(--fs-xs)}
.ph-kv .v{color:#fff;word-break:break-word}
.ph-pre{margin:.3rem .9rem .3rem;padding:.4rem .6rem;background:#0b1622;border:1px solid var(--border);border-radius:3px;font-family:monospace;font-size:var(--fs-xs);color:#ffffff;white-space:pre-wrap;word-break:break-all}
.ph-tbl{width:100%;border-collapse:collapse;font-family:var(--sans);font-size:var(--fs-sm);color:#fff}
.ph-tbl th{text-align:left;font-size:var(--fs-xs);font-weight:normal;color:#ffffff;padding:.3rem .9rem;border-bottom:1px solid var(--border)}
.ph-tbl td{padding:.3rem .9rem;border-top:1px solid var(--border)}
.ph-tbl tr:first-child td{border-top:none}
.ph-link{display:inline-block;text-decoration:none}
.pm-ok{color:var(--green)}
.pm-bad{color:var(--red)}
.pm-warn{color:var(--orange)}
.pm-dim{color:#ffffff}
.pm-btns{display:flex;flex-wrap:wrap;gap:.25rem}
.pm-btns .btn:disabled{opacity:.35;cursor:default}
.ph-sub{padding:.5rem .9rem .1rem;font-family:var(--sans);font-size:var(--fs-xs);letter-spacing:.2em;text-transform:uppercase;color:#ffffff}
.ph-howto{margin:.5rem .9rem;font-family:var(--mono);font-size:var(--fs-xs);color:#ffffff}
.ph-howto summary{cursor:pointer;color:var(--teal)}
.ph-howto p{margin:.35rem 0 0}
.ast-toggle{font-family:var(--sans);font-size:var(--fs-xs);
  background:none;border:1px solid var(--border2);border-radius:3px;
  color:#fff;padding:.1rem .35rem;cursor:pointer;
  transition:all .14s;flex-shrink:0}
.ast-toggle:hover{color:var(--text-bright);border-color:#fff}

.ast-check-note{font-family:var(--sans);font-size:var(--fs-xs);
  color:#fff;padding:.08rem .9rem .14rem 2.2rem}
.ast-check-link{color:var(--teal);text-decoration:none}
.ast-check-link:hover{text-decoration:underline}

.hw-dev-row-hdr{display:flex;align-items:center;gap:.55rem;
  padding:.45rem .9rem;border-top:1px solid var(--border);
  background:var(--surface)}

.hw-section-lbl{font-family:var(--sans);font-size:var(--fs-xs);
  letter-spacing:.22em;text-transform:uppercase;color:#fff;
  padding:.35rem .9rem .28rem;background:#131c2d;
  border-top:1px solid var(--border);border-bottom:1px solid var(--border)}

.hw-dev-info{padding:.55rem .9rem;border-bottom:1px solid var(--border);
  font-family:var(--sans);font-size:var(--fs-base);line-height:2;background:#0f1825}
.hw-dev-row{display:flex;align-items:baseline;gap:.6rem}
.hw-dev-label{color:#fff;font-size:var(--fs-xs);letter-spacing:.15em;
  text-transform:uppercase;min-width:80px;flex-shrink:0}
.hw-dev-val{color:var(--teal)}
.hw-dev-val.sym{color:var(--green)}
.hw-dev-val.dim{color:#fff}

.hw-check-row{display:grid;grid-template-columns:28px 1fr auto;
  align-items:center;gap:.5rem;
  padding:.38rem .9rem;border-top:1px solid var(--border);
  font-family:var(--sans);font-size:var(--fs-base)}
.hw-check-row:first-of-type{border-top:none}
.hw-check-icon{font-size:var(--fs-lg);text-align:center;width:20px;flex-shrink:0}
.hw-check-icon.ok{color:var(--green);text-shadow:0 0 6px rgba(0,255,176,.5)}
.hw-check-icon.fail{color:var(--red);text-shadow:0 0 6px rgba(255,61,90,.5)}
.hw-check-icon.warn{color:var(--amber);text-shadow:0 0 6px rgba(255,208,64,.5)}
.hw-check-icon.pend{color:#fff}
.hw-check-label{color:var(--text-bright);font-size:var(--fs-base)}
.hw-check-detail{font-size:var(--fs-xs);color:#fff;
  text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hw-check-detail.ok{color:var(--green)}
.hw-check-detail.warn{color:var(--amber)}
.hw-check-detail.fail{color:var(--red)}

.hw-compat-section{padding:.45rem .9rem;background:#0b1420;
  border-top:1px solid var(--border)}
.hw-compat-row{display:flex;align-items:center;gap:.7rem;
  padding:.28rem 0;font-family:var(--sans);font-size:var(--fs-base)}
.hw-compat-label{color:#fff;font-size:var(--fs-xs);letter-spacing:.12em;
  text-transform:uppercase;min-width:90px;flex-shrink:0}
.hw-compat-ok{color:var(--green);text-shadow:0 0 6px rgba(0,255,176,.4)}
.hw-compat-fail{color:var(--red);font-size:var(--fs-sm)}
.hw-compat-warn{color:var(--amber);font-size:var(--fs-sm)}
.hw-compat-reason{color:#fff;font-size:var(--fs-xs);margin-left:.3rem}

.hw-card-footer{display:flex;align-items:center;gap:.5rem;
  padding:.4rem .9rem;background:#111828;
  border-top:2px solid var(--border2)}

.hw-multi-warn{display:flex;align-items:center;gap:.55rem;
  padding:.35rem .9rem;background:#1a1200;
  border-bottom:1px solid var(--amber-dim);
  font-family:var(--sans);font-size:var(--fs-sm);color:var(--amber)}

.hw-gear-btn{font-family:var(--sans);font-size:var(--fs-sm);color:#fff;
  border:1px solid var(--border2);border-radius:3px;
  padding:.15rem .45rem;background:transparent;cursor:pointer;
  transition:all .14s;flex-shrink:0}
.hw-gear-btn:hover{color:var(--teal);border-color:var(--teal-dim)}
.hw-gear-btn.open{color:var(--teal);border-color:var(--teal-dim);
  background:rgba(0,255,229,.07)}

.hw-action-zone{border-top:2px solid var(--border2);background:#0d1520;
  overflow:hidden;max-height:0;transition:max-height .22s ease}
.hw-action-zone.open{max-height:600px}
.hw-action-sub{padding:.55rem .9rem .45rem;
  border-bottom:1px solid var(--border)}
.hw-action-sub:last-child{border-bottom:none}
.hw-action-sub-title{font-family:var(--sans);font-size:var(--fs-xs);
  letter-spacing:.2em;text-transform:uppercase;
  color:#fff;margin-bottom:.4rem}
.hw-action-row{display:flex;align-items:center;gap:.4rem;
  flex-wrap:wrap;margin-top:.35rem}
.hw-action-inp{font-family:var(--sans);font-size:var(--fs-base);
  padding:.25rem .5rem;background:var(--surface2);
  color:var(--text-bright);border:1px solid var(--border2);
  border-radius:3px;outline:none;width:160px;transition:border-color .15s}
.hw-action-inp:focus{border-color:var(--teal);
  box-shadow:0 0 6px rgba(0,255,229,.2)}
.hw-action-inp::placeholder{color:#fff}
.hw-action-sel{font-family:var(--sans);font-size:var(--fs-base);
  padding:.25rem .45rem;background:var(--surface2);
  color:var(--text-bright);border:1px solid var(--border2);
  border-radius:3px;cursor:pointer;outline:none}
.hw-action-sel option{background:var(--surface2)}
.hw-action-note{font-family:var(--sans);font-size:var(--fs-xs);
  color:#fff;margin-top:.4rem;line-height:1.6}
.hw-symlink-hint{font-family:var(--sans);font-size:var(--fs-xs);
  color:#fff;margin-top:.25rem}
.hw-symlink-hint span{color:var(--teal)}

.hw-ping-result{font-family:var(--sans);font-size:var(--fs-sm);
  margin-left:.5rem;padding:.2rem .5rem;border-radius:3px;
  border:1px solid var(--border2);color:#fff;display:none}
.hw-ping-result.ok{color:var(--green);border-color:var(--green-dim);
  background:rgba(0,255,176,.06);display:inline-block}
.hw-ping-result.fail{color:var(--red);border-color:var(--red-dim);
  background:rgba(255,61,90,.06);display:inline-block}

.hw-reset-chip-btn{
  font-family:var(--sans);font-size:var(--fs-base);font-weight:bold;
  letter-spacing:.04em;padding:.28rem .75rem;border-radius:4px;
  border:1px solid var(--orange);cursor:pointer;
  color:#0d1117;background:var(--orange);
  box-shadow:0 0 8px rgba(255,170,34,.45);
  transition:box-shadow .15s,opacity .15s,transform .1s}
.hw-reset-chip-btn:hover:not(:disabled){
  box-shadow:0 0 16px rgba(255,170,34,.75);transform:translateY(-1px)}
.hw-reset-chip-btn:active:not(:disabled){transform:translateY(0)}
.hw-reset-chip-btn:disabled{
  opacity:.38;cursor:not-allowed;box-shadow:none;transform:none}

.hw-reset-status{font-family:var(--sans);font-size:var(--fs-xs);
  margin-left:.55rem;padding:.2rem .5rem;border-radius:3px;
  border:1px solid var(--border2);color:#fff;display:none}
.hw-reset-status.ok{color:var(--green);border-color:var(--green-dim);
  background:rgba(0,255,176,.06);display:inline-block}
.hw-reset-status.warn{color:var(--amber);border-color:var(--amber-dim);
  background:rgba(255,208,64,.06);display:inline-block}
.hw-reset-status.fail{color:var(--red);border-color:var(--red-dim);
  background:rgba(255,61,90,.06);display:inline-block}

.hw-badge{font-family:var(--sans);font-size:var(--fs-xs);letter-spacing:.1em;
  padding:.1rem .45rem;border-radius:3px;border:1px solid;
  flex-shrink:0;white-space:nowrap}
.hw-badge-ambe{color:var(--teal);border-color:var(--teal-dim);
  background:rgba(0,255,229,.07)}
.hw-badge-serial{color:var(--amber);border-color:var(--amber-dim);
  background:rgba(255,208,64,.07)}
.hw-badge-audio{color:var(--blue);border-color:var(--blue-dim);
  background:rgba(34,212,255,.07)}
.hw-badge-watchdog{color:#fff;border-color:var(--border2)}

.hw-compat-note{font-family:var(--sans);font-size:var(--fs-xs);color:#fff;
  padding:.25rem 0;border-top:1px solid var(--border);margin-top:.3rem}

.hw-remove-btn{display:none}
.hw-remove-btn.visible{display:inline-block}

.hw-source-tag{font-family:var(--sans);font-size:var(--fs-xs);
  color:#fff;letter-spacing:.1em}
@media(max-width:600px){
  .hw-dev-label{min-width:60px}
  .hw-compat-label{min-width:70px}
  .hw-check-detail{display:none}
  .hw-action-inp{width:130px}
}

#uf-overlay{display:none;position:fixed;inset:0;
  background:rgba(0,0,0,.8);backdrop-filter:blur(4px);
  z-index:500;align-items:center;justify-content:center;
  padding:0}
#uf-overlay.open{display:flex}

#uf-box{background:var(--surface);border:1px solid var(--border2);
  border-radius:0;width:100vw;height:100vh;max-width:none;max-height:100vh;
  height:100dvh;max-height:100dvh;  
  display:flex;flex-direction:column;box-shadow:none}

#uf-hdr{background:linear-gradient(90deg,#0f1a2e,#161e2e 50%,#0f1a2e);
  border-bottom:2px solid var(--teal);padding:.55rem 1rem;
  display:flex;align-items:center;justify-content:space-between;
  flex-shrink:0;box-shadow:0 2px 0 rgba(0,255,229,.15);
  position:sticky;top:0;z-index:501}
#uf-title{font-family:var(--sans);font-size:var(--fs-base);
  color:var(--teal);letter-spacing:.08em;
  text-shadow:0 0 8px rgba(0,255,229,.4)}
#uf-hdr-right{display:flex;align-items:center;gap:.4rem}
#uf-close{font-family:var(--sans);font-size:var(--fs-base);color:#fff;
  cursor:pointer;padding:.15rem .55rem;border:1px solid var(--border2);
  border-radius:3px;transition:all .14s}
#uf-close:hover{color:var(--red);border-color:var(--red-dim)}

#uf-promoted-bar{display:none;background:rgba(255,208,64,.08);
  border-bottom:1px solid var(--amber-dim);
  padding:.35rem 1rem;font-family:var(--sans);font-size:var(--fs-xs);
  color:var(--amber);flex-shrink:0;position:sticky;top:2.5rem;z-index:500}
#uf-promoted-bar.show{display:block}

#uf-toolbar{display:flex;align-items:center;gap:.4rem;
  padding:.38rem 1rem;background:#131c2d;
  border-bottom:1px solid var(--border);flex-shrink:0;
  position:sticky;top:2.5rem;z-index:500}
#uf-path{font-family:var(--sans);font-size:var(--fs-xs);
  color:#fff;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#uf-status{font-family:var(--sans);font-size:var(--fs-sm);color:#fff}

#uf-textarea{flex:1;background:#0a1020;color:#ffffff;
  font-family:var(--sans);font-size:var(--fs-base);line-height:1.65;
  border:none;outline:none;padding:3.5rem 1rem .8rem 1rem;
  resize:none;tab-size:4;white-space:pre;overflow:auto;
  min-height:0}
#uf-textarea::-webkit-scrollbar{width:4px;height:4px}
#uf-textarea::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}

.dvsm-tab-hdr{display:flex;align-items:center;justify-content:space-between;
  margin-bottom:.75rem;padding:.1rem 0}
.dvsm-tab-title{font-family:var(--sans);font-size:var(--fs-sm);letter-spacing:.22em;
  text-transform:uppercase;color:#fff}
.dvsm-tab-hdr-right{display:flex;align-items:center;gap:.55rem}
.dvsm-node-ip-lbl{font-family:var(--sans);font-size:var(--fs-xs);color:#fff}

.dvsm-grid{display:grid;grid-template-columns:1fr 1fr;gap:.65rem;margin-bottom:.65rem}
@media(max-width:800px){.dvsm-grid{grid-template-columns:1fr}}

.dvsm-accent{width:3px;height:1.15rem;border-radius:2px;flex-shrink:0}

.dvsm-card-title{font-family:var(--sans);font-size:var(--fs-base);font-weight:bold;
  letter-spacing:.06em;text-transform:uppercase}
.dvsm-card-sub{font-family:var(--sans);font-size:var(--fs-xs);color:#fff;
  letter-spacing:.1em;margin-top:.06rem}

.dvsm-fields{width:100%;border-collapse:collapse}
.dvsm-fields tr{border-top:1px solid rgba(255,255,255,.04)}
.dvsm-fields tr:first-child{border-top:none}
.dvsm-fields td{padding:.28rem .9rem;vertical-align:middle}
.dvsm-lbl{font-family:var(--sans);font-size:var(--fs-xs);color:#fff;
  letter-spacing:.1em;text-transform:uppercase;width:110px;white-space:nowrap}

.dvsm-val-cell{word-break:break-word;min-width:0}
.dvsm-val{font-family:var(--sans);font-size:var(--fs-base);color:var(--text-bright)}
.dvsm-val.masked{letter-spacing:.14em;color:#fff}
.dvsm-val.placeholder{color:#fff;font-style:italic}
.dvsm-actions{text-align:right;width:58px;white-space:nowrap}

.dvsm-copy,.dvsm-eye{font-family:var(--sans);font-size:var(--fs-xs);
  padding:.1rem .35rem;border-radius:2px;
  border:1px solid var(--border);background:transparent;
  color:#fff;cursor:pointer;transition:all .12s;margin-left:2px}
.dvsm-copy:hover{color:var(--teal);border-color:var(--teal-dim)}
.dvsm-eye:hover{color:var(--amber);border-color:var(--amber-dim)}
.dvsm-copy.copied{color:var(--green);border-color:var(--green-dim)}
.dvsm-eye.revealed{color:var(--amber);border-color:var(--amber-dim)}

.dvsm-note{background:#0a1220;border-top:1px solid rgba(255,208,64,.14);
  padding:.32rem .9rem;font-family:var(--sans);font-size:var(--fs-xs);line-height:1.5}
.dvsm-note.warn{color:var(--amber);border-top-color:rgba(255,208,64,.14)}
.dvsm-note.info{color:var(--teal);border-top-color:rgba(0,255,229,.12)}
.dvsm-note.err{color:var(--red);border-top-color:rgba(255,61,90,.12)}
.dvsm-note.src{color:#fff;font-size:var(--fs-xs);
  border-top-color:rgba(255,255,255,.05)}

.dvsm-sec-lbl{display:block;font-family:var(--sans);font-size:var(--fs-xs);
  letter-spacing:.2em;text-transform:uppercase;color:#fff;
  padding:.3rem .9rem .18rem;background:#0a1220;
  border-top:1px solid var(--border)}
.dvsm-sec-lbl:first-child{border-top:none}

.dvsm-compat-tbl{width:100%;border-collapse:collapse}
.dvsm-compat-tbl tr{border-top:1px solid rgba(255,255,255,.04)}
.dvsm-compat-tbl tr:first-child{border-top:none}
.dvsm-compat-tbl td{padding:.3rem .9rem;vertical-align:middle;
  font-family:var(--sans);font-size:var(--fs-sm)}
.dvsm-ct-key{color:var(--blue);width:230px}

.dvsm-ct-enables{color:#fff}
.dvsm-ct-badge{text-align:right;width:58px}

.dvsm-ct-fix-row{border-top:none}
.dvsm-ct-fix{color:#fff;font-size:var(--fs-xs);
  padding:.05rem .9rem .3rem 2.5rem;border-top:none!important}

.stfu-tab-hdr{display:flex;align-items:center;justify-content:space-between;
  margin-bottom:.75rem;padding:.1rem 0}
.stfu-tab-title{font-family:var(--sans);font-size:var(--fs-sm);letter-spacing:.22em;
  text-transform:uppercase;color:#fff}

.stfu-bm-bar{display:flex;flex-wrap:wrap;gap:.35rem .6rem;align-items:center;justify-content:space-between;
  padding:.42rem .9rem;
  background:linear-gradient(90deg,rgba(0,191,255,.06),rgba(0,191,255,.03));
  border-bottom:1px solid rgba(0,191,255,.15)}
.stfu-bm-bar-left{display:flex;flex-wrap:wrap;align-items:center;gap:.55rem}
.stfu-bm-label{font-family:var(--sans);font-size:var(--fs-sm);
  color:#fff;letter-spacing:.06em}
.stfu-bm-link{font-family:var(--sans);font-size:var(--fs-sm);color:var(--blue);
  text-decoration:none;letter-spacing:.04em;
  text-shadow:0 0 8px rgba(0,191,255,.4);transition:all .15s}
.stfu-bm-link:hover{color:#fff;text-shadow:0 0 14px rgba(0,191,255,.9)}
.stfu-bm-pill{font-family:var(--sans);font-size:var(--fs-xs);letter-spacing:.14em;
  text-transform:uppercase;padding:.1rem .42rem;border-radius:2px;
  border:1px solid var(--blue-dim);color:var(--blue);
  background:rgba(0,191,255,.07)}

.stfu-sample-hdr{padding:.38rem .9rem;display:flex;align-items:center;
  justify-content:space-between;border-bottom:1px solid var(--border);
  background:#131c2d}
.stfu-sample-title{font-family:var(--sans);font-size:var(--fs-sm);color:#fff;
  letter-spacing:.12em;text-transform:uppercase}
.stfu-sample-btns{display:flex;gap:.4rem;align-items:center}

.stfu-code{font-family:var(--sans);font-size:var(--fs-base);line-height:1.7;
  color:#ffffff;padding:.7rem .9rem;background:#080e18;
  margin:0;white-space:pre;overflow-x:auto;display:block}
.stfu-ini-section{color:var(--blue)}
.stfu-ini-key{color:var(--teal)}
.stfu-ini-ph{color:#fff;font-style:italic}   

.stfu-editor-wrap{overflow:hidden;transition:max-height .3s ease;max-height:0}
.stfu-editor-wrap.open{max-height:600px}
#stfu-textarea{width:100%;background:#0a1020;color:#ffffff;
  font-family:var(--sans);font-size:var(--fs-base);line-height:1.65;
  border:none;outline:none;padding:.8rem 1rem;
  resize:none;tab-size:4;white-space:pre;overflow:auto;
  min-height:260px;display:block}
.stfu-editor-bar{display:flex;flex-wrap:wrap;align-items:center;gap:.4rem;
  padding:.38rem .9rem;background:#131c2d;border-top:1px solid var(--border)}

.hw-pwr-tbl{width:100%;border-collapse:collapse}
.hw-pwr-tbl tr{border-top:1px solid rgba(255,255,255,.04)}
.hw-pwr-tbl tr:first-child{border-top:none}
.hw-pwr-tbl td{padding:.28rem .9rem;vertical-align:middle;
  font-family:var(--sans);font-size:var(--fs-base)}
.hw-pwr-lbl{color:#fff;font-size:var(--fs-xs);letter-spacing:.1em;
  text-transform:uppercase;width:140px;white-space:nowrap}
.hw-pwr-val{color:var(--text-bright)}
.hw-pwr-val.ok{color:var(--green);text-shadow:0 0 6px rgba(0,255,176,.35)}
.hw-pwr-val.warn{color:var(--amber)}
.hw-pwr-val.hot{color:var(--red);text-shadow:0 0 6px rgba(255,61,90,.35)}
.hw-pwr-val.dim{color:#fff;font-style:italic}
.hw-vid-opt{display:flex;align-items:flex-start;gap:.55rem;padding:.45rem .9rem;
  font-family:var(--sans);font-size:var(--fs-sm);color:var(--text-bright);cursor:pointer}
.hw-vid-opt input[type=checkbox]{accent-color:var(--amber);margin-top:.2rem;cursor:pointer}
.hw-vid-opt.disabled{opacity:.55;cursor:default}
.hw-vid-pend{display:inline-block;margin-left:.4rem;padding:0 .4rem;border-radius:3px;
  font-size:var(--fs-xs);color:#000;background:var(--amber);font-weight:bold}
.hw-vid-refs{margin:.3rem .9rem .5rem;font-family:var(--mono);font-size:var(--fs-xs);
  color:var(--amber);white-space:pre-wrap;word-break:break-all}
.hw-vid-actions{display:flex;gap:.4rem;padding:.3rem .9rem .6rem}
.hw-pwr-note{font-size:var(--fs-xs);color:#fff;
  display:block;margin-top:.08rem;line-height:1.4}

.hw-pwr-flags{display:flex;flex-wrap:wrap;gap:.25rem .5rem;
  padding:.32rem .9rem .42rem;background:#080e18;
  border-top:1px solid var(--border)}
.hw-pwr-flag{font-family:var(--sans);font-size:var(--fs-xs);
  padding:.08rem .38rem;border-radius:2px;border:1px solid;white-space:nowrap}
.hw-pwr-flag.set-now{color:var(--red);border-color:var(--red-dim);
  background:rgba(255,61,90,.08)}
.hw-pwr-flag.set-ever{color:var(--amber);border-color:var(--amber-dim);
  background:rgba(255,208,64,.06)}
.hw-pwr-flag.clear{color:#ffffff;border-color:#1a2a40}

.hw-diag-pre{font-family:var(--sans);font-size:var(--fs-xs);line-height:1.5;
  color:var(--text);background:#080e18;padding:.6rem .9rem;margin:0;
  overflow-x:auto;white-space:pre;border-top:1px solid var(--border);
  max-height:340px;overflow-y:auto}
.hw-diag-toggle{padding:.18rem .5rem;font-size:var(--fs-xs);letter-spacing:.06em}
.hw-diag-toggle.active{color:var(--teal);border-color:var(--teal);
  background:rgba(0,255,229,.08)}
.hw-diag-note{font-family:var(--sans);font-size:var(--fs-xs);color:#fff;
  padding:.35rem .9rem;border-top:1px solid var(--border);line-height:1.5}
.hw-usb-badge{font-family:var(--sans);font-size:var(--fs-xs);padding:.04rem .32rem;
  border-radius:2px;border:1px solid;margin-left:.4rem;white-space:nowrap;
  vertical-align:middle}
.hw-usb-badge.ambe{color:var(--green);border-color:var(--green-dim)}
.hw-usb-badge.ftdi{color:var(--amber);border-color:var(--amber-dim)}

.ast-toggle.on{color:var(--text-bright);border-color:var(--teal)}

#login-screen,#login{flex-direction:column;gap:18px;padding:40px 16px 56px}
.welcome{font-size:1.1rem;font-weight:700;color:var(--text-bright);letter-spacing:.02em;text-wrap:balance;max-width:44ch}
.welcome b{color:var(--amber);font-weight:700;text-shadow:0 0 12px rgba(255,208,64,.5)}
.splash-license{position:absolute;left:0;right:0;bottom:14px;text-align:center;font-size:var(--fs-xs);letter-spacing:.04em;color:var(--muted)}
.splash-license a{color:var(--blue)}
.hdr-logout{font-family:var(--sans);font-size:var(--fs-sm);color:var(--muted);background:transparent;border:1px solid var(--border2);border-radius:5px;padding:.2rem .5rem;cursor:pointer}
</style>
</head>
<body>

<div id="login-screen">
  <div class="welcome">Welcome to the <b>KD8PGK</b> System Monitor</div>
  <div class="splash-license">System Monitor · <a href="https://creativecommons.org/licenses/by-nc/4.0/" target="_blank" rel="noopener">CC BY-NC 4.0</a></div>
  <div id="login-card">
    <h2>System Monitor</h2>
    <p class="sub">Sign in with this node's root password.</p>
    <form onsubmit="_doLogin(event)">
      <label for="login-pw">Root password</label>
      <input id="login-pw" type="password" autocomplete="current-password" required>
      <button id="login-btn" type="submit">Log In</button>
      <div id="login-err"></div>
    </form>
  </div>
</div>

<div id="offline-bar">SERVER UNREACHABLE — retrying…</div>
<div id="restart-banner">⚠ Restart sysmon to apply server address changes</div>

<header>
  <div>
    <div class="logo">System Monitor</div>
    <div class="logo-sub">
      <span id="hdr-callsign">KD8PGK</span>
      <span style="color:#6b4800"> · </span>
      <span>Node </span><span id="hdr-node">…</span>
    </div>
  </div>
  <div id="hdr-right">
    <span id="hdr-uptime">UP 0:00:00</span>
    <button class="hdr-logout" onclick="doLogout()">Log Out</button>
    <span id="hdr-version">v__VERSION__</span>
  </div>
</header>

<div id="ql-bar">
  <a id="lnk-allmon3" class="ql-btn" href="http://localhost:8080/" target="_blank" rel="noopener"
     title="Allmon3 web monitor">Allmon3</a>
  <a id="lnk-dvswitch" class="ql-btn" href="/dvswitch" target="_blank" rel="noopener"
     title="DVSwitch dashboard">DVSwitch</a>
  <a id="lnk-cockpit" class="ql-btn" href="http://localhost:9090/" target="_blank" rel="noopener"
     title="Cockpit admin UI">Cockpit</a>
  <a id="lnk-m17" class="ql-btn" href="/m17" target="_blank" rel="noopener"
     title="USRP2M17">USRP2M17</a>
  <a id="lnk-wifimon" class="ql-btn" href="http://localhost:8991/" target="_blank" rel="noopener"
     title="WifiMon">WifiMon</a>
  <a id="lnk-dashboard" class="ql-btn" href="http://localhost:8989/" 
     title="Return to ASL-DVS Dashboard" target="_self" onclick="pauseAllPolling()">Node Controller</a>
</div>

<div id="zone-status">
  <div class="sf"><span class="sl">Host</span><span class="sv cyan" id="s-host">…</span></div>
  <div class="sf"><span class="sl">Load</span><span class="sv" id="s-load">…</span></div>
  <div class="sf"><span class="sl">Mem</span><span class="sv" id="s-mem">…</span></div>
  <div class="sf sf-temp"><span class="sl">Temp</span><span class="sv" id="s-temp">—</span></div>
  <div class="sf"><span class="sl">Pwr</span><span class="sv" id="s-volt" title="Power health — vcgencmd get_throttled">—</span></div>
  <div class="sf sf-reg" id="sf-reg" onclick="regJump()"><span class="sl">ASL</span><span class="sv" id="s-reg" title="AllStarLink registration — rpt show registrations">…</span></div>
</div>

<div id="zone-cmdbar">
  
  <button class="tab-btn active" id="tbtn-overview"
    onclick="switchTab('overview','0,255,229')">Overview</button>
  <button class="tab-btn"        id="tbtn-services"
    onclick="switchTab('services','0,255,229')">Services</button>
  <button class="tab-btn"        id="tbtn-ports"
    onclick="switchTab('ports','34,212,255')">Ports</button>
  <button class="tab-btn"        id="tbtn-journal"
    onclick="switchTab('journal','212,102,255')">Journal</button>
  <button class="tab-btn"        id="tbtn-asldvs"
    onclick="switchTab('asldvs','255,61,90')">ASL-DVS</button>
  <button class="tab-btn"        id="tbtn-reg"
    onclick="switchTab('reg','120,180,255')">Reg</button>
  <button class="tab-btn"        id="tbtn-phone"
    onclick="switchTab('phone','0,255,176')">Phone</button>
  <button class="tab-btn"        id="tbtn-tune"
    onclick="switchTab('tune','255,68,204')">Tune</button>
  <button class="tab-btn"        id="tbtn-hardware"
    onclick="switchTab('hardware','0,200,120')">Hardware</button>
  <button class="tab-btn"        id="tbtn-dvsm"
    onclick="switchTab('dvsm','255,170,34')">DVSM</button>
  <button class="tab-btn"        id="tbtn-stfu"
    onclick="switchTab('stfu','0,191,255')">STFU</button>
  <button class="tab-btn"        id="tbtn-m17"
    onclick="switchTab('m17','124,255,60')">M17</button>
  <button class="tab-btn"        id="tbtn-sdcard"
    onclick="switchTab('sdcard','180,140,255')">SD Card</button>
  <button class="tab-btn"        id="tbtn-edit"
    onclick="switchTab('edit','255,208,64')">Edit</button>
  <div class="cmdbar-spacer"></div>
  
  <div style="flex-basis:100%;height:0"></div>
  
  <span style="font-size:var(--fs-base);color:#fff;font-weight:500;margin-right:.4rem">Radio:</span>
  <button class="radio-btn empty" id="radio-btn-1" onclick="applyRadioPreset(1)" title="Apply Radio 1 preset">Radio 1</button>
  <button class="radio-btn empty" id="radio-btn-2" onclick="applyRadioPreset(2)" title="Apply Radio 2 preset">Radio 2</button>
  <button class="radio-btn empty" id="radio-btn-3" onclick="applyRadioPreset(3)" title="Apply Radio 3 preset">Radio 3</button>
  <button class="radio-btn empty" id="radio-btn-4" onclick="applyRadioPreset(4)" title="Apply Radio 4 preset">Radio 4</button>
  <button class="radio-btn empty" id="radio-btn-5" onclick="applyRadioPreset(5)" title="Apply Radio 5 preset">Radio 5</button>
  
  <div class="cmdbar-spacer"></div>
  <button class="btn btn-muted btn-sm" onclick="pollStatus()">↻ Refresh</button>
  <button class="btn btn-amber btn-sm"
    onclick="postAction('/api/reboot','reboot',this,'⟳ Reboot this machine?')">⟳ Reboot</button>
  <button class="btn btn-red btn-sm"
    onclick="postAction('/api/shutdown','shutdown',this,'⏻ Shut down this machine?')">⏻ Shutdown</button>
  <button class="btn btn-muted btn-sm" onclick="doLogout()" title="Log out">⎋ Logout</button>
</div>

<div id="zone-content">

  <div id="panel-overview" class="tab-panel active">
    __SVC_LEGEND__
    <div id="ov-content">
      
      <div class="stub-panel" id="ov-loading">Loading overview…</div>
      <div id="ov-global-bar">
        <span id="ov-global-lbl">Global Actions</span>
        <div style="flex:1"></div>
        <button class="btn btn-muted btn-sm"
          onclick="dtCopy(this, ovText)" title="Copy the overview as text">⎘ Copy</button>
        <button class="btn btn-red btn-sm"
          onclick="svcGlobal('stop_all',this)">■ Stop All</button>
        <button class="btn btn-blue btn-sm"
          onclick="svcGlobal('restart_all',this)">↺ Restart All</button>
      </div>
    </div>
  </div>

  <div id="panel-services" class="tab-panel">

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Services</span>
        <button class="btn btn-muted btn-sm" style="margin-left:auto"
          onclick="dtCopy(this, svcText)" title="Copy this list as text">⎘ Copy</button>
      </div>
      __SVC_LEGEND__
      <div class="s3-controls">
        <button class="s3-scope on" id="s3-btn-active"
          onclick="s3SetScope('active')">Active</button>
        <button class="s3-scope"   id="s3-btn-all"
          onclick="s3SetScope('all')">All</button>
        <input  class="s3-filter"  id="s3-filter" type="text"
          placeholder="filter by name…"
          oninput="s3FilterChanged()">
      </div>
      <div id="s3-gen-body">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>

  </div>

  <div id="panel-ports" class="tab-panel">
    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Open Ports</span>
        <span class="s3-card-meta" id="pt-refresh-ts">auto-refresh 15s</span>
      </div>
      <div class="pt-controls">
        <button class="pt-proto-btn on" id="pt-btn-both"
          onclick="ptSetProto('both')">All</button>
        <button class="pt-proto-btn"    id="pt-btn-tcp"
          onclick="ptSetProto('tcp')">TCP</button>
        <button class="pt-proto-btn"    id="pt-btn-udp"
          onclick="ptSetProto('udp')">UDP</button>
        <span style="flex:1"></span>
        <button class="btn btn-muted btn-sm" onclick="ptCopy(this,false)"
          title="Copy the table (current filter) as text, full desktop layout">⎘ Copy table</button>
        <button class="btn btn-muted btn-sm" onclick="ptCopy(this,true)"
          title="Copy every open port, TCP and UDP, as text">⎘ Copy all</button>
      </div>
      <div class="dot-legend">
        <span class="dot-legend-item"><span class="dot dot-on"></span>Known Service</span>
        <span class="dot-legend-item"><span class="dot dot-off"></span>Unknown Listener</span>
      </div>
      <div class="pt-legend">
        OK/DUP shows whether more than one process is bound to that port+protocol —
        not a health check on the service itself.
      </div>
      <div class="pt-table-hdr">
        <span></span><span>Port</span><span>Proto</span><span>Process</span>
        <span>PID</span><span>Known Service</span><span>Conflict</span>
      </div>
      <div id="pt-body">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>
  </div>

  <div id="panel-journal" class="tab-panel">
    <div class="s3-card" id="dvl-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">DV Gateway Logs</span>
        <span class="s3-card-meta">files in UTC · journal in local time</span>
      </div>
      <div class="dvl-agent">
        <button class="btn btn-purple btn-sm" id="dvl-agent-btn"
          onclick="dvlAgentCopy()">⎘ Copy for agent</button>
        <button class="btn btn-muted btn-sm" onclick="dvlAgentDownload()">⤓ Download .txt</button>
        <button class="btn btn-muted btn-sm" onclick="dvlLoad()">↻ Refresh</button>
        <span class="dvl-agent-note" id="dvl-agent-note">The last 50 lines of every log below,
          plus this boot's warnings. Copy one log at a time with its own Copy button.</span>
      </div>
      <div id="dvl-body">
        <div class="stub-panel" style="min-height:60px">Loading…</div>
      </div>
    </div>
    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Running Services — click to view journal</span>
        <span class="s3-card-meta">pinned + active</span>
      </div>
      __SVC_LEGEND__
      <div class="jl-table-hdr">
        <span></span><span>Service</span><span>Active</span><span></span>
      </div>
      <div id="jl-body">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>
  </div>

  <div id="panel-asldvs" class="tab-panel">
    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">/etc/asterisk/ — Config Files</span>
        <span class="s3-card-meta">click row → edit</span>
      </div>
      <div id="ast-file-body">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Allmon3 — Config Files</span>
        <span class="s3-card-meta">click row → edit</span>
      </div>
      <div id="allmon3-file-body">
        <div class="stub-panel" style="min-height:60px">Loading…</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">DVSwitch — Config Files</span>
        <span class="s3-card-meta">click row → edit</span>
      </div>
      <div id="dvs-file-body">
        <div class="stub-panel" style="min-height:60px">Loading…</div>
      </div>
    </div>

    <div class="s3-card" id="dstargw-card">
      <div class="s3-card-hdr" style="padding-left:.6rem">
        <div style="display:flex;align-items:center;gap:.55rem">
          <div class="dvsm-accent" style="background:var(--blue)"></div>
          <div>
            <div class="dvsm-card-title" style="color:var(--blue)">D-Star — ircDDBGateway</div>
            <div class="dvsm-card-sub">/etc/ircddbgateway · gateway linking · remote control</div>
          </div>
        </div>
        <span class="dpbadge" id="dstargw-badge">—</span>
      </div>
      <div id="dstargw-body">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
      <div style="padding:.5rem .6rem;border-top:1px solid rgba(255,255,255,.06);display:flex;gap:.4rem;flex-wrap:wrap">
        <button class="btn btn-sm" style="color:var(--blue);border-color:var(--blue-dim)"
          onclick="dstarGwEdit()">✎ Edit /etc/ircddbgateway</button>
        <button class="btn btn-sm" style="color:var(--green);border-color:var(--green-dim)"
          onclick="dstarGwRestart()">↺ Restart ircddbgatewayd</button>
        <button class="btn btn-blue btn-sm" onclick="loadDstarGw()">↻ Refresh</button>
        <button class="btn btn-muted btn-sm" onclick="dstarGwCopy(this)" title="Copy this card as text">⎘ Copy</button>
      </div>
    </div>

    <div class="s3-card" id="nodelisten-card">
      <div class="s3-card-hdr" style="padding-left:.6rem">
        <div style="display:flex;align-items:center;gap:.55rem">
          <div class="dvsm-accent" style="background:var(--teal)"></div>
          <div>
            <div class="dvsm-card-title" style="color:var(--teal)">Node Talker</div>
            <div class="dvsm-card-sub" id="nodelisten-sub">listen ports · connections · push-to-talk node 1921</div>
          </div>
        </div>
        <span class="dpbadge" id="nodelisten-badge">—</span>
      </div>
      <div id="nodelisten-body">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
      <div id="nodelisten-clients"></div>
      <div id="nodelisten-actions" style="padding:.5rem .6rem;border-top:1px solid rgba(255,255,255,.06);display:flex;gap:.4rem;flex-wrap:wrap">
        <button class="btn btn-sm" style="color:var(--green);border-color:var(--green-dim)"
          onclick="nodeListenRestart()">↺ Restart Node Talker</button>
        <button class="btn btn-sm" id="nodelisten-unlink" style="color:var(--amber);border-color:var(--amber-dim)"
          onclick="nodeListenUnlink()">⨯ Unlink 1921</button>
        <a class="btn btn-sm" id="nodelisten-open" style="color:var(--teal);border-color:var(--teal-dim);text-decoration:none"
          href="#" target="_blank" rel="noopener">↗ Open Node Talker</a>
        <button class="btn btn-blue btn-sm" onclick="loadNodeListen()">↻ Refresh</button>
        <button class="btn btn-muted btn-sm" onclick="nodeListenCopy(this)" title="Copy this card as text">⎘ Copy</button>
      </div>
    </div>

  </div>

  <div id="panel-reg" class="tab-panel">

    <div class="reg-live-note" id="reg-live-note">Live state from <code>rpt show registrations</code>, checked every 10 s until the node registers, then every 30 s. This tab refreshes every 15 s while open.</div>

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">HTTP Registration</span>
        <span class="reg-card-status" id="reg-http-status">—</span>
        <span class="s3-card-meta" id="reg-http-meta">—</span>
        <div style="display:flex;gap:.3rem;margin-left:auto">
          <button class="btn btn-muted btn-sm" id="reg-http-refresh"
                  onclick="loadTab_reg()">↻ Re-check</button>
        </div>
      </div>
      <div id="reg-http-body">
        <div class="stub-panel" style="min-height:60px">Loading…</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">IAX Registration</span>
        <span class="reg-card-status" id="reg-iax-status">—</span>
        <span class="s3-card-meta" id="reg-iax-meta">—</span>
        <div style="display:flex;gap:.3rem;margin-left:auto">
          <button class="btn btn-muted btn-sm" id="reg-iax-refresh"
                  onclick="loadTab_reg()">↻ Re-check</button>
        </div>
      </div>
      <div id="reg-iax-body">
        <div class="stub-panel" style="min-height:60px">Loading…</div>
      </div>
    </div>

  </div>

  <div id="panel-phone" class="tab-panel">

    <div class="ph-ro">Read-only view of what Asterisk is set up to do for autopatch. Change phone settings in the ASL-DVS Dashboard → Edit → Phone. The one exception is the Autopatch modules card, which can load, stop and set modules.</div>

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Live</span>
        <span class="reg-card-status" id="ph-live-status">—</span>
        <span class="s3-card-meta" id="ph-live-meta">—</span>
        <div style="display:flex;gap:.3rem;margin-left:auto">
          <button class="btn btn-muted btn-sm" onclick="phCopyCard('live')" title="Copy this card as text">⎘ Copy</button>
          <button class="btn btn-muted btn-sm" onclick="loadTab_phone()">↻ Re-check</button>
        </div>
      </div>
      <div id="ph-live-body"><div class="stub-panel" style="min-height:60px">Loading…</div></div>
    </div>
    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Autopatch node</span>
        <span class="reg-card-status" id="ph-node-status">—</span>
        <span class="s3-card-meta" id="ph-node-meta">—</span>
        <div style="display:flex;gap:.3rem;margin-left:auto">
          <button class="btn btn-muted btn-sm" onclick="phCopyCard('node')" title="Copy this card as text">⎘ Copy</button>
          <button class="btn btn-muted btn-sm" onclick="loadTab_phone()">↻ Re-check</button>
        </div>
      </div>
      <div id="ph-node-body"><div class="stub-panel" style="min-height:60px">Loading…</div></div>
    </div>
    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Phone networks</span>
        <span class="reg-card-status" id="ph-nets-status">—</span>
        <span class="s3-card-meta" id="ph-nets-meta">—</span>
        <div style="display:flex;gap:.3rem;margin-left:auto">
          <button class="btn btn-muted btn-sm" onclick="phCopyCard('nets')" title="Copy this card as text">⎘ Copy</button>
          <button class="btn btn-muted btn-sm" onclick="loadTab_phone()">↻ Re-check</button>
        </div>
      </div>
      <div id="ph-nets-body"><div class="stub-panel" style="min-height:60px">Loading…</div></div>
    </div>
    <div class="s3-card" id="ph-hoip-card" style="display:none">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Hams Over IP</span>
        <span class="reg-card-status" id="ph-hoip-status">—</span>
        <span class="s3-card-meta" id="ph-hoip-meta">—</span>
        <div style="display:flex;gap:.3rem;margin-left:auto">
          <button class="btn btn-muted btn-sm" onclick="phCopyCard('hoip')" title="Copy this card as text">⎘ Copy</button>
          <button class="btn btn-muted btn-sm" onclick="loadTab_phone()">↻ Re-check</button>
        </div>
      </div>
      <div id="ph-hoip-body"><div class="stub-panel" style="min-height:60px">Loading…</div></div>
    </div>
    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Dialing rules</span>
        <span class="reg-card-status" id="ph-dial-status">—</span>
        <span class="s3-card-meta" id="ph-dial-meta">—</span>
        <div style="display:flex;gap:.3rem;margin-left:auto">
          <button class="btn btn-muted btn-sm" onclick="phCopyCard('dial')" title="Copy this card as text">⎘ Copy</button>
          <button class="btn btn-muted btn-sm" onclick="loadTab_phone()">↻ Re-check</button>
        </div>
      </div>
      <div id="ph-dial-body"><div class="stub-panel" style="min-height:60px">Loading…</div></div>
    </div>
    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Health checks</span>
        <span class="reg-card-status" id="ph-health-status">—</span>
        <span class="s3-card-meta" id="ph-health-meta">—</span>
        <div style="display:flex;gap:.3rem;margin-left:auto">
          <button class="btn btn-muted btn-sm" onclick="phCopyCard('health')" title="Copy this card as text">⎘ Copy</button>
          <button class="btn btn-muted btn-sm" onclick="loadTab_phone()">↻ Re-check</button>
        </div>
      </div>
      <div id="ph-health-body"><div class="stub-panel" style="min-height:60px">Loading…</div></div>
    </div>
    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Router test</span>
        <span class="reg-card-status" id="ph-rt-status">—</span>
        <span class="s3-card-meta" id="ph-rt-meta">press a test below</span>
        <div style="display:flex;gap:.3rem;margin-left:auto">
          <button class="btn btn-muted btn-sm" onclick="phCopyCard('rt')" title="Copy this card as text">⎘ Copy</button>
        </div>
      </div>
      <div id="ph-rt-body">
        <div class="ph-sub">1 · Going out</div>
        <div class="ph-nocopy" style="margin:.3rem 0"><button class="btn btn-muted btn-sm" id="rt-out-btn" onclick="rtOut()">Run outgoing test</button>
          <span class="ph-note">Re-signs in to your phone provider once and sends one STUN packet. Takes about 5 seconds.</span></div>
        <div id="rt-out-box"></div>
        <div class="ph-sub">2 · Call audio</div>
        <div class="ph-nocopy" style="margin:.3rem 0"><button class="btn btn-muted btn-sm" id="rt-audio-btn" onclick="rtAudio()">Check audio now</button>
          <span class="ph-note">Start a Test call on the dashboard Phone tab first, then press this. It counts packets in and out over 4 seconds (SIP calls only).</span></div>
        <div id="rt-audio-box"></div>
        <div class="ph-sub">3 · Coming in</div>
        <div class="ph-nocopy" style="margin:.3rem 0"><button class="btn btn-muted btn-sm" onclick="rtIn(true)">Start watching (10 min)</button>
          <button class="btn btn-muted btn-sm" onclick="rtIn(false)">Check</button>
          <span class="ph-note">Have someone call your number or extension while watching.</span></div>
        <div id="rt-in-box"></div>
      </div>
    </div>
    <div class="s3-card" id="ph-mods-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Autopatch modules</span>
        <span class="reg-card-status" id="ph-mods-status">—</span>
        <span class="s3-card-meta" id="ph-mods-meta">—</span>
        <div style="display:flex;gap:.3rem;margin-left:auto">
          <button class="btn btn-muted btn-sm" onclick="phCopyCard('mods')" title="Copy this card as text">⎘ Copy</button>
          <button class="btn btn-muted btn-sm" onclick="loadTab_phone()">↻ Re-check</button>
        </div>
      </div>
      <div id="ph-mods-body"><div class="stub-panel" style="min-height:60px">Loading…</div></div>
    </div>
    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Recent call attempts</span>
        <span class="reg-card-status" id="ph-calls-status">—</span>
        <span class="s3-card-meta" id="ph-calls-meta">—</span>
        <div style="display:flex;gap:.3rem;margin-left:auto">
          <button class="btn btn-muted btn-sm" onclick="phCopyCard('calls')" title="Copy this card as text">⎘ Copy</button>
          <button class="btn btn-muted btn-sm" onclick="loadTab_phone()">↻ Re-check</button>
        </div>
      </div>
      <div id="ph-calls-body"><div class="stub-panel" style="min-height:60px">Loading…</div></div>
    </div>
  </div>

  <div id="panel-tune" class="tab-panel">

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">SimpleUSB — Tune Settings</span>
        <div style="display:flex;align-items:center;gap:.5rem">
          <span class="s3-card-meta" id="su-tune-status">—</span>
          <button class="ast-toggle" id="su-tune-toggle" aria-expanded="true"
            onclick="toggleTuneCard()" title="Show / hide this card">Hide</button>
        </div>
      </div>
      <div id="su-tune-body">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Node Settings — rpt.conf</span>
        <div style="display:flex;align-items:center;gap:.5rem">
          <span class="s3-card-meta" id="rn-status">—</span>
          <button class="ast-toggle" id="rn-toggle" aria-expanded="false"
            onclick="toggleRptCard()" title="Show / hide this card">Show</button>
        </div>
      </div>
      <div id="rn-body" class="hidden">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>

  </div>

  <div id="panel-hardware" class="tab-panel">

    <div class="hw-copybar" style="display:flex;justify-content:flex-end;padding:.2rem 0 .5rem">
      <button class="btn btn-muted btn-sm" onclick="dtCopy(this, hwText)"
        title="Copy the whole Hardware tab as text">⎘ Copy hardware report</button>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Node Health</span>
        <span class="s3-card-meta" id="hw-health-meta">checking…</span>
      </div>
      <div id="hw-health-body">
        <div class="stub-panel" style="min-height:60px">Loading…</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">AMBE Device</span>
        <span class="s3-card-meta" id="hw-ambe-meta">detecting…</span>
      </div>
      <div id="hw-ambe-body">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Audio Device</span>
        <span class="s3-card-meta" id="hw-audio-meta">detecting…</span>
      </div>
      <div id="hw-audio-body">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Power &amp; Thermal</span>
        <span class="s3-card-meta" id="hw-pwr-meta">—</span>
      </div>
      <div id="hw-pwr-body">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Video &amp; GPU Memory</span>
        <span class="s3-card-meta" id="hw-vid-meta">—</span>
      </div>
      <div id="hw-vid-body">
        <div class="stub-panel" style="min-height:60px">Loading…</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">USB Bus</span>
        <span class="s3-card-meta" id="hw-usb-meta">—</span>
        <div style="display:flex;gap:.3rem">
          <button class="btn btn-muted btn-sm hw-diag-toggle active" id="hw-usb-btn-flat"
                  onclick="hwUsbToggle('flat')">Flat</button>
          <button class="btn btn-muted btn-sm hw-diag-toggle" id="hw-usb-btn-tree"
                  onclick="hwUsbToggle('tree')">Tree</button>
        </div>
      </div>
      <div class="hw-diag-note" style="margin:.5rem .9rem 0">
        "possible AMBE" is a vendor-ID guess (any FTDI-chip device gets this badge) —
        only a badge reading the exact product name (e.g. ThumbDV) is a confirmed match.
      </div>
      <div id="hw-usb-body">
        <div class="stub-panel" style="min-height:60px">Loading…</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">asl-find-sound</span>
        <span class="s3-card-meta" id="hw-afs-meta">—</span>
      </div>
      <div id="hw-afs-body">
        <div class="stub-panel" style="min-height:60px">Loading…</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">ALSA Cards</span>
        <span class="s3-card-meta" id="hw-alsa-meta">—</span>
        <div style="display:flex;gap:.3rem">
          <button class="btn btn-muted btn-sm hw-diag-toggle active" id="hw-alsa-btn-pb"
                  onclick="hwAlsaToggle('playback')">Playback</button>
          <button class="btn btn-muted btn-sm hw-diag-toggle" id="hw-alsa-btn-cap"
                  onclick="hwAlsaToggle('capture')">Capture</button>
        </div>
      </div>
      <div id="hw-alsa-body">
        <div class="stub-panel" style="min-height:60px">Loading…</div>
      </div>
    </div>

  </div>

  <div id="panel-dvsm" class="tab-panel">

    <div class="dvsm-tab-hdr">
      <span class="dvsm-tab-title">DVSwitch Mobile — Account Configuration</span>
      <div class="dvsm-tab-hdr-right">
        <span class="dvsm-node-ip-lbl">
          Node IP: <span id="dvsm-node-ip" style="color:var(--orange)">—</span>
        </span>
        <button class="btn btn-orange btn-sm" onclick="loadDvsm()">↻ Refresh</button>
      </div>
    </div>

    <div class="dvsm-grid">

      <div class="s3-card">
        <div class="s3-card-hdr" style="padding-left:.6rem">
          <div style="display:flex;align-items:center;gap:.55rem">
            <div class="dvsm-accent" style="background:var(--blue)"></div>
            <div>
              <div class="dvsm-card-title" style="color:var(--blue)">IAX2 Direct</div>
              <div class="dvsm-card-sub">Phone-mode client → this node</div>
            </div>
          </div>
          <span class="dpbadge" id="dvsm-badge-direct">—</span>
        </div>
        <div id="dvsm-body-direct">
          <div class="stub-panel" style="min-height:140px">Loading…</div>
        </div>
      </div>

      <div class="s3-card">
        <div class="s3-card-hdr" style="padding-left:.6rem">
          <div style="display:flex;align-items:center;gap:.55rem">
            <div class="dvsm-accent" style="background:var(--green)"></div>
            <div>
              <div class="dvsm-card-title" style="color:var(--green)">IAXRpt</div>
              <div class="dvsm-card-sub">Radio mode — most data-efficient</div>
            </div>
          </div>
          <span class="dpbadge" id="dvsm-badge-iaxrpt">—</span>
        </div>
        <div id="dvsm-body-iaxrpt">
          <div class="stub-panel" style="min-height:140px">Loading…</div>
        </div>
      </div>

      <div class="s3-card">
        <div class="s3-card-hdr" style="padding-left:.6rem">
          <div style="display:flex;align-items:center;gap:.55rem">
            <div class="dvsm-accent" style="background:var(--purple)"></div>
            <div>
              <div class="dvsm-card-title" style="color:var(--purple)">Node Mode</div>
              <div class="dvsm-card-sub">DVSM registers as full ASL node</div>
            </div>
          </div>
          <span class="dpbadge" id="dvsm-badge-node">—</span>
        </div>
        <div id="dvsm-body-node">
          <div class="stub-panel" style="min-height:140px">Loading…</div>
        </div>
      </div>

      <div class="s3-card">
        <div class="s3-card-hdr" style="padding-left:.6rem">
          <div style="display:flex;align-items:center;gap:.55rem">
            <div class="dvsm-accent" style="background:var(--amber)"></div>
            <div>
              <div class="dvsm-card-title" style="color:var(--amber)">USRP / DVSwitch Bridge</div>
              <div class="dvsm-card-sub">Connect via Analog_Bridge USRP port</div>
            </div>
          </div>
          <span class="dpbadge" id="dvsm-badge-usrp">—</span>
        </div>
        <div id="dvsm-body-usrp">
          <div class="stub-panel" style="min-height:140px">Loading…</div>
        </div>
      </div>

    </div>

    <div class="s3-card" style="margin-bottom:1rem">
      <div class="s3-card-hdr" style="padding-left:.6rem">
        <div style="display:flex;align-items:center;gap:.55rem">
          <div class="dvsm-accent" style="background:var(--red)"></div>
          <div>
            <div class="dvsm-card-title" style="color:var(--red)">Compatibility Checks</div>
            <div class="dvsm-card-sub">rpt.conf · iax.conf flags for DVSM features</div>
          </div>
        </div>
      </div>
      <div id="dvsm-body-compat">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>

  </div>
  
  <div id="panel-stfu" class="tab-panel">

    <div class="stfu-tab-hdr">
      <span class="stfu-tab-title">STFU — DVSwitch BrandMeister Terminal</span>
      <button class="btn btn-blue btn-sm" onclick="loadStfu()">↻ Refresh</button>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr" style="padding-left:.6rem">
        <div style="display:flex;align-items:center;gap:.55rem">
          <div class="dvsm-accent" style="background:var(--green)"></div>
          <div>
            <div class="dvsm-card-title" style="color:var(--green)">Installation</div>
            <div class="dvsm-card-sub">Binary · Service · Status</div>
          </div>
        </div>
        <span class="dpbadge" id="stfu-badge-install">—</span>
      </div>
      <div id="stfu-body-install">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr" style="padding-left:.6rem">
        <div style="display:flex;align-items:center;gap:.55rem">
          <div class="dvsm-accent" style="background:var(--blue)"></div>
          <div>
            <div class="dvsm-card-title" style="color:var(--blue)">Configuration</div>
            <div class="dvsm-card-sub" id="stfu-config-path">/opt/MMDVM_Bridge/DVSwitch.ini [STFU]</div>
          </div>
        </div>
        <span class="dpbadge" id="stfu-badge-config">—</span>
      </div>
      
      <div class="stfu-bm-bar">
        <div class="stfu-bm-bar-left">
          <span style="font-size:var(--fs-base);opacity:.7">🔗</span>
          <span class="stfu-bm-label">BrandMeister Master Server —</span>
          <a class="stfu-bm-link"
             href="https://brandmeister.network/?page=masterserver"
             target="_blank" rel="noopener">
            brandmeister.network/masterserver
          </a>
        </div>
        <span class="stfu-bm-pill">Hotspot&nbsp;Password&nbsp;→&nbsp;Self&nbsp;Care</span>
      </div>
      <div id="stfu-body-config">
        <div class="stub-panel" style="min-height:140px">Loading…</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr" style="padding-left:.6rem">
        <div style="display:flex;align-items:center;gap:.55rem">
          <div class="dvsm-accent" style="background:var(--red)"></div>
          <div>
            <div class="dvsm-card-title" style="color:var(--red)">Compatibility Checks</div>
            <div class="dvsm-card-sub">DVSwitch.ini [STFU] · systemd</div>
          </div>
        </div>
      </div>
      <div id="stfu-body-compat">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="stfu-sample-hdr">
        <span class="stfu-sample-title">Sample [STFU] Stanza</span>
        <div class="stfu-sample-btns">
          <button class="btn btn-muted btn-sm"
            onclick="stfuCopyStanza(this)">⎘ Copy Stanza</button>
          <button class="btn btn-blue btn-sm"
            onclick="stfuOpenEditor()">✎ Edit Stanza</button>
        </div>
      </div>
      <div id="stfu-body-sample">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>

    <div class="s3-card" style="margin-bottom:1rem">
      <div class="s3-card-hdr" style="padding-left:.6rem">
        <div style="display:flex;align-items:center;gap:.55rem">
          <div class="dvsm-accent" style="background:var(--amber)"></div>
          <div>
            <div class="dvsm-card-title" style="color:var(--amber)">Edit DVSwitch.ini</div>
            <div class="dvsm-card-sub" id="stfu-editor-path">—</div>
          </div>
        </div>
        <button class="btn btn-muted btn-sm" id="stfu-editor-toggle"
          onclick="stfuToggleEditor()">▼ Expand</button>
      </div>
      <div class="stfu-editor-wrap" id="stfu-editor-wrap">
        <textarea id="stfu-textarea" spellcheck="false"></textarea>
        <div class="stfu-editor-bar">
          <button class="btn btn-sm" style="color:var(--green);border-color:var(--green-dim)"
            onclick="stfuRestart()">↺ Restart STFU</button>
          <button class="btn btn-blue btn-sm"
            onclick="stfuSave()">💾 Save</button>
          <button class="btn btn-muted btn-sm"
            onclick="stfuCopy()">⎘ Copy</button>
          <button class="btn btn-muted btn-sm"
            onclick="stfuDiscardEdit()">✕ Close</button>
          <span style="font-family:var(--sans);font-size:var(--fs-xs);
            color:#fff;margin-left:auto">
            Save then Restart to apply changes</span>
        </div>
      </div>
    </div>

  </div>

  <div id="panel-m17" class="tab-panel">

    <div class="stfu-tab-hdr">
      <span class="stfu-tab-title">M17 — USRP2M17 Bridge</span>
      <button class="btn btn-blue btn-sm" onclick="loadM17()">↻ Refresh</button>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr" style="padding-left:.6rem">
        <div style="display:flex;align-items:center;gap:.55rem">
          <div class="dvsm-accent" style="background:var(--green)"></div>
          <div>
            <div class="dvsm-card-title" style="color:var(--green)">Installation</div>
            <div class="dvsm-card-sub">Binary · Service · Status</div>
          </div>
        </div>
        <span class="dpbadge" id="m17-badge-install">—</span>
      </div>
      <div id="m17-body-install">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
      <div style="padding:.5rem .6rem;border-top:1px solid rgba(255,255,255,.06)">
        <button class="btn btn-sm" style="color:var(--green);border-color:var(--green-dim)"
          onclick="m17Restart()">↺ Restart usrp2m17</button>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr" style="padding-left:.6rem">
        <div style="display:flex;align-items:center;gap:.55rem">
          <div class="dvsm-accent" style="background:var(--blue)"></div>
          <div>
            <div class="dvsm-card-title" style="color:var(--blue)">Configuration</div>
            <div class="dvsm-card-sub" id="m17-config-path">/opt/USRP2M17/USRP2M17.ini</div>
          </div>
        </div>
        <span class="dpbadge" id="m17-badge-config">—</span>
      </div>
      <div id="m17-body-config">
        <div class="stub-panel" style="min-height:140px">Loading…</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr" style="padding-left:.6rem">
        <div style="display:flex;align-items:center;gap:.55rem">
          <div class="dvsm-accent" style="background:var(--red)"></div>
          <div>
            <div class="dvsm-card-title" style="color:var(--red)">Compatibility Checks</div>
            <div class="dvsm-card-sub">USRP2M17.ini · rpt.conf [1917] · systemd</div>
          </div>
        </div>
      </div>
      <div id="m17-body-compat">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr" style="padding-left:.6rem">
        <div style="display:flex;align-items:center;gap:.55rem">
          <div class="dvsm-accent" style="background:var(--blue)"></div>
          <div>
            <div class="dvsm-card-title" style="color:var(--blue)">Reflector Host File</div>
            <div class="dvsm-card-sub">/var/lib/mmdvm/M17Hosts.json</div>
          </div>
        </div>
        <span class="dpbadge" id="m17-badge-hosts">—</span>
      </div>
      <div id="m17-body-hosts">
        <div class="stub-panel" style="min-height:60px">Loading…</div>
      </div>
      <div style="padding:.5rem .6rem;border-top:1px solid rgba(255,255,255,.06)">
        <button class="btn btn-sm" style="color:var(--blue);border-color:var(--blue-dim)"
          onclick="m17UpdateHosts()">⟳ Update Now</button>
      </div>
    </div>

    <div class="s3-card" style="margin-bottom:1rem">
      <div class="stfu-sample-hdr">
        <span class="stfu-sample-title">Sample USRP2M17.ini</span>
        <div class="stfu-sample-btns">
          <button class="btn btn-muted btn-sm"
            onclick="m17CopyStanza(this)">⎘ Copy Stanza</button>
        </div>
      </div>
      <div id="m17-body-sample">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>

    <div class="s3-card" style="margin-bottom:1rem">
      <div class="s3-card-hdr" style="padding-left:.6rem">
        <div style="display:flex;align-items:center;gap:.55rem">
          <div class="dvsm-accent" style="background:var(--amber)"></div>
          <div>
            <div class="dvsm-card-title" style="color:var(--amber)">Edit USRP2M17.ini</div>
            <div class="dvsm-card-sub" id="m17-editor-path">—</div>
          </div>
        </div>
        <button class="btn btn-muted btn-sm" id="m17-editor-toggle"
          onclick="m17ToggleEditor()">▼ Expand</button>
      </div>
      <div class="stfu-editor-wrap" id="m17-editor-wrap">
        <div style="padding:.5rem .6rem;font-family:var(--sans);font-size:var(--fs-xs);
          color:var(--amber);border-bottom:1px solid rgba(255,255,255,.06)">
          ⚠ Overwritten in full by the ASL-DVS-M17 dashboard on every M17
          connect/disconnect — edits here won't survive the next tune.
        </div>
        <textarea id="m17-textarea" spellcheck="false"></textarea>
        <div class="stfu-editor-bar">
          <button class="btn btn-blue btn-sm"
            onclick="m17Save()">💾 Save</button>
          <button class="btn btn-muted btn-sm"
            onclick="m17Copy()">⎘ Copy</button>
          <button class="btn btn-muted btn-sm"
            onclick="m17DiscardEdit()">✕ Close</button>
          <span style="font-family:var(--sans);font-size:var(--fs-xs);
            color:#fff;margin-left:auto">
            Restart from the Installation card above to apply changes
          </span>
        </div>
      </div>
    </div>

  </div>

  <div id="panel-sdcard" class="tab-panel">

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">SD Card Health</span>
        <span class="s3-card-meta" id="sd-health-meta">—</span>
        <div style="display:flex;gap:.3rem;margin-left:auto">
          <button class="btn btn-muted btn-sm" id="sd-health-refresh"
                  onclick="loadSdHealth()">↻ Re-check</button>
        </div>
      </div>
      <div id="sd-health-body">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Integrity Tests</span>
        <span class="s3-card-meta" id="sd-test-meta">read-only</span>
      </div>
      <div id="sd-test-body">
        <div class="stub-panel" style="min-height:60px">Loading…</div>
      </div>
    </div>

  </div>

  <div id="panel-edit" class="tab-panel">

    <div class="ed-section">
      <div class="ed-section-title">Visible Tabs</div>
      <div class="tab-vis-row" id="ed-tabvis">
        <label class="tab-vis-lbl locked" title="Always on — cannot be hidden">
          <input type="checkbox" id="tabchk-overview" value="overview" checked disabled>Overview</label>
        <label class="tab-vis-lbl">
          <input type="checkbox" id="tabchk-services" value="services" onchange="edTabVisChanged()">Services</label>
        <label class="tab-vis-lbl">
          <input type="checkbox" id="tabchk-ports" value="ports" onchange="edTabVisChanged()">Ports</label>
        <label class="tab-vis-lbl">
          <input type="checkbox" id="tabchk-journal" value="journal" onchange="edTabVisChanged()">Journal</label>
        <label class="tab-vis-lbl">
          <input type="checkbox" id="tabchk-asldvs" value="asldvs" onchange="edTabVisChanged()">ASL-DVS</label>
        <label class="tab-vis-lbl">
          <input type="checkbox" id="tabchk-reg" value="reg" onchange="edTabVisChanged()">Reg</label>
        <label class="tab-vis-lbl">
          <input type="checkbox" id="tabchk-phone" value="phone" onchange="edTabVisChanged()">Phone</label>
        <label class="tab-vis-lbl">
          <input type="checkbox" id="tabchk-tune" value="tune" onchange="edTabVisChanged()">Tune</label>
        <label class="tab-vis-lbl">
          <input type="checkbox" id="tabchk-hardware" value="hardware" onchange="edTabVisChanged()">Hardware</label>
        <label class="tab-vis-lbl">
          <input type="checkbox" id="tabchk-dvsm" value="dvsm" onchange="edTabVisChanged()">DVSM</label>
        <label class="tab-vis-lbl">
          <input type="checkbox" id="tabchk-stfu" value="stfu" onchange="edTabVisChanged()">STFU</label>
        <label class="tab-vis-lbl">
          <input type="checkbox" id="tabchk-m17" value="m17" onchange="edTabVisChanged()">M17</label>
        <label class="tab-vis-lbl">
          <input type="checkbox" id="tabchk-sdcard" value="sdcard" onchange="edTabVisChanged()">SD Card</label>
        <label class="tab-vis-lbl locked" title="Always on — cannot be hidden">
          <input type="checkbox" id="tabchk-edit" value="edit" checked disabled>Edit</label>
      </div>
      <div class="ed-hint">Overview and Edit are always on · changes apply on Save</div>
    </div>

    <div class="ed-section">
      <div class="ed-section-title">Identity</div>
      <div class="ed-grid">
        <div class="ed-field">
          <label class="ed-lbl" for="ed-callsign">Callsign</label>
          <input class="ed-inp" id="ed-callsign" type="text"
            maxlength="9" placeholder="KD8PGK"
            oninput="edValidate()">
          <span class="ed-err" id="ed-callsign-err"></span>
        </div>
        <div class="ed-field">
          <label class="ed-lbl" for="ed-node">Node</label>
          <input class="ed-inp" id="ed-node" type="text"
            maxlength="10" placeholder="652701"
            oninput="edValidate()">
          <span class="ed-err" id="ed-node-err"></span>
        </div>
        <div class="ed-field">
          <label class="ed-lbl" for="ed-label">Label</label>
          <input class="ed-inp" id="ed-label" type="text"
            maxlength="40" placeholder="AllStarLink Node">
        </div>
      </div>
    </div>

    <div class="ed-section">
      <div class="ed-section-title">Server</div>
      <div class="ed-grid">
        <div class="ed-field">
          <label class="ed-lbl" for="ed-port">Port</label>
          <input class="ed-inp" id="ed-port" type="text"
            maxlength="5" placeholder="9999"
            oninput="edValidate()">
          <span class="ed-err" id="ed-port-err"></span>
        </div>
        <div class="ed-field">
          <label class="ed-lbl" for="ed-host">Bind Host</label>
          <input class="ed-inp" id="ed-host" type="text"
            maxlength="40" placeholder="0.0.0.0"
            oninput="edValidate()">
          <span class="ed-err" id="ed-host-err"></span>
        </div>
      </div>
    </div>

    <div class="ed-section">
      <div class="ed-section-title">Thresholds</div>
      <div class="ed-grid">
        <div class="ed-field">
          <label class="ed-lbl" for="ed-cpu-warn">CPU warn %</label>
          <input class="ed-inp" id="ed-cpu-warn" type="text"
            maxlength="3" placeholder="50"
            oninput="edValidate()">
        </div>
        <div class="ed-field">
          <label class="ed-lbl" for="ed-rss-warn">RSS warn MiB</label>
          <input class="ed-inp" id="ed-rss-warn" type="text"
            maxlength="5" placeholder="200"
            oninput="edValidate()">
        </div>
        <div class="ed-field">
          <label class="ed-lbl" for="ed-nr-warn">NRestart warn</label>
          <input class="ed-inp" id="ed-nr-warn" type="text"
            maxlength="3" placeholder="3"
            oninput="edValidate()">
        </div>
        <div class="ed-field">
          <label class="ed-lbl" for="ed-nr-crit">NRestart crit</label>
          <input class="ed-inp" id="ed-nr-crit" type="text"
            maxlength="3" placeholder="10"
            oninput="edValidate()">
        </div>
      </div>
    </div>

    <div class="ed-collapsible-hdr" id="ed-asl-hdr" onclick="edToggleAslDvs()">
      <span class="ed-collapsible-title">Config Files</span>
      <span class="ed-collapsible-chevron" id="ed-asl-chevron">▶</span>
    </div>
    <div class="ed-collapsible-body collapsed" id="ed-asl-body">

      <div class="s3-card" style="margin:.5rem 0 .5rem">
        <div class="s3-card-hdr">
          <span class="s3-card-title">Asterisk — /etc/asterisk/</span>
          <span class="s3-card-meta">Edit · Hide from ASL-DVS tab</span>
        </div>
        <div id="ed-ast-file-body">
          <div class="stub-panel" style="min-height:50px">Loading…</div>
        </div>
      </div>

      <div class="s3-card" style="margin:0 0 .5rem">
        <div class="s3-card-hdr">
          <span class="s3-card-title">DVSwitch</span>
          <span class="s3-card-meta">Edit · Hide from ASL-DVS tab</span>
        </div>
        <div id="ed-dvs-file-body">
          <div class="stub-panel" style="min-height:50px">Loading…</div>
        </div>
      </div>

      <div class="s3-card" style="margin:0 0 .5rem">
        <div class="s3-card-hdr">
          <span class="s3-card-title">Allmon3 — /etc/allmon3/</span>
          <span class="s3-card-meta">Edit · Hide from ASL-DVS tab</span>
        </div>
        <div id="ed-allmon3-file-body">
          <div class="stub-panel" style="min-height:50px">Loading…</div>
        </div>
      </div>

    </div>

    <div class="ed-section" style="border-bottom:none">
      <div class="ed-collapsible-hdr" id="ed-pinned-hdr"
        onclick="edTogglePinned()">
        <span class="ed-collapsible-title">Pinned Services</span>
        <span class="ed-collapsible-chevron" id="ed-pinned-chevron">▶</span>
      </div>
      <div class="ed-collapsible-body collapsed" id="ed-pinned-body">
        <div style="font-family:var(--sans);font-size:var(--fs-xs);
          color:#fff;margin-bottom:.4rem;line-height:1.7">
          Format: unit | description | config_path | port | proto
          <br>Groups: __GROUP__:Name
        </div>
        <textarea class="ed-textarea" id="ed-pinned"
          spellcheck="false"></textarea>
        <div class="find-bar">
          <input class="find-inp" id="ed-find-inp" type="text" placeholder="Find in pinned services"
            spellcheck="false" autocomplete="off"
            oninput="findStart('ed')" onkeydown="findKey(event, 'ed')">
          <span class="find-count" id="ed-find-count"></span>
          <button class="btn btn-muted btn-sm" id="ed-find-prev" onclick="findStep('ed', -1)"
            title="Previous match (Shift+Enter)" disabled>▲ Prev</button>
          <button class="btn btn-muted btn-sm" id="ed-find-next" onclick="findStep('ed', 1)"
            title="Next match (Enter)" disabled>▼ Next</button>
        </div>
        <div class="ed-count" id="ed-pinned-count">0 service entries</div>
      </div>
    </div>

  </div>

</div>

<div id="ed-action-bar" style="flex-wrap:wrap">
  <button class="btn btn-amber" id="ed-save-btn"
    onclick="edSave()">Save</button>
  <button class="btn btn-muted"
    onclick="edReload()">↺ Reload from file</button>
  <button class="btn btn-blue"
    onclick="edAllConf('asl')">ASL AllConf</button>
  <button class="btn btn-blue"
    onclick="edAllConf('dvs')">DVS AllConf</button>
  <button class="btn btn-blue"
    onclick="openAppConfEditor('asl_dvs.conf')">asl_dvs.conf</button>
  <button class="btn btn-blue" id="ed-sysmonconf-btn"
    onclick="openAppConfEditor('sysmon.conf')">sysmon.conf</button>
  <span id="ed-status" style="font-family:var(--sans);
    font-size:var(--fs-sm);color:#fff;margin-left:.5rem"></span>
</div>

<div id="jp-overlay" onclick="jpOverlayClick(event)">
  <div id="jp-box">
    <div id="jp-hdr">
      <span id="jp-title">▤ journal</span>
      <div id="jp-ctrl">
        <button class="btn btn-blue btn-sm" id="jp-restart-btn"
          onclick="jpSvcAction('restart')">↺ Restart</button>
        <button class="btn btn-green btn-sm" id="jp-start-btn"
          onclick="jpSvcAction('start')">▶ Start</button>
        <button class="btn btn-muted btn-sm" id="jp-copy-btn"
          onclick="jpCopy()">⎘ Copy</button>
        <span id="jp-close" onclick="closeJournalPopup()">✕</span>
      </div>
    </div>
    <div id="jp-toolbar">
      <span style="font-family:var(--sans);font-size:var(--fs-xs);
        letter-spacing:.2em;text-transform:uppercase;color:#fff">Lines</span>
      <button class="jp-lines-btn" id="jp-ln-50"
        onclick="jpSetLines(50)">50</button>
      <button class="jp-lines-btn on" id="jp-ln-200"
        onclick="jpSetLines(200)">200</button>
      <button class="jp-lines-btn" id="jp-ln-all"
        onclick="jpSetLines(2000)">All</button>
      <div style="flex:1"></div>
      <input id="jp-grep" type="text" placeholder="grep filter…"
        oninput="jpGrepChanged()">
      <button class="btn btn-muted btn-sm"
        onclick="jpRefresh()">↻ Refresh</button>
    </div>
    <div id="jp-info" hidden></div>
    <div id="jp-body">Select a service from the Journal tab</div>
  </div>
</div>

<div id="modal-overlay">
  <div id="modal-box">
    <div id="modal-msg">Are you sure?</div>
    <div id="modal-btns">
      <button class="btn btn-muted" onclick="modalCancel()">Cancel</button>
      <button class="btn btn-red"   id="modal-ok">Confirm</button>
    </div>
  </div>
</div>

<div id="radio-dialog-overlay" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:2000;justify-content:center;align-items:center">
  <div style="background:var(--surface);border:1px solid var(--border2);border-radius:0.5rem;padding:1.2rem;max-width:420px;width:90%;box-shadow:0 4px 12px rgba(0,0,0,0.3)">

    <div id="radio-dialog-form-view">
      <div style="font-weight:600;font-size:var(--fs-lg);margin-bottom:0.8rem" id="radio-dialog-hdr">Save to Radio Preset</div>
      <div style="margin-bottom:1rem;font-size:var(--fs-md);color:#fff">
        <div id="radio-dialog-msg" style="margin-bottom:0.8rem">Enter a name for this preset:</div>
        <input type="text" id="radio-dialog-title" placeholder="e.g., Main, Mobile, Test…"
          style="width:100%;padding:0.5rem;border:1px solid var(--border2);border-radius:0.3rem;font-family:var(--sans);font-size:var(--fs-md);box-sizing:border-box"
          onkeydown="if(event.key==='Enter') confirmRadioDialog()">
      </div>

      <div id="radio-dialog-preset-row" style="margin-bottom:0.9rem;display:none">
        <label style="display:block;font-size:var(--fs-base);color:#fff;margin-bottom:0.3rem">Save as preset</label>
        <select id="radio-dialog-preset-select"
          style="width:100%;padding:0.4rem 0.5rem;background:var(--surface2);color:var(--text);border:1px solid var(--border2);border-radius:0.3rem;cursor:pointer"
          onchange="tuneDialogPresetChanged()">
          <option value="">Don't save as preset</option>
          <option value="1">Radio 1</option>
          <option value="2">Radio 2</option>
          <option value="3">Radio 3</option>
          <option value="4">Radio 4</option>
          <option value="5">Radio 5</option>
        </select>
      </div>

      <div id="radio-dialog-reload-row" style="margin-bottom:0.9rem;display:none">
        <label style="display:flex;align-items:center;gap:0.5rem;font-size:var(--fs-base);color:#fff;cursor:pointer">
          <input type="checkbox" id="radio-dialog-reload-toggle" onchange="tuneDialogReloadChanged()">
          Restart Asterisk after saving
        </label>
        <div id="radio-dialog-reload-warn" style="display:none;font-size:var(--fs-base);color:var(--amber);margin-top:0.4rem">
          ⚠ Will restart Asterisk — brief audio interruption
        </div>
      </div>

      <div id="radio-dialog-error" style="display:none;font-size:var(--fs-base);color:var(--red);margin-bottom:0.7rem"></div>

      <div style="display:flex;justify-content:flex-end;gap:0.5rem">
        <button class="btn btn-muted btn-sm" onclick="closeRadioDialog()">Cancel</button>
        <button class="btn btn-green btn-sm" id="radio-dialog-save-btn" onclick="confirmRadioDialog()">Save</button>
      </div>
    </div>

    <div id="radio-dialog-restart-view" style="display:none;text-align:center">
      <div style="font-weight:600;font-size:var(--fs-lg);margin-bottom:0.6rem">⚠ Asterisk is restarting</div>
      <div style="font-size:var(--fs-md);color:#fff;margin-bottom:1rem">node will be briefly offline</div>
      <div style="width:2rem;height:2rem;border:3px solid var(--border2);border-top-color:var(--teal);
        border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 1rem"></div>
      <div id="radio-dialog-restart-msg" style="font-size:var(--fs-base);color:var(--red);display:none;margin-bottom:0.8rem"></div>
      <div style="display:flex;justify-content:center;gap:0.5rem">
        <button class="btn btn-muted btn-sm" id="radio-dialog-restart-dismiss" style="display:none" onclick="closeRadioDialog()">Dismiss</button>
      </div>
    </div>

  </div>
</div>

<div id="uf-overlay" onclick="ufOverlayClick(event)">
  <div id="uf-box">
    <div id="uf-hdr">
      <span id="uf-title">✎ unit file</span>
      <div id="uf-hdr-right">
        <button class="btn btn-blue btn-sm" id="uf-restart-btn"
          onclick="ufRestart()">↺ Restart</button>
        <div class="find-bar">
          <input class="find-inp" id="uf-find-inp" type="text" placeholder="Find"
            spellcheck="false" autocomplete="off"
            oninput="findStart('uf')" onkeydown="findKey(event, 'uf')">
          <span class="find-count" id="uf-find-count"></span>
          <button class="btn btn-muted btn-sm" id="uf-find-prev" onclick="findStep('uf', -1)"
            title="Previous match (Shift+Enter)" disabled>▲ Prev</button>
          <button class="btn btn-muted btn-sm" id="uf-find-next" onclick="findStep('uf', 1)"
            title="Next match (Enter)" disabled>▼ Next</button>
        </div>
        <button class="btn btn-green btn-sm" id="uf-save-btn"
          onclick="ufSave()">Save</button>
        <button class="btn btn-muted btn-sm" id="uf-copy-btn"
          onclick="ufCopy()">⎘ Copy</button>
        <span id="uf-close" onclick="closeUnitFileEditor()">✕</span>
      </div>
    </div>
    <div id="uf-promoted-bar">
      ⚠ File is from /lib/systemd/system — saving will create an override in /etc/systemd/system/
    </div>
    <div id="uf-toolbar">
      <span id="uf-path">—</span>
      <button class="btn btn-muted btn-sm"
        onclick="ufReloadDaemon()">⟳ Reload Daemon</button>
      <span id="uf-status"></span>
    </div>
    <textarea id="uf-textarea" spellcheck="false"></textarea>
  </div>
</div>

<div id="allconf-overlay" onclick="allConfOverlayClick(event)">
  <div id="allconf-box">
    <div id="allconf-hdr">
      <span id="allconf-title">All Visible Config Files</span>
      <div style="display:flex;align-items:center;gap:.4rem">
        <div class="find-bar">
          <input class="find-inp" id="allconf-find-inp" type="text" placeholder="Find"
            spellcheck="false" autocomplete="off"
            oninput="findStart('allconf')" onkeydown="findKey(event, 'allconf')">
          <span class="find-count" id="allconf-find-count"></span>
          <button class="btn btn-muted btn-sm" id="allconf-find-prev" onclick="findStep('allconf', -1)"
            title="Previous match (Shift+Enter)" disabled>▲ Prev</button>
          <button class="btn btn-muted btn-sm" id="allconf-find-next" onclick="findStep('allconf', 1)"
            title="Next match (Enter)" disabled>▼ Next</button>
        </div>
        <button class="btn btn-green btn-sm" onclick="allConfCopy()">Copy All</button>
        <span id="allconf-close" onclick="closeAllConf()">✕</span>
      </div>
    </div>
    <div id="allconf-info">Loading…</div>
    <textarea id="allconf-textarea" spellcheck="false" readonly></textarea>
  </div>
</div>

<div id="dpanel-overlay" onclick="closePanel()"></div>
<div id="dpanel" role="dialog" aria-modal="true">

  <div id="dpanel-hdr">
    <span id="dpanel-close" onclick="closePanel()">✕ close</span>
    <div id="dpanel-unit">—</div>
    <div id="dpanel-desc"></div>
    <div id="dpanel-badges"></div>
    <div id="dp-own-zone"></div>
  </div>

  <div id="dpanel-body">

    <div class="dpzone-lbl">Daemon Controls</div>
    <div class="dpbtn-row">
      <button class="btn btn-blue btn-sm"
        onclick="dpSvcAction('reload_daemon','')">⟳ Reload Daemon</button>
      <button class="btn btn-amber btn-sm"
        id="dp-btn-reset"
        onclick="dpSvcAction('reset_failed', dpUnit())">✕ Reset Failed</button>
      <button class="btn btn-red btn-sm"
        onclick="dpSvcAction('mask', dpUnit())">⊘ Mask</button>
      <button class="btn btn-teal btn-sm"
        onclick="dpSvcAction('unmask', dpUnit())">◉ Unmask</button>
    </div>

    <div class="dpzone-lbl">Runtime Controls</div>
    <div class="dpbtn-row">
      <button class="btn btn-green btn-sm"
        onclick="dpSvcAction('start', dpUnit())">▶ Start</button>
      <button class="btn btn-amber btn-sm"
        onclick="dpSvcAction('stop', dpUnit())">■ Stop</button>
      <button class="btn btn-blue btn-sm"
        onclick="dpSvcAction('restart', dpUnit())">↺ Restart</button>
      <button class="btn btn-blue btn-sm"
        id="dp-btn-reload" disabled title="This unit does not support reload"
        onclick="dpSvcAction('reload', dpUnit())">↻ Reload</button>
    </div>

    <div class="dpzone-lbl">Boot Persistence</div>
    <div class="dpbtn-row">
      <button class="btn btn-green btn-sm"
        onclick="dpSvcAction('enable', dpUnit())">✓ Enable</button>
      <button class="btn btn-amber btn-sm"
        onclick="dpSvcAction('disable', dpUnit())">✗ Disable</button>
    </div>

    <div class="dpzone-lbl" id="dp-pin-lbl">Pinned Services</div>
    <div class="dpbtn-row" id="dp-pin-row">
      
    </div>

    <div class="dp-copy-row"><div class="dpzone-lbl">Status</div>
      <button class="btn btn-muted btn-sm" onclick="dpStatusCopy()">⎘ Copy</button></div>
    <div id="dpanel-output"><span class="dp-out-dim">Loading…</span></div>

  </div>
</div>

<div id="toast-stack"></div>
<div id="wfm-shutdown-overlay"><div id="wfm-shutdown-box">
  <div id="wfm-shutdown-hdr">⚠ wifimon — Node Shutting Down</div>
  <div id="wfm-shutdown-msg"></div>
  <div id="wfm-shutdown-sub">This node is powering off. It will need to be manually power-cycled or reconnected to WiFi.</div>
</div></div>

<script>
"use strict";

window._authLostHandled = false;

const _rawFetch = window.fetch.bind(window);
window.fetch = async function(input, init) {
  const url = typeof input === "string" ? input : (input && input.url) || "";
  const isApi = url.startsWith("/api/");
  const skipAuth = url === "/api/login" || url === "/api/ping";
  const res = await _rawFetch(input, init);
  if (isApi && !skipAuth && res.status === 401) _onAuthLost();
  return res;
};

let _appStarted = false;
const _RELOGIN_KEY         = "sysmonRelogin";
const _RELOGIN_WINDOW_MS   = 30000;
const _SESSION_EXPIRED_MSG = "Session expired — please log in again.";

function _onAuthLost() {
  if (window._authLostHandled) return;
  window._authLostHandled = true;
  if (_appStarted) {
    let last = 0;
    try { last = Number(sessionStorage.getItem(_RELOGIN_KEY)) || 0; } catch (_) {}
    if (!last || Date.now() - last > _RELOGIN_WINDOW_MS) {
      let stamped = false;
      try { sessionStorage.setItem(_RELOGIN_KEY, String(Date.now())); stamped = true; } catch (_) {}
      if (stamped) {
        location.reload();
        return;
      }
    }
  }
  showLoginScreen(_SESSION_EXPIRED_MSG);
}
function showLoginScreen(msg) {
  const el = document.getElementById("login-screen"); if (!el) return;
  el.classList.add("open");
  const errEl = document.getElementById("login-err"); if (errEl) errEl.textContent = msg || "";
  const pwEl = document.getElementById("login-pw");
  if (pwEl) { pwEl.value = ""; setTimeout(() => pwEl.focus(), 0); }
}
function hideLoginScreen() {
  const el = document.getElementById("login-screen"); if (el) el.classList.remove("open");
}

async function _doLogin(ev) {
  if (ev) ev.preventDefault();
  const pwEl = document.getElementById("login-pw");
  const btnEl = document.getElementById("login-btn");
  const errEl = document.getElementById("login-err");
  const password = pwEl ? pwEl.value : "";
  if (!password) return;
  if (btnEl) btnEl.disabled = true;
  if (errEl) errEl.textContent = "";
  try {
    const r = await fetch("/api/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password })
    });
    const d = await r.json().catch(() => ({ ok: false, message: "Unexpected response" }));
    if (r.ok && d.ok) {
      window._authLostHandled = false;
      try { sessionStorage.removeItem(_RELOGIN_KEY); } catch (_) {}
      hideLoginScreen();
      _startApp();
    } else {
      if (errEl) errEl.textContent = d.message || "Login failed";
    }
  } catch (e) {
    if (errEl) errEl.textContent = "Network error — is sysmon reachable?";
  } finally {
    if (btnEl) btnEl.disabled = false;
  }
}
function doLogout() {
  fetch("/api/logout", { method: "POST" })
    .catch(() => {})
    .finally(() => location.reload());
}


const TABS = ["overview","services","ports","journal","asldvs","reg","phone","tune","hardware","dvsm","stfu","m17","sdcard","edit"];

let _enabledTabSet = new Set(TABS);

let _savedEnabledTabs = TABS.slice();

let _ptRefreshTimer  = null;
let _phRefreshTimer  = null;
let _s3RefreshTimer  = null;
let _sdTestTimer = null;
let _statusPollTimer = null;

function _applyTabVisibilityGated() {
  applyTabVisibility(_savedEnabledTabs.slice());
}


function stopTabPolling(tab) {
  let cleared = false;
  if (tab === "ports"    && _ptRefreshTimer) { clearInterval(_ptRefreshTimer); _ptRefreshTimer = null; cleared = true; }
  if (tab === "reg"      && _regRefreshTimer) { clearInterval(_regRefreshTimer); _regRefreshTimer = null; cleared = true; }
  if (tab === "phone"    && _phRefreshTimer) { clearInterval(_phRefreshTimer); _phRefreshTimer = null; cleared = true; }
  if (tab === "services" && _s3RefreshTimer) { clearInterval(_s3RefreshTimer); _s3RefreshTimer = null; cleared = true; }
  if (tab === "sdcard"   && _sdTestTimer)    { clearInterval(_sdTestTimer);    _sdTestTimer    = null; cleared = true; }
  if (cleared) console.info("[sysmon] polling stopped: " + tab);
  return cleared;
}

function startStatusPolling() {
  if (_statusPollTimer) return;
  pollStatus();
  _statusPollTimer = setInterval(pollStatus, 5000);
}
function stopStatusPolling() {
  if (_statusPollTimer) { clearInterval(_statusPollTimer); _statusPollTimer = null; }
}

function switchTab(name, rgb) {
  TABS.forEach(t => {
    const panel = document.getElementById("panel-" + t);
    const btn   = document.getElementById("tbtn-" + t);
    if (!panel || !btn) return;
    const active = t === name;
    panel.classList.toggle("active", active);
    btn.classList.toggle("active",   active);
    if (active && rgb) {
      btn.style.setProperty("--ta",     `rgb(${rgb})`);
      btn.style.setProperty("--ta-rgb", rgb);
    }
  });
  TABS.forEach(t => document.body.classList.toggle("tab-" + t, t === name));

  TABS.forEach(t => { if (t !== name && t !== "sdcard") stopTabPolling(t); });

  if (_enabledTabSet.has(name) &&
      typeof window["loadTab_" + name] === "function") {
    window["loadTab_" + name]();
  }
}

function applyTabVisibility(enabled) {
  const set = new Set(Array.isArray(enabled) && enabled.length ? enabled : TABS);
  set.add("overview"); set.add("edit");
  _enabledTabSet = set;
  for (const t of TABS) {
    const btn = document.getElementById("tbtn-" + t);
    if (btn) btn.style.display = set.has(t) ? "" : "none";
    if (!set.has(t)) {
      if (t === "sdcard" && _sdTestTimer) {
        toast("SD test continues in background — re-enable tab to monitor", "info", 5000);
      }
      stopTabPolling(t);
    }
  }
  const active = TABS.find(t =>
    document.getElementById("tbtn-" + t)?.classList.contains("active"));
  if (active && !set.has(active)) {
    switchTab("overview", "0,255,229");
  }
}

let _toastId = 0;
function toast(msg, type, ms) {
  ms   = ms   || 3500;
  type = type || "info";
  const el = document.createElement("div");
  el.className  = "toast-item " + type;
  el.textContent = msg;
  el.id = "toast-" + (++_toastId);
  document.getElementById("toast-stack").appendChild(el);
  requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add("show")));
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 300);
  }, ms);
}

async function api(path, method, body) {
  method = method || "GET";
  try {
    const opts = {method: method, headers: {}};
    if (body !== null && body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const r = await fetch(path, opts);
    document.body.classList.remove("offline");
    return await r.json();
  } catch(e) {
    document.body.classList.add("offline");
    return null;
  }
}

let _uptimeBase = null;

let _wfmShutdownShown = false;
function showWfmShutdown(state) {
  if (_wfmShutdownShown) return;
  _wfmShutdownShown = true;
  const trig = state.trigger === "low_voltage" ? "Low voltage" :
               state.trigger === "no_conn"     ? "Lost network connection" : "wifimon";
  document.getElementById("wfm-shutdown-msg").textContent =
    trig + " — " + (state.reason || "shutting down now.");
  document.getElementById("wfm-shutdown-overlay").classList.add("open");
}

async function pollStatus() {
  const d = await api("/api/status");
  if (!d) return;

  if (d.wifimon_shutdown && d.wifimon_shutdown.active) showWfmShutdown(d.wifimon_shutdown);

  window._portConflicts = d.port_conflicts || {};
  if ("reg_summary" in d) renderRegHeader(d.reg_summary);

  if (d.callsign) document.getElementById("hdr-callsign").textContent = d.callsign;
  if (d.node)     document.getElementById("hdr-node").textContent     = d.node;

  if (d.uptime_s != null) {
    _uptimeBase = {s: d.uptime_s, at: Date.now()};
    renderUptime();
  }

  const load = d.load || {};
  if (d.hostname) {
    const h = document.getElementById("s-host");
    h.textContent = d.hostname;
  }
  if (load.l1 != null) {
    const el  = document.getElementById("s-load");
    const l1  = parseFloat(load.l1);
    el.textContent = load.l1 + " / " + load.l5 + " / " + load.l15;
    el.className   = "sv" + (l1 > 3 ? " hot" : l1 > 1.5 ? " warn" : " ok");
  }
  if (d.memory && d.memory.used_mb != null) {
    document.getElementById("s-mem").textContent =
      d.memory.used_mb + " / " + d.memory.total_mb + " MiB";
  }
  if (d.cpu_temp != null) {
    const el = document.getElementById("s-temp");
    el.textContent = d.cpu_temp + "°C";
    el.className   = "sv" + (d.cpu_temp > 75 ? " hot" : d.cpu_temp > 60 ? " warn" : " ok");
  }
  if (d.throttle_state && d.throttle_state.available) {
    const ts  = d.throttle_state;
    const el  = document.getElementById("s-volt");
    
    if (ts.uv_now) {
      el.textContent = "⚡ UV";
      el.className   = "sv hot";
    } else if (ts.throttled_now) {
      el.textContent = "⚡ THR";
      el.className   = "sv hot";
    } else if (ts.uv_ever || ts.freq_cap_ever || ts.throttled_ever || ts.temp_ever) {
      el.textContent = "WARN";
      el.className   = "sv warn";
    } else {
      el.textContent = "OK";
      el.className   = "sv ok";
    }
    
    const bits = [];
    if (ts.uv_now)         bits.push("Under-voltage NOW");
    if (ts.freq_cap_now)   bits.push("Freq cap NOW");
    if (ts.throttled_now)  bits.push("Throttled NOW");
    if (ts.temp_now)       bits.push("Temp limit NOW");
    if (ts.uv_ever)        bits.push("Under-voltage since boot");
    if (ts.freq_cap_ever)  bits.push("Freq cap since boot");
    if (ts.throttled_ever) bits.push("Throttled since boot");
    if (ts.temp_ever)      bits.push("Temp limit since boot");
    el.title = bits.length
      ? `Power: ${ts.raw}\n${bits.join("\n")}`
      : `Power OK (${ts.raw})`;
    
    if (ts.uv_now && !window._uvToastShown) {
      window._uvToastShown = true;
      toast("⚡ Under-voltage detected — check power supply", "warn");
    } else if (!ts.uv_now) {
      window._uvToastShown = false;
    }
  } else if (d.pi_voltage != null) {
    
    const el = document.getElementById("s-volt");
    el.textContent = d.pi_voltage.toFixed(4) + "V";
    el.className   = "sv" + (d.pi_voltage < 0.82 ? " warn" : " ok");
    el.title       = "Core voltage (internal) — not supply voltage";
  }

  const rb = document.getElementById("restart-banner");
  if (rb) rb.classList.toggle("show", !!d.needs_restart);
}

function portBadge(port, proto) {
  const conflicts = window._portConflicts || {};
  const key       = `${proto}:${port}`;
  const span      = document.createElement("span");
  if (conflicts[key]) {
    const procs = conflicts[key].map(p => `${p.process}(${p.pid})`).join(", ");
    span.className = "pc-dup";
    span.textContent = "[DUP]";
    span.title = `Duplicate: ${procs}`;
  } else {
    span.className = "pc-ok";
    span.textContent = "[OK]";
    span.title = "No other process is bound to this port/protocol";
  }
  return span;
}

function renderUptime() {
  if (!_uptimeBase) return;
  const elapsed = Math.floor((Date.now() - _uptimeBase.at) / 1000);
  const total   = _uptimeBase.s + elapsed;
  const h  = Math.floor(total / 3600);
  const m  = Math.floor((total % 3600) / 60);
  const s  = total % 60;
  document.getElementById("hdr-uptime").textContent =
    "UP " + h + ":" + String(m).padStart(2,"0") + ":" + String(s).padStart(2,"0");
}


window.loadTab_overview = function() { loadOverview(); };

async function loadOverview() {
  const d = await api("/api/overview");
  if (!d) return;
  renderOverview(d.groups);
}

function renderOverview(groups) {
  _ovGroups = groups || [];
  const container = document.getElementById("ov-content");
  if (!container) return;

  Array.from(container.querySelectorAll(".ov-card")).forEach(el => el.remove());
  const loading = document.getElementById("ov-loading");
  if (loading) loading.style.display = "none";

  if (!groups || !groups.length) {
    if (loading) { loading.textContent = "No services configured."; loading.style.display = "flex"; }
    return;
  }

  groups.forEach(grp => {
    const card = document.createElement("div");
    card.className = "ov-card";

    const hdr = document.createElement("div");
    hdr.className = "ov-card-hdr ov-hdr-grid";
    hdr.innerHTML =
      `<span></span>` +
      `<span class="ov-card-title">${esc(grp.group)}</span>` +
      `<span class="ov-hdr-owner">Owner</span>` +
      `<span class="ov-hdr-mode">Perms</span>` +
      `<span class="ov-hdr-status">Status</span>` +
      `<span class="ov-hdr-port">Port</span>` +
      `<span></span>` +
      `<span></span>`;
    card.appendChild(hdr);

    grp.services.forEach(svc => renderOvRow(card, svc));

    container.insertBefore(card, document.getElementById("ov-global-bar"));
  });
}

function renderOvRow(card, svc) {
  const row = document.createElement("div");
  const ni  = svc.state === "not-inst";
  row.className = "ov-row" + (ni ? " not-inst" : "");

  const dot = dotEl(svc.state, svc.enabled);

  const name = document.createElement("a");
  name.className = "ov-name" + (ni ? " ni" : "");
  name.textContent = svc.unit.replace(".service", "");
  if (!ni) {
    name.href = "#";
    name.onclick = e => {
      e.preventDefault();
      _dpOriginTab = "overview";
      switchTab("services", "0,255,229");
      if (typeof openServicePanel === "function") openServicePanel(svc.unit, svc.desc);
    };
  }

  const ownerEl = _ovOwnerCell(svc);
  const modeEl   = _ovModeCell(svc);

  const state = document.createElement("span");
  state.className = "ov-state " + stateClass(svc.state);
  state.textContent = svc.state;

  const portEl = document.createElement("span");
  portEl.className = "ov-port";
  if (svc.nr > 0) {
    portEl.className = "ov-nr" + (svc.nr > 3 ? " nr-warn" : "");
    portEl.textContent = `NR:${svc.nr}${svc.nr > 3 ? "⚠" : ""}`;
  } else if (svc.port && svc.port !== "-") {
    portEl.textContent = `:${svc.port}/${svc.proto}`;
  }

  const badgeEl = document.createElement("span");
  if (svc.state === "active" && svc.port && svc.port !== "-" && svc.port !== "parse") {
    const b = portBadge(svc.port, svc.proto || "tcp");
    badgeEl.className   = b.className;
    badgeEl.textContent = b.textContent;
    if (b.title) badgeEl.title = b.title;
  } else {
    badgeEl.className = "pc-empty";
  }

  const btns = document.createElement("div");
  btns.className = "ov-btns";
  if (!ni) {
    ovBtns(svc).forEach(b => btns.appendChild(b));
  }

  row.appendChild(dot);
  row.appendChild(name);
  row.appendChild(ownerEl);
  row.appendChild(modeEl);
  row.appendChild(state);
  row.appendChild(portEl);
  row.appendChild(badgeEl);
  row.appendChild(btns);
  card.appendChild(row);
}

function _ovOwnerCell(svc) {
  const el = document.createElement("span");
  el.className = "ov-owner";
  el.textContent = svc.owner || "—";
  if (!svc.installed || svc.owner_source === "none") {
    el.title = "not installed";
    return el;
  }
  const srcTxt = svc.owner_source === "running"    ? "running as"
               : svc.owner_source === "configured" ? "configured User="
               :                                     "no User= set — systemd runs it as root";
  const bits = [`${svc.owner} — ${srcTxt}`];
  if (svc.owner_config) bits.push(`systemd User=${svc.owner_config}`);
  if (svc.owner_group)  bits.push(`Group=${svc.owner_group}`);

  if (svc.owner_is_root && svc.owner_exempt) {
    el.classList.add("own-ok");
    bits.push("root by design for this unit");
  } else if (svc.owner_is_root) {
    el.classList.add("own-warn");
    bits.push("this unit does not require root");
  }
  el.title = bits.join("; ");
  return el;
}

function _ovModeCell(svc) {
  const el = document.createElement("span");
  el.className = "ov-mode";
  if (!svc.installed) { el.textContent = "—"; el.title = "not installed"; return el; }
  el.textContent = svc.mode || "—";

  const lines = [];
  if (svc.unit_path) {
    lines.push(`unit  ${svc.mode || "?"}  ${svc.unit_owner || "?"}  ${svc.unit_path}`);
  } else {
    lines.push("unit  (FragmentPath not reported)");
  }
  if (svc.bin_path) {
    lines.push(`bin   ${svc.bin_mode || "?"}  ${svc.bin_owner || "?"}  ${svc.bin_path}`);
  }
  if (Array.isArray(svc.perm_reasons) && svc.perm_reasons.length) {
    lines.push("", ...svc.perm_reasons);
  }
  if      (svc.perm_verdict === "fail") el.classList.add("perm-fail");
  else if (svc.perm_verdict === "warn") el.classList.add("perm-warn");
  el.title = lines.join("\n");
  return el;
}

function ovBtns(svc) {
  const make = (label, cls, action) => {
    const b = document.createElement("button");
    b.className = `btn ${cls} btn-sm`;
    b.textContent = label;
    b.onclick = () => svcAction(action, svc.unit, b);
    return b;
  };
  const editBtn = () => {
    const b = document.createElement("button");
    b.className = "btn btn-muted btn-sm";
    b.textContent = "Edit";
    b.onclick = e => { e.stopPropagation(); openUnitFileEditor(svc.unit); };
    return b;
  };
  switch (svc.state) {
    case "active":
      return [make("↺ Restart", "btn-blue",  "restart"),
              make("■ Stop",    "btn-amber",  "stop"),
              make("☠ Kill",   "btn-red",    "kill_pid"),
              editBtn()];
    case "failed":
      return [make("▶ Start",  "btn-green",  "start"),
              make("✕ Reset",  "btn-amber",  "reset_failed"),
              editBtn()];
    case "inactive":
      return [make("▶ Start",  "btn-green",  "start"),
              editBtn()];
    default:
      return [];
  }
}

function _svcPollAfterRestart() {
  [3000, 8000, 16000, 28000].forEach(delay => setTimeout(loadOverview, delay));
}

async function svcAction(action, unit, btn) {
  
  if (action === "stop") {
    if (!await confirm(`Stop  ${unit}?`)) return;
  } else if (action === "kill_pid") {
    if (!await confirm(`☠ Kill PID for ${unit}?\n\nSends SIGKILL immediately — no clean shutdown.`)) return;
  } else if (action === "disable") {
    if (!await confirm(`Disable  ${unit}  at boot?`)) return;
  } else if (action === "mask") {
    if (!await confirm(`Mask  ${unit}?  This prevents it from starting.`)) return;
  }
  if (btn) btn.disabled = true;
  const d = await api("/api/svc", "POST", {action: action, unit: unit});
  if (btn) btn.disabled = false;
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "OK" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) {
    if (d.async) { _svcPollAfterRestart(); } else { setTimeout(loadOverview, 800); }
  }
}

function dotColorClass(state, enabled) {
  if (enabled === "masked") return "dot-fail";
  return {
    "active":   "dot-on",
    "failed":   "dot-fail",
    "inactive": "dot-warn",
    "not-inst": "dot-off",
    "unknown":  "dot-unknown",
  }[state] || "dot-unknown";
}

function dotEl(state, enabled) {
  const d = document.createElement("span");
  d.className = "dot " + dotColorClass(state, enabled);
  return d;
}

function stateClass(state) {
  return {"active":"st-active","failed":"st-failed",
          "inactive":"st-inactive","not-inst":"st-notinst",
          "unknown":"st-unknown"}[state] || "st-unknown";
}

function esc(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

let _s3Scope  = "active";
let _s3Filter = "";
let _s3FilterTimer = null;

function openServicePanel(unit, desc) {
  openPanel(unit, desc || "");
}

window.loadTab_services = function() {
  if (!_enabledTabSet.has("services")) return;
  clearInterval(_s3RefreshTimer);
  loadGeneralList();
  _s3RefreshTimer = setInterval(loadGeneralList, 30_000);
}


let _cfg_nr_warn = "3";
let _cfg_nr_crit = "10";
let _cfg_cpu_warn = "50";
let _cfg_rss_warn = "200";

function _applyThresholds(t) {
  if (!t) return;
  const num = v => (v != null && String(v).trim() !== "" && !isNaN(parseFloat(v))) ? String(v).trim() : null;
  _cfg_nr_warn  = num(t.nr_warn)      ?? _cfg_nr_warn;
  _cfg_nr_crit  = num(t.nr_crit)      ?? _cfg_nr_crit;
  _cfg_cpu_warn = num(t.cpu_warn_pct) ?? _cfg_cpu_warn;
  _cfg_rss_warn = num(t.rss_warn_mb)  ?? _cfg_rss_warn;
}

let _dpUnit       = "";
let _dpActiveView = "";
let _dpOriginTab  = "";
const TAB_RGB = {
  overview:"0,255,229", services:"0,255,229", ports:"34,212,255",
  journal:"212,102,255", asldvs:"255,61,90", phone:"0,255,176",
  tune:"255,68,204", hardware:"0,200,120", dvsm:"255,170,34",
  stfu:"0,191,255", sdcard:"180,140,255", edit:"255,208,64"
};

function dpUnit() { return _dpUnit; }

let _dpBodyDefault = null;
function _dpRestoreBody() {
  const body = document.getElementById("dpanel-body");
  if (!body) return;
  if (_dpBodyDefault === null) { _dpBodyDefault = body.innerHTML; return; }
  if (body.dataset.custom) {
    body.innerHTML = _dpBodyDefault;
    delete body.dataset.custom;
  }
}

async function openPanel(unit, desc) {
  _dpRestoreBody();
  _dpUnit       = unit;
  _dpActiveView = "";

  document.getElementById("dpanel-unit").textContent  = unit.replace(".service","");
  document.getElementById("dpanel-desc").textContent  = desc || "Loading…";
  document.getElementById("dpanel-badges").innerHTML  = "";
  document.getElementById("dpanel-output").innerHTML  =
    '<span class="dp-out-dim">Loading…</span>';
  dpSetReload(false);

  document.getElementById("dpanel-overlay").classList.add("open");
  document.getElementById("dpanel").classList.add("open");

  await dpRefreshHeader();
  dpLoadStatus();
}

function closePanel() {
  document.getElementById("dpanel-overlay").classList.remove("open");
  document.getElementById("dpanel").classList.remove("open");
  _dpUnit       = "";
  _dpActiveView = "";
  if (_dpOriginTab && _dpOriginTab !== "services") {
    switchTab(_dpOriginTab, TAB_RGB[_dpOriginTab]);
  }
  _dpOriginTab = "";
}

async function dpRefreshHeader() {
  if (!_dpUnit) return;
  const d = await api(`/api/services/detail?unit=${encodeURIComponent(_dpUnit)}`);
  if (!d || !d.ok) return;

  document.getElementById("dpanel-unit").textContent =
    _dpUnit.replace(".service","");
  document.getElementById("dpanel-desc").textContent = d.desc || _dpUnit;

  const accent = {
    "active":   "var(--green)",
    "failed":   "var(--red)",
    "inactive": "var(--amber)",
  }[d.state] || "var(--teal)";
  document.getElementById("dpanel").style.setProperty("--panel-accent", accent);

  const badgeEl = document.getElementById("dpanel-badges");
  badgeEl.innerHTML = "";

  const mkBadge = (text, cls) => {
    const b = document.createElement("span");
    b.className = "dpbadge " + cls;
    b.textContent = text;
    badgeEl.appendChild(b);
  };

  const stateCls = d.state === "active"  ? "dpbadge-state-active"
                 : d.state === "failed"  ? "dpbadge-state-failed"
                 : "dpbadge-state-other";
  mkBadge(d.state, stateCls);

  const enCls = d.enabled === "enabled" ? "dpbadge-enabled" : "dpbadge-disabled";
  mkBadge(d.enabled || "unknown", enCls);

  if (d.pid) mkBadge(`PID ${d.pid}`, "dpbadge-info");

  const nr = d.nrestarts || 0;
  if (nr > 0) {
    const nrCls = nr >= parseInt(_cfg_nr_crit) ? "dpbadge-crit"
                : nr >= parseInt(_cfg_nr_warn)  ? "dpbadge-warn"
                : "dpbadge-info";
    mkBadge(`NR:${nr}${nr >= parseInt(_cfg_nr_warn) ? "⚠" : ""}`, nrCls);
  }

  if (d.cpu_pct != null) {
    const hot = d.cpu_pct >= parseFloat(_cfg_cpu_warn);
    mkBadge(`CPU ${d.cpu_pct}%${hot ? "⚠" : ""}`, hot ? "dpbadge-warn" : "dpbadge-info");
  }
  if (d.rss_mb != null) {
    const big = d.rss_mb >= parseFloat(_cfg_rss_warn);
    mkBadge(`${d.rss_mb} MiB${big ? "⚠" : ""}`, big ? "dpbadge-warn" : "dpbadge-info");
  }

  if (d.installed && d.owner) {
    const ownCls = (d.owner_is_root && !d.owner_exempt) ? "dpbadge-warn"
                 : d.owner_is_root                       ? "dpbadge-info"
                 :                                         "dpbadge-enabled";
    mkBadge(`user ${d.owner}`, ownCls);
  }
  if (d.perm_verdict === "fail")      mkBadge("perms", "dpbadge-crit");
  else if (d.perm_verdict === "warn") mkBadge("perms", "dpbadge-warn");

  dpSetReload(!!d.can_reload);

  dpRenderOwnZone(d);
  dpRenderPinZone(_dpUnit);
}

function dpRenderOwnZone(d) {
  const host = document.getElementById("dp-own-zone");
  if (!host) return;
  if (!d.installed) { host.innerHTML = ""; return; }

  const row = (lbl, val, cls) =>
    `<div class="dp-own-row"><span class="dp-own-lbl">${_esc(lbl)}</span>` +
    `<span class="dp-own-val ${cls || ""}">${_esc(val)}</span></div>`;

  const srcTxt = d.owner_source === "running"    ? "running as"
               : d.owner_source === "configured" ? "configured User="
               :                                   "no User= set";
  const ownCls = (d.owner_is_root && !d.owner_exempt) ? "warn" : "";

  let html = `<div class="dpzone-lbl">Ownership &amp; permissions</div>`;
  html += row("Runs as", `${d.owner}  (${srcTxt})`, ownCls);
  html += row("systemd", `User=${d.owner_config || "(unset)"}` +
                          `  Group=${d.owner_group || "(unset)"}`, "");
  if (d.owner_is_root && d.owner_exempt) {
    html += row("", "root by design for this unit", "");
  }

  const f = d.unit_file || {}, b = d.exec_file || {};
  if (f.path) {
    html += row("Unit file", f.exists
      ? `${f.mode}  ${f.owner}:${f.group}  ${f.path}`
      : `${f.path}  (not readable)`,
      f.exists && (f.world_writable ? "fail" : (f.group_writable || !f.root_owned) ? "warn" : ""));
  }
  if (b.path) {
    html += row("ExecStart", b.exists
      ? `${b.mode}  ${b.owner}:${b.group}  ${b.path}`
      : `${b.path}  (not readable)`,
      b.exists && (b.world_writable ? "fail" : (b.group_writable || !b.root_owned) ? "warn" : ""));
  }
  (d.perm_reasons || []).forEach(r => { html += row("", r, "warn"); });

  host.innerHTML = html;
}

function dpSetReload(canReload) {
  const btn = document.getElementById("dp-btn-reload");
  if (!btn) return;
  btn.disabled = !canReload;
  btn.title    = canReload ? "" : "This unit does not support reload";
  btn.style.opacity = canReload ? "1" : "0.35";
}

async function dpRenderPinZone(unit) {
  const row = document.getElementById("dp-pin-row");
  if (!row) return;
  row.innerHTML = '<span style="font-family:var(--sans);font-size:var(--fs-sm);color:#fff">…</span>';

  const d = await api("/api/pinned");
  if (!d) { row.innerHTML = ""; return; }

  const isPinned = d.pinned_units.includes(unit);
  const groups   = d.groups;

  row.innerHTML = "";

  if (isPinned) {
    const btn = document.createElement("button");
    btn.className = "btn btn-red btn-sm";
    btn.textContent = "✕ Unpin";
    btn.onclick = () => dpUnpinService(unit, btn);
    row.appendChild(btn);
    const note = document.createElement("span");
    note.style.cssText = "font-family:var(--sans);font-size:var(--fs-xs);color:#fff;margin-left:.4rem";
    note.textContent = "Remove from pinned list";
    row.appendChild(note);
  } else {
    const sel = document.createElement("select");
    sel.title = "Choose group";
    groups.forEach(g => {
      const opt = document.createElement("option");
      opt.value = g; opt.textContent = g;
      sel.appendChild(opt);
    });
    const newOpt = document.createElement("option");
    newOpt.value = "__new__"; newOpt.textContent = "＋ New group…";
    sel.appendChild(newOpt);

    const btn = document.createElement("button");
    btn.className = "btn btn-lime btn-sm";
    btn.style.cssText = "color:var(--lime);border-color:var(--lime-dim)";
    btn.textContent = "📌 Pin";
    btn.onclick = () => dpPinService(unit, sel, btn);

    row.appendChild(sel);
    row.appendChild(btn);
  }
}

async function dpPinService(unit, sel, btn) {
  let group = sel.value;
  if (group === "__new__") {
    group = prompt("New group name:");
    if (!group || !group.trim()) return;
    group = group.trim();
  }
  if (btn) btn.disabled = true;
  const d = await api("/api/pinned", "POST", {action: "pin", unit, group});
  if (btn) btn.disabled = false;
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "Pinned" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) {
    dpRenderPinZone(unit);
    if (typeof loadOverview === "function") setTimeout(loadOverview, 400);
  }
}

async function dpUnpinService(unit, btn) {
  if (!await confirm(`Remove  ${unit}  from the pinned list?`)) return;
  if (btn) btn.disabled = true;
  const d = await api("/api/pinned", "POST", {action: "unpin", unit});
  if (btn) btn.disabled = false;
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "Unpinned" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) {
    dpRenderPinZone(unit);
    if (typeof loadOverview === "function") setTimeout(loadOverview, 400);
  }
}

async function dpSvcAction(action, unit) {
  
  if (action === "stop") {
    if (!await confirm(`Stop  ${unit || _dpUnit}?`)) return;
  } else if (action === "disable") {
    if (!await confirm(`Disable  ${unit || _dpUnit}  at boot?`)) return;
  } else if (action === "mask") {
    if (!await confirm(`Mask  ${unit || _dpUnit}?  This prevents it from starting.`)) return;
  }
  const url  = "/api/svc";
  const body = action === "reload_daemon"
    ? {action: "reload_daemon"}
    : {action: action, unit: unit};

  const d = await api(url, "POST", body);
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "OK" : "Failed"), d.ok ? "ok" : "err");

  if (d.ok) {
    if (d.async) {
      [3000, 8000, 16000, 28000].forEach(delay => setTimeout(async () => {
        await dpRefreshHeader();
        if (typeof loadOverview === "function") loadOverview();
      }, delay));
      [3500, 8500, 16500, 28500].forEach(delay => setTimeout(() => dpLoadStatus(), delay));
    } else {
      setTimeout(async () => {
        await dpRefreshHeader();
        if (typeof loadOverview === "function") loadOverview();
      }, 700);
      setTimeout(() => dpLoadStatus(), 1200);
    }
  }
}

async function dpLoadStatus() {
  if (!_dpUnit) return;
  _dpActiveView = "status";

  const out = document.getElementById("dpanel-output");
  out.innerHTML = '<span class="dp-out-dim">Loading…</span>';

  const d = await api(
    `/api/services/detail?unit=${encodeURIComponent(_dpUnit)}&view=status&lines=50`
  );
  if (!d || !d.ok) {
    out.innerHTML = `<span class="dp-out-fail">Error: ${esc(d?.message || "request failed")}</span>`;
    return;
  }
  out.innerHTML = "";
  (d.output || "").split("\n").forEach(line => {
    const div = document.createElement("div");
    const lower = line.toLowerCase();
    if (lower.includes("failed") || lower.includes("error") || lower.includes("fatal")) {
      div.className = "dp-out-fail";
    } else if (lower.includes("warn") || lower.includes("notice")) {
      div.className = "dp-out-warn";
    } else if (lower.includes("started") || lower.includes("active") ||
               lower.includes("loaded") || lower.match(/\bok\b/)) {
      div.className = "dp-out-ok";
    } else {
      div.className = "dp-out-dim";
    }
    div.textContent = line || "\u00a0";
    out.appendChild(div);
  });
}

function dotClass(state, enabled) {
  return dotColorClass(state, enabled);
}

let _ptProto      = "both";

window.loadTab_ports = function() {
  if (!_enabledTabSet.has("ports")) return;
  clearInterval(_ptRefreshTimer);
  loadPorts();
  _ptRefreshTimer = setInterval(loadPorts, 15_000);
};

let _jpUnit  = "";
let _jpFile  = null;
let _jpLines = 200;
let _jpRaw   = "";
let _jpFilteredText = "";

window.loadTab_journal = function() { loadJournalList(); dvlLoad(); };

let _dvlSources = [];
let _dvlAgent = null;
let _dvlAgentAt = 0;

function _dvlSize(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(n < 10240 ? 1 : 0)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

function _dvlAge(t) {
  const s = Math.max(0, Math.floor(Date.now() / 1000) - t);
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

async function dvlLoad() {
  const d = await api("/api/logs/list");
  _dvlSources = (d && d.ok) ? (d.sources || []) : [];
  renderDvlList(d && d.ok ? null : ((d && d.message) || "Could not read the log list"));
  dvlAgentFetch();
}

function renderDvlList(err) {
  const body = document.getElementById("dvl-body");
  if (!body) return;
  body.innerHTML = "";
  if (err || !_dvlSources.length) {
    body.innerHTML = `<div class="stub-panel" style="min-height:60px">${esc(err || "No DV gateway logs found on this node.")}</div>`;
    return;
  }
  let group = "";
  _dvlSources.forEach((e, i) => {
    if (e.group !== group) {
      group = e.group;
      const g = document.createElement("div");
      g.className = "dvl-group";
      g.textContent = group;
      body.appendChild(g);
    }
    if (e.kind === "none") {
      const n = document.createElement("div");
      n.className = "dvl-note";
      n.textContent = e.note || "no log";
      body.appendChild(n);
      return;
    }
    const sub = e.kind === "file"
      ? `${_dvlSize(e.size || 0)} · ${e.mtime ? _dvlAge(e.mtime) : ""}${e.size ? "" : " · empty"}`
      : (e.note || "systemd journal");
    const row = document.createElement("div");
    row.className = "dvl-row";
    row.innerHTML =
      `<div class="dvl-name" title="${esc(e.path || e.unit || "")}">${esc(e.label)}` +
      `<div class="dvl-sub">${esc(sub)}</div></div>` +
      `<button class="jl-btn" onclick="dvlOpen(${i})">▤ Open</button>` +
      `<button class="jl-btn" onclick="dvlCopy(${i})">⎘ Copy</button>`;
    body.appendChild(row);
  });
}

function dvlOpen(i) {
  const e = _dvlSources[i];
  if (!e) return;
  if (e.kind === "journal") openJournalPopup(e.unit);
  else openLogPopup(e.id, e.label);
}

async function _dvlReadText(e) {
  const d = await api(`/api/logs/read?id=${encodeURIComponent(e.id)}&lines=200`);
  if (!d || !d.ok) throw new Error((d && d.message) || "Could not read the log");
  const shown = d.text ? d.text.split("\n").length : 0;
  const where = e.kind === "journal" ? `journal: ${e.unit} (local time)` : `${d.path || e.label} (UTC)`;
  const of = d.total >= 0 ? ` of ${d.total.toLocaleString()}` : "";
  return `== ${where} · last ${shown}${of} lines ==\n${d.text || ""}\n`;
}

function dvlCopy(i) {
  const e = _dvlSources[i];
  if (!e) return;
  _copyFetched(_dvlReadText(e));
}

async function dvlAgentFetch() {
  const btn = document.getElementById("dvl-agent-btn");
  const d = await api("/api/logs/agent");
  if (!d || !d.ok) { _dvlAgent = null; if (btn) btn.textContent = "⎘ Copy for agent"; return null; }
  _dvlAgent = d.text || "";
  _dvlAgentAt = Date.now();
  if (btn) btn.textContent = `⎘ Copy for agent · ${_dvlSize(d.bytes || _dvlAgent.length)}`;
  return _dvlAgent;
}

function dvlAgentCopy() {
  if (_dvlAgent && Date.now() - _dvlAgentAt < 60000) {
    _copyWithVerify(_dvlAgent);
    return;
  }
  _copyFetched(dvlAgentFetch().then(t => {
    if (!t) throw new Error("Could not build the log bundle");
    return t;
  }));
}

async function dvlAgentDownload() {
  let text = _dvlAgent && Date.now() - _dvlAgentAt < 60000 ? _dvlAgent : await dvlAgentFetch();
  if (!text) { toast("Could not build the log bundle", "err"); return; }
  const stamp = new Date().toISOString().replace(/[:T]/g, "-").slice(0, 19);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], {type: "text/plain"}));
  a.download = `dv-gateway-logs-${stamp}.txt`;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

async function loadJournalList() {
  const d = await api("/api/journal/list");
  if (!d) return;
  renderJournalList(d.services || []);
}

function renderJournalList(services) {
  const body = document.getElementById("jl-body");
  if (!body) return;
  body.innerHTML = "";

  if (!services.length) {
    body.innerHTML =
      '<div class="stub-panel" style="min-height:60px">No services found.</div>';
    return;
  }

  services.forEach(svc => {
    const row = document.createElement("div");
    row.className = "jl-row";
    row.onclick   = e => {
      if (e.target.classList.contains("jl-btn")) return;
      openJournalPopup(svc.unit);
    };

    row.innerHTML =
      `<span class="dot ${dotClass(svc.state, svc.enabled)}"></span>` +
      `<span class="jl-name">${esc(svc.unit.replace(".service",""))}</span>` +
      `<span class="jl-state ${stateClass(svc.state)}">${esc(svc.state)}</span>` +
      `<button class="jl-btn" onclick="openJournalPopup('${esc(svc.unit)}')">▤ Journal</button>`;
    body.appendChild(row);
  });
}

function _jpSvcButtons(show) {
  ["jp-restart-btn", "jp-start-btn"].forEach(id => {
    const b = document.getElementById(id);
    if (b) b.style.display = show ? "" : "none";
  });
}

function _jpSetInfo(text) {
  const el = document.getElementById("jp-info");
  if (!el) return;
  el.textContent = text || "";
  el.hidden = !text;
}

async function openLogPopup(id, label) {
  _jpUnit = "";
  _jpFile = {id, label};
  _jpSvcButtons(false);
  _jpSetInfo("");
  const title = document.getElementById("jp-title");
  if (title) title.textContent = `▤ ${label} — Log`;
  document.getElementById("jp-overlay").classList.add("open");
  document.getElementById("jp-grep").value = "";
  jpSetLinesUI(_jpLines);
  await jpRefresh();
}

async function openJournalPopup(unit) {
  _jpUnit = unit;
  _jpFile = null;
  _jpSvcButtons(true);
  _jpSetInfo("");
  const title = document.getElementById("jp-title");
  if (title) title.textContent = `▤ ${unit.replace(".service","")} — Journal`;

  document.getElementById("jp-overlay").classList.add("open");
  document.getElementById("jp-grep").value = "";

  jpSetLinesUI(_jpLines);

  await jpRefresh();
}

function closeJournalPopup() {
  document.getElementById("jp-overlay").classList.remove("open");
  _jpUnit = "";
  _jpFile = null;
}

function jpOverlayClick(e) {
  if (e.target === document.getElementById("jp-overlay")) closeJournalPopup();
}

async function jpCopy() {
  if (!_jpFilteredText) { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(_jpFilteredText);
}

async function jpRefresh() {
  if (_jpFile) return jpRefreshFile();
  if (!_jpUnit) return;
  const body = document.getElementById("jp-body");
  if (body) body.textContent = "Loading…";

  const d = await api(
    `/api/journal/fetch?unit=${encodeURIComponent(_jpUnit)}&lines=${_jpLines}`
  );
  if (!d) {
    if (body) body.innerHTML = '<span class="jp-err">Request failed</span>';
    return;
  }
  if (!d.ok) {
    if (body) body.innerHTML =
      `<span class="jp-err">${esc(d.message || "Journal fetch failed")}</span>`;
    _jpRaw = "";
    return;
  }

  _jpRaw = d.output || "";
  jpApplyGrep();
}

async function jpRefreshFile() {
  const body = document.getElementById("jp-body");
  if (body) body.textContent = "Loading…";
  const want = _jpLines >= 2000 ? "all" : String(_jpLines);
  const d = await api(`/api/logs/read?id=${encodeURIComponent(_jpFile.id)}&lines=${want}`);
  if (!d || !d.ok) {
    if (body) body.innerHTML =
      `<span class="jp-err">${esc((d && d.message) || "Request failed")}</span>`;
    _jpRaw = "";
    _jpFilteredText = "";
    _jpSetInfo("");
    return;
  }
  _jpRaw = d.text || "";
  const shown = _jpRaw ? _jpRaw.split("\n").length : 0;
  const tz = d.tz === "UTC" ? "Times in UTC" : "Times in local time";
  let info = `${tz} · ${d.path || d.label}`;
  if (d.total >= 0) info += ` · showing ${shown.toLocaleString()} of ${d.total.toLocaleString()} lines`;
  if (want === "all" && d.truncated) info += " · cut to the last 2 MB";
  _jpSetInfo(info);
  jpApplyGrep();
}

function jpApplyGrep() {
  const term = (document.getElementById("jp-grep")?.value || "").trim();
  const body = document.getElementById("jp-body");
  if (!body) return;

  const lines = _jpRaw.split("\n");
  const filtered = term
    ? lines.filter(l => l.toLowerCase().includes(term.toLowerCase()))
    : lines;

  if (!filtered.length || (filtered.length === 1 && !filtered[0])) {
    body.innerHTML = '<span class="jp-dim">-- No entries --</span>';
    _jpFilteredText = "";
    return;
  }

  _jpFilteredText = filtered.join("\n");
  body.innerHTML = "";
  filtered.forEach(line => {
    const div = document.createElement("div");
    const lower = line.toLowerCase();
    if (lower.includes("error") || lower.includes("failed") || lower.includes("fatal")) {
      div.className = "jp-err";
    } else if (lower.includes("warn") || lower.includes("notice")) {
      div.className = "jp-warn";
    } else if (lower.includes("started") || lower.includes("active") ||
               lower.includes("loaded") || lower.match(/\bok\b/)) {
      div.className = "jp-ok";
    } else if (line.startsWith("--")) {
      div.className = "jp-dim";
    } else {
      div.className = "jp-ts";
    }
    div.textContent = line || "\u00a0";
    body.appendChild(div);
  });

  body.scrollTop = body.scrollHeight;
}

function jpSetLines(n) {
  _jpLines = n;
  jpSetLinesUI(n);
  jpRefresh();
}

function jpSetLinesUI(n) {
  const map = {50: "jp-ln-50", 200: "jp-ln-200", 2000: "jp-ln-all"};
  Object.entries(map).forEach(([k, id]) => {
    const btn = document.getElementById(id);
    if (btn) btn.classList.toggle("on", parseInt(k) === n);
  });
}

let _jpGrepTimer = null;
function jpGrepChanged() {
  clearTimeout(_jpGrepTimer);
  _jpGrepTimer = setTimeout(jpApplyGrep, 250);
}

async function jpSvcAction(action) {
  if (!_jpUnit) return;
  const d = await api("/api/svc", "POST", {action, unit: _jpUnit});
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "OK" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) {
    setTimeout(jpRefresh, 1500);
    if (typeof loadJournalList === "function") setTimeout(loadJournalList, 1000);
  }
}


let _edDirty = false;

window.loadTab_edit = function() { edReload(); edAslDvsLoad(); };

let _edAslOpen = false;

let _edPinnedOpen = false;

async function edAslDvsLoad() {
  if (!_edAslOpen) return;

  const da = await api("/api/asterisk/files?all=1");
  if (da) renderAstFiles(da.files || [], da.dir || "/etc/asterisk",
                          "ed-ast-file-body", true);
  const dm = await api("/api/allmon3/files?all=1");
  if (dm) renderAllmon3Files(dm.files || [], "ed-allmon3-file-body", true);
  const dd = await api("/api/dvswitch/files?all=1");
  if (dd) renderDvsFiles(dd.files || [], "ed-dvs-file-body", true);

  const body = document.getElementById("ed-asl-body");
  if (body && _edAslOpen) body.style.maxHeight = "none";
}

async function edToggleFileHidden(filename, isHidden) {
  const cfg = await api("/api/config");
  if (!cfg || !cfg.ok) { toast("Failed to load config", "err"); return; }

  const current = new Set(
    (cfg.asldvs?.hidden_files || "").split(",").map(s => s.trim()).filter(Boolean)
  );

  if (isHidden) {
    current.delete(filename);
  } else {
    current.add(filename);
  }

  const d = await api("/api/config", "POST",
    {"asldvs.hidden_files": [...current].join(",")});
  if (!d || !d.ok) {
    toast(d?.message || "Save failed", "err"); return;
  }

  toast(isHidden ? `${filename} shown` : `${filename} hidden`, "ok", 2000);

  edAslDvsLoad();
  if (typeof loadAstFiles     === "function") loadAstFiles();
  if (typeof loadAllmon3Files === "function") loadAllmon3Files();
  if (typeof loadDvsFiles     === "function") loadDvsFiles();
}

const ED_FIELDS = [
  {id: "ed-callsign",  key: "identity.callsign"},
  {id: "ed-node",      key: "identity.node"},
  {id: "ed-label",     key: "identity.label"},
  {id: "ed-port",      key: "server.port"},
  {id: "ed-host",      key: "server.host"},
  {id: "ed-cpu-warn",  key: "thresholds.cpu_warn_pct"},
  {id: "ed-rss-warn",  key: "thresholds.rss_warn_mb"},
  {id: "ed-nr-warn",   key: "thresholds.nr_warn"},
  {id: "ed-nr-crit",   key: "thresholds.nr_crit"},
];

const ED_LOCKED_TABS = ["overview", "edit"];

function edCountPinned() {
  const ta  = document.getElementById("ed-pinned");
  const cnt = document.getElementById("ed-pinned-count");
  if (!ta || !cnt) return;
  const n = ta.value.split("\n").filter(l => {
    const t = l.trim();
    return t && !t.startsWith("#") && !t.startsWith("__GROUP__");
  }).length;
  cnt.textContent = `${n} service entr${n === 1 ? "y" : "ies"}`;
}

let _pageVisible = document.visibilityState === "visible";

document.addEventListener("visibilitychange", () => {
  if (_pausedByNavigation) return;
  
  _pageVisible = document.visibilityState === "visible";
  if (_pageVisible) {
    startStatusPolling();
    console.info("[sysmon] Polling resumed (page visible)");
  } else {
    stopStatusPolling();
    stopTabPolling("ports");
    stopTabPolling("services");
    console.info("[sysmon] Polling paused (page hidden)");
  }
});

document.addEventListener("DOMContentLoaded", () => {
  const ta = document.getElementById("ed-pinned");
  if (ta) ta.addEventListener("input", edCountPinned);
});

async function _copyWithVerify(src) {
  let wrote = false;
  try {
    await navigator.clipboard.writeText(src);
    wrote = true;
  } catch {
    const tmp = document.createElement("textarea");
    tmp.value = src;
    tmp.style.position = "fixed";
    tmp.style.left = "-9999px";
    tmp.setAttribute("readonly", "");
    document.body.appendChild(tmp);
    tmp.focus();
    tmp.setSelectionRange(0, tmp.value.length);
    try {
      document.execCommand("copy");
      wrote = true;
    } catch { wrote = false; }
    document.body.removeChild(tmp);
  }
  if (!wrote) { toast("Copy failed", "err"); return; }
  await _clipVerify(src);
}

async function _copyFetched(textPromise) {
  textPromise.catch(() => {});
  if (window.ClipboardItem && navigator.clipboard && navigator.clipboard.write) {
    try {
      const blob = textPromise.then(t => new Blob([t], {type: "text/plain"}));
      await navigator.clipboard.write([new ClipboardItem({"text/plain": blob})]);
      await _clipVerify(await textPromise);
      return;
    } catch (e) {
      try { await textPromise; } catch (e2) { toast(e2.message || "Copy failed", "err"); return; }
    }
  }
  let text = "";
  try { text = await textPromise; } catch (e) { toast(e.message || "Copy failed", "err"); return; }
  if (!text) { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(text);
}

async function _clipVerify(src) {
  try {
    const check = await navigator.clipboard.readText();
    if (check === src) {
      toast("Copied ✓", "ok", 2000);
    } else {
      await alertModal(
        `⚠ Clipboard copy may be incomplete (${check.length} of ${src.length} ` +
        `characters). This can happen on some mobile browsers with large ` +
        `files — try again, use a Download button where there is one, or a desktop browser.`
      );
    }
  } catch {
    toast("Copied — could not confirm on this browser", "info", 3000);
  }
}

let _modalResolve = null;

function confirm(msg) {
  
  return new Promise(resolve => {
    _modalResolve = resolve;
    document.getElementById("modal-msg").textContent = msg;
    document.getElementById("modal-overlay").classList.add("open");
  });
}

function modalCancel() {
  document.getElementById("modal-overlay").classList.remove("open");
  _resetModalAlertUI();
  if (_modalResolve) { _modalResolve(false); _modalResolve = null; }
}

function modalConfirm() {
  document.getElementById("modal-overlay").classList.remove("open");
  _resetModalAlertUI();
  if (_modalResolve) { _modalResolve(true); _modalResolve = null; }
}

let _modalIsAlert = false;

function alertModal(msg) {
  _modalIsAlert = true;
  const cancelBtn = document.querySelector("#modal-btns .btn-muted");
  const okBtn = document.getElementById("modal-ok");
  if (cancelBtn) cancelBtn.style.display = "none";
  if (okBtn) okBtn.textContent = "OK";
  return confirm(msg);
}

function _resetModalAlertUI() {
  if (!_modalIsAlert) return;
  const cancelBtn = document.querySelector("#modal-btns .btn-muted");
  const okBtn = document.getElementById("modal-ok");
  if (cancelBtn) cancelBtn.style.display = "";
  if (okBtn) okBtn.textContent = "Confirm";
  _modalIsAlert = false;
}
document.addEventListener("DOMContentLoaded", () => {
  const ok = document.getElementById("modal-ok");
  if (ok) ok.addEventListener("click", modalConfirm);
  const ov = document.getElementById("modal-overlay");
  if (ov) ov.addEventListener("click", e => {
    if (e.target === ov) modalCancel();
  });
});

async function postAction(url, action, btn, confirmMsg) {
  if (confirmMsg) {
    const ok = await confirm(confirmMsg);
    if (!ok) return;
  }
  if (btn) btn.disabled = true;
  const d = await api(url, "POST", {action: action});
  if (btn) btn.disabled = false;
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "OK" : "Failed"), d.ok ? "ok" : "err");
}

let _pausedByNavigation = false;

function pauseAllPolling() {
  _pausedByNavigation = true;
  sessionStorage.setItem("sysmon_paused_by_nav", "1");
  stopStatusPolling();
  stopTabPolling("ports");
  stopTabPolling("services");
  stopTabPolling("sdcard");
  stopTabPolling("phone");
  stopTabPolling("reg");
  console.info("[sysmon] All polling paused (navigating to dashboard)");
}

function resumeAllPolling() {
  _pausedByNavigation = false;
  startStatusPolling();
  console.info("[sysmon] All polling resumed");
}


let _ufUnit = "";

async function openUnitFileEditor(unit) {
  _ufUnit = unit;

  document.getElementById("uf-title").textContent    = `✎ ${unit.replace(".service","")}`;
  document.getElementById("uf-path").textContent     = "Loading…";
  document.getElementById("uf-textarea").value       = "";
  document.getElementById("uf-status").textContent   = "";
  document.getElementById("uf-promoted-bar").classList.remove("show");
  document.getElementById("uf-save-btn").disabled    = true;
  document.getElementById("uf-restart-btn").disabled = true;
  findReset("uf");
  document.getElementById("uf-overlay").classList.add("open");

  const d = await api(`/api/unit_file?unit=${encodeURIComponent(unit)}`);
  if (!d || !d.ok) {
    document.getElementById("uf-path").textContent   = d?.message || "Failed to load";
    document.getElementById("uf-textarea").value     = "";
    ufSetStatus(d?.message || "Error loading unit file", false);
    return;
  }

  document.getElementById("uf-path").textContent     = d.read_path;
  document.getElementById("uf-textarea").value       = d.content;
  document.getElementById("uf-save-btn").disabled    = !d.writable;
  document.getElementById("uf-restart-btn").disabled = false;
  ufSetStatus(d.writable ? "" : "Read-only (not running as root)");

  if (d.promoted) {
    document.getElementById("uf-promoted-bar").classList.add("show");
    document.getElementById("uf-path").textContent =
      `${d.path}  (override — original: ${d.read_path})`;
  }
}

function closeUnitFileEditor() {
  document.getElementById("uf-overlay").classList.remove("open");
  const rb = document.getElementById("uf-restart-btn");
  if (rb) rb.style.display = "";
  _ufUnit = "";
}

function ufOverlayClick(e) {
  if (e.target === document.getElementById("uf-overlay")) closeUnitFileEditor();
}

async function ufCopy() {
  const ta = document.getElementById("uf-textarea");
  if (!ta || !ta.value) { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(ta.value);
}

function ufSetStatus(msg, ok) {
  const el = document.getElementById("uf-status");
  if (!el) return;
  el.textContent = msg;
  el.style.color = ok === true  ? "var(--green)"
                 : ok === false ? "var(--red)"
                 : "#3a5278";
}

async function _ufSaveOrig() {
  if (!_ufUnit) return;
  const content = document.getElementById("uf-textarea").value;
  const btn     = document.getElementById("uf-save-btn");
  if (btn) btn.disabled = true;
  ufSetStatus("Saving…");

  const d = await api("/api/unit_file", "POST", {unit: _ufUnit, content});
  if (btn) btn.disabled = false;

  if (!d || !d.ok) {
    ufSetStatus(d?.message || "Save failed", false);
    toast(d?.message || "Save failed", "err");
    return;
  }

  const detail = d.reload_ok ? "daemon-reload OK" : "saved (daemon-reload failed)";
  ufSetStatus(`Saved ✓  —  ${detail}`, d.reload_ok);
  toast(d.message, d.reload_ok ? "ok" : "err");

  if (d.path) document.getElementById("uf-path").textContent = d.path;
  document.getElementById("uf-promoted-bar").classList.remove("show");
}

async function ufRestart() {
  if (!_ufUnit) return;
  if (!await confirm(`Restart ${_ufUnit} to apply unit file changes?`)) return;
  const d = await api("/api/svc", "POST", {action: "restart", unit: _ufUnit});
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "Restarted" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) { d.async ? _svcPollAfterRestart() : setTimeout(loadOverview, 800); }
}

async function ufReloadDaemon() {
  ufSetStatus("Reloading daemon…");
  const d = await api("/api/svc", "POST", {action: "reload_daemon"});
  if (!d) { ufSetStatus("Server unreachable", false); return; }
  ufSetStatus(d.message || (d.ok ? "Daemon reloaded" : "Failed"), d.ok);
}

window.loadTab_asldvs = function() { loadAstFiles(); loadAllmon3Files(); loadDvsFiles(); loadDstarGw(); loadNodeListen(); };

// v6.13.66: D-Star -- ircDDBGateway card (read-only checks on /etc/ircddbgateway
// for the dashboard's gateway linking).  Edit opens the DVSwitch file editor.
let _dstarGw = null;
async function loadDstarGw() {
  const d = await api("/api/dstar-gw");
  if (!d) return;
  _dstarGw = d;
  _dvsmSetBadge("dstargw-badge", d.status, d.badge);
  _renderCompatTable("dstargw-body", d.checks || []);
}
async function dstarGwRestart() {
  if (!await confirm("Restart ircddbgatewayd? Any D-Star link drops.")) return;
  const d = await api("/api/dstar-gw", "POST", {action: "restart"});
  if (!d || !d.ok) { toast(d?.message || "Restart failed", "err"); return; }
  toast("ircddbgatewayd restarted", "ok");
  setTimeout(loadDstarGw, 1500);
}
function dstarGwEdit() {
  if (_dstarGw && _dstarGw.present === false) { toast("/etc/ircddbgateway not found", "warn"); return; }
  openDvsEditor("ircddbgateway");
}
function dstarGwCopy(btn) {
  if (!_dstarGw) return;
  const lines = [`D-Star — ircDDBGateway (${_dstarGw.path}): ${_dstarGw.badge}`];
  (_dstarGw.checks || []).forEach(c => {
    lines.push(`[${String(c.status || "").toUpperCase()}] ${c.enables}: ${c.key}`);
    if (c.fix) lines.push(`    -> ${c.fix}`);
  });
  dvsmCopy(btn, lines.join("\n"));
}

let _nodeListen = null;
async function loadNodeListen() {
  const d = await api("/api/nodelisten");
  if (!d) return;
  _nodeListen = d;
  const acts = document.getElementById("nodelisten-actions");
  const cl = document.getElementById("nodelisten-clients");
  if (!d.installed) {
    _dvsmSetBadge("nodelisten-badge", "info", "NOT INSTALLED");
    document.getElementById("nodelisten-body").innerHTML =
      `<div class="stub-panel" style="min-height:40px">Node Talker is not installed on this node.</div>`;
    if (cl) cl.innerHTML = "";
    if (acts) acts.style.display = "none";
    return;
  }
  if (acts) acts.style.display = "flex";
  _dvsmSetBadge("nodelisten-badge", d.status, d.badge);
  _renderCompatTable("nodelisten-body", d.checks || []);
  const sub = document.getElementById("nodelisten-sub");
  if (sub) sub.textContent = `port ${d.port}` + (d.version ? ` · v${d.version}` : "") +
    (d.main ? ` · node ${d.main}` : "") + " · listen ports · connections";
  const open = document.getElementById("nodelisten-open");
  if (open) open.href = `${d.scheme || "https"}://${location.hostname}:${d.port}/`;
  const ul = document.getElementById("nodelisten-unlink");
  if (ul) ul.style.display = d.tx ? "" : "none";
  if (!cl) return;
  const rows = (d.clients || []).map(c => {
    const where = c.local ? "this Pi (local or tunnel)" : c.lan ? "LAN" : "internet";
    return `<tr><td class="dvsm-ct-key">${_esc(c.ip)}</td>` +
      `<td class="dvsm-ct-enables">${_esc(where)} · ${c.conns} connection${c.conns === 1 ? "" : "s"}</td>` +
      `<td class="dvsm-ct-badge"><button class="btn btn-sm" style="color:var(--red);border-color:var(--red-dim)" ` +
      `data-ip="${_esc(c.ip)}" onclick="nodeListenDisconnect(this.dataset.ip)">Disconnect</button></td></tr>`;
  }).join("");
  cl.innerHTML = `<span class="dvsm-sec-lbl">Connected browsers (${(d.clients || []).length})</span>` +
    (rows ? `<table class="dvsm-compat-tbl">${rows}</table>`
          : `<div class="stub-panel" style="min-height:30px">No one is connected.</div>`);
}
async function nodeListenRestart() {
  if (!await confirm("Restart Node Talker? Everyone listening is dropped and their pages reconnect.")) return;
  const d = await api("/api/nodelisten", "POST", {action: "restart"});
  if (!d || !d.ok) { toast(d?.message || "Restart failed", "err"); return; }
  toast("Node Talker restarted", "ok");
  setTimeout(loadNodeListen, 2500);
}
async function nodeListenDisconnect(ip) {
  if (!await confirm(`Disconnect ${ip} from Node Talker? Their page tries again in 3 s if they are still listening.`)) return;
  const d = await api("/api/nodelisten", "POST", {action: "disconnect", ip});
  if (!d || !d.ok) { toast(d?.message || "Disconnect failed", "err"); loadNodeListen(); return; }
  toast(d.message || "Disconnected", "ok");
  setTimeout(loadNodeListen, 800);
}
async function nodeListenUnlink() {
  if (!await confirm("Unlink node 1921 (push-to-talk) from the node? Node Talker links it again within 20 s while it runs.")) return;
  const d = await api("/api/nodelisten", "POST", {action: "unlink"});
  if (!d || !d.ok) { toast(d?.message || "Unlink failed", "err"); return; }
  toast(d.message || "Unlinked", "ok");
  setTimeout(loadNodeListen, 1500);
}
function nodeListenCopy(btn) {
  if (!_nodeListen) return;
  const lines = [`Node Talker (port ${_nodeListen.port || "-"}): ${_nodeListen.badge}`];
  (_nodeListen.checks || []).forEach(c => {
    lines.push(`[${String(c.status || "").toUpperCase()}] ${c.enables}: ${c.key}`);
    if (c.fix) lines.push(`    -> ${c.fix}`);
  });
  (_nodeListen.clients || []).forEach(c => lines.push(`Connected: ${c.ip} (${c.lan ? "LAN" : "internet"}, ${c.conns})`));
  dvsmCopy(btn, lines.join("\n"));
}

let _regRefreshTimer = null;
const _REG_HTTP_IDS = {body: "reg-http-body", meta: "reg-http-meta", status: "reg-http-status"};
const _REG_IAX_IDS  = {body: "reg-iax-body",  meta: "reg-iax-meta",  status: "reg-iax-status"};

window.loadTab_reg = async function() {
  if (!_enabledTabSet.has("reg")) return;
  if (!_regRefreshTimer) _regRefreshTimer = setInterval(() => {
    if (document.visibilityState === "visible" && !_pausedByNavigation) loadTab_reg();
  }, 15000);
  const [dHttp, dIax] = await Promise.all([api("/api/reg/http"), api("/api/reg/iax")]);

  if (!dHttp || !dHttp.ok) { _regShowUnreachable(_REG_HTTP_IDS); }
  else                     { renderRegChecks(dHttp.checks, dHttp.status, _REG_HTTP_IDS); }

  if (!dIax || !dIax.ok) { _regShowUnreachable(_REG_IAX_IDS); }
  else                   { renderRegChecks(dIax.checks, dIax.status, _REG_IAX_IDS); }
};

function regJump() {
  if (!_enabledTabSet.has("reg")) return;
  switchTab("reg", "120,180,255");
}

function renderRegHeader(sm) {
  const el = document.getElementById("s-reg");
  if (!el) return;
  if (!sm) {
    el.textContent = "…"; el.className = "sv";
    el.title = "AllStarLink registration — not checked yet";
    return;
  }
  const age = s => s < 60 ? s + "s" : s < 3600 ? Math.floor(s / 60) + "m" : Math.floor(s / 3600) + "h";
  const map = {
    ok:   ["REG",      "sv ok",   "Registered"],
    wait: ["WAIT",     "sv warn", "Waiting for registration"],
    fail: ["NOT REG",  "sv hot",  "Not registered"],
    down: ["ASL DOWN", "sv hot",  "Asterisk isn't answering — ASL3 not running yet"],
    none: ["—",        "sv",      "No HTTP registration configured (see the Reg tab)"],
  };
  const m = map[sm.state] || ["?", "sv", sm.state];
  el.textContent = m[0] + (sm.state === "ok" || sm.state === "none" ? "" : " " + age(sm.age_s));
  el.className   = m[1];
  const lines = [m[2], `In this state since ${sm.since_text}`];
  Object.keys(sm.nodes || {}).forEach(n => lines.push(`Node ${n}: ${sm.nodes[n]}` +
    ((sm.perceived || {})[n] ? ` as ${sm.perceived[n]}` : "")));
  if (sm.error) lines.push(sm.error);
  lines.push(`Checked ${sm.checked_age_s}s ago`);
  el.title = lines.join("\n");
}
let _phData = {};

window.phCopyCard = async function(pfx) {
  const text = phCardText(pfx);
  if (!text.trim()) { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(text);
};

const _rtResult = {};
window.rtOut = async function() {
  const b = document.getElementById("rt-out-btn"); if (b) b.disabled = true;
  const box = document.getElementById("rt-out-box");
  if (box) box.innerHTML = '<div class="stub-panel" style="min-height:40px">Testing…</div>';
  const d = await api("/api/phone/routertest", "POST", {part: "out"});
  if (b) b.disabled = false;
  if (!d || !d.ok) { if (box) box.innerHTML = '<div class="stub-panel">Test failed: ' + _esc((d && d.message) || "no reply") + '</div>'; return; }
  rtChecks("rt-out-box", "out", d.checks);
};
window.rtAudio = async function() {
  const b = document.getElementById("rt-audio-btn"); if (b) b.disabled = true;
  const box = document.getElementById("rt-audio-box");
  if (box) box.innerHTML = '<div class="stub-panel" style="min-height:40px">Counting packets…</div>';
  const a = await api("/api/phone/routertest", "POST", {part: "audio"});
  await new Promise(r => setTimeout(r, 4000));
  const z = await api("/api/phone/routertest", "POST", {part: "audio"});
  if (b) b.disabled = false;
  if (!a || !a.ok || !z || !z.ok) { if (box) box.innerHTML = '<div class="stub-panel">Check failed</div>'; return; }
  const checks = [];
  if (!z.calls.length) {
    checks.push({id: "nocall", title: "Call audio", status: "info", value: "no call is up",
                 note: "Start a Test call on the dashboard Phone tab, then press Check audio now"});
  }
  z.calls.forEach(c => {
    const p = (a.calls || []).find(x => x.channel === c.channel) || c;
    const sec = Math.max(1, (z.t - a.t));
    const rx = Math.round((c.rx - p.rx) / sec), tx = Math.round((c.tx - p.tx) / sec);
    const lossy = c.rx_pct >= 5 || c.tx_pct >= 5;
    let st = "pass", note = "Audio is getting out and coming back in";
    if (rx <= 0 && tx <= 0) { st = "fail"; note = "No audio either way -- the call may be on hold or the audio ports are blocked"; }
    else if (rx <= 0) { st = "fail"; note = "Audio goes out but none comes back in -- check the router forward and Pi firewall for the audio ports"; }
    else if (tx <= 0) { st = "warn"; note = "Audio comes in but none goes out -- normal on a simplex node while nobody is talking; key up and check again"; }
    else if (lossy) { st = "warn"; note = "Packets are being lost -- expect choppy audio. Check WiFi signal and internet load"; }
    checks.push({id: "a-" + c.channel, title: c.channel + " (" + c.codec + ", up " + c.uptime + ")", status: st,
                 value: `in ${rx}/s · out ${tx}/s · lost in ${c.rx_pct}% out ${c.tx_pct}% · jitter ${c.rx_jitter}/${c.tx_jitter}`,
                 note: note});
  });
  rtChecks("rt-audio-box", "audio", checks);
};
window.rtIn = async function(start) {
  const box = document.getElementById("rt-in-box");
  if (box) box.innerHTML = '<div class="stub-panel" style="min-height:40px">Reading…</div>';
  const d = await api("/api/phone/routertest", "POST", {part: start ? "in_start" : "in"});
  if (!d || !d.ok) { if (box) box.innerHTML = '<div class="stub-panel">Check failed</div>'; return; }
  rtChecks("rt-in-box", "in", d.checks);
};

const PM_STATE = {"ready": ["pass", "READY"], "missing": ["fail", "MISSING"], "off": ["info", "OFF"],
                  "not set up": ["info", "NOT SET UP"], "asterisk down": ["warn", "ASTERISK DOWN"]};

let _pmJobTimer = null;

let _pmLast = null;

let _pmRoot = true;
const PM_ASK = {
  "conf:load":   m => `Set ${m} to load in modules.conf?\n\nsysmon backs up modules.conf first. It takes effect the next time Asterisk restarts -- use Start to load it now.`,
  "conf:noload": m => `Set ${m} to noload in modules.conf?\n\nAsterisk won't load it at the next restart. Use Stop to unload it now.`,
  "live:start":  m => `Start (load) ${m} now?`,
  "live:stop":   m => `Stop (unload) ${m} now?\n\nAnything using it stops working until it is started again.`,
};

window.loadTab_phone = async function() {
  if (!_enabledTabSet.has("phone")) return;
  const d = await api("/api/phone");
  if (!d || !d.ok) {
    ["live", "node", "nets", "hoip", "dial", "health", "mods", "calls"].forEach(p => {
      const b = phBody(p);
      if (b) b.appendChild(phEl("div", "stub-panel", "Server unreachable"));
      phSetCard(p, "info", "—", "—");
    });
    return;
  }
  _phData = d;
  phRenderAll();
  if (_phRefreshTimer) clearInterval(_phRefreshTimer);
  _phRefreshTimer = setInterval(phPollLive, 5000);
};


window.loadTab_sdcard = function() {
  if (!_enabledTabSet.has("sdcard")) return;
  loadSdHealth(); loadSdTests();
};

window.loadTab_hardware = function() { loadHardware(); };

const _hwPingCache = {};

let _hwUsbView  = "flat";
let _hwAlsaView = "playback";
let _hwDiagData = null;
let _hwData = null;
let _ptAll = [];
let _ovGroups = [];
let _s3Items = [];

const _HW_AMBE_PAIRS  = {"0403:6015": "ThumbDV"};
const _HW_FTDI_VIDS   = {"0403": true};

function _esc(s) {
  return String(s || "")
    .replace(/&/g,"&amp;")
    .replace(/</g,"&lt;")
    .replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;")
    .replace(/'/g,"&#39;");
}

async function loadAstFiles() {
  const d = await api("/api/asterisk/files");
  if (!d) return;
  renderAstFiles(d.files || [], d.dir || "/etc/asterisk");
}

async function loadDvsFiles() {
  const d = await api("/api/dvswitch/files");
  if (!d) return;
  renderDvsFiles(d.files || []);
}

function _fileCheckRows(cb, checks) {
  checks.forEach(c => {
    if (c.title.startsWith("[")) {
      const lbl = document.createElement("div");
      lbl.style.cssText =
        "font-family:var(--sans);font-size:var(--fs-xs);letter-spacing:.15em;" +
        "text-transform:uppercase;color:#fff;padding:.4rem .9rem .15rem 1.1rem;" +
        "border-top:1px solid var(--border)";
      lbl.textContent = c.title + (c.value ? "  — " + c.value : "");
      cb.appendChild(lbl);
      return;
    }

    const crow = document.createElement("div");
    crow.className = "ast-check-row";

    const title = document.createElement("span");
    title.className   = "ast-check-title";
    title.textContent = c.title;

    const val = document.createElement("span");
    val.className   = "ast-check-value";
    val.textContent = c.value || "";

    const badge = document.createElement("span");
    if (c.status === "pass") {
      badge.className = "ast-check-pass"; badge.textContent = "[PASS]";
    } else if (c.status === "fail") {
      badge.className = "ast-check-fail"; badge.textContent = "[FAIL]";
    } else if (c.status === "info") {
      badge.className = "ast-check-info"; badge.textContent = "[INFO]";
    } else {
      badge.className = "ast-check-none"; badge.textContent = "[NONE]";
    }

    crow.appendChild(title);
    crow.appendChild(val);
    crow.appendChild(badge);
    cb.appendChild(crow);

    if (c.note) {
      const nrow = document.createElement("div");
      nrow.className = "ast-check-note";
      if (c.url) {
        const a = document.createElement("a");
        a.href = c.url; a.target = "_blank"; a.rel = "noopener noreferrer";
        a.className = "ast-check-link"; a.textContent = c.note;
        nrow.appendChild(a);
      } else {
        nrow.textContent = c.note;
      }
      cb.appendChild(nrow);
    }
    if (Array.isArray(c.notes)) {
      c.notes.forEach(line => {
        const nrow = document.createElement("div");
        nrow.className   = "ast-check-note";
        nrow.textContent = line;
        cb.appendChild(nrow);
      });
    }
  });
}

function _filePortLinesEl(portLines) {
  const pl = document.createElement("div");
  pl.className = "ast-port-lines";
  let lastSection = null;
  portLines.forEach(entry => {
    const section = (typeof entry === "object") ? entry.section : "";
    const rawLine = (typeof entry === "object") ? entry.line    : entry;
    if (section && section !== lastSection) {
      const lbl = document.createElement("span");
      lbl.className   = "ast-section-lbl";
      lbl.textContent = "[" + section + "]";
      pl.appendChild(lbl);
      lastSection = section;
    }
    const wrap = document.createElement("div");
    wrap.style.cssText = "display:flex;align-items:baseline;gap:.4rem";
    const span = document.createElement("span");
    span.className   = "ast-port-line";
    span.style.flex  = "1";
    span.textContent = rawLine;
    wrap.appendChild(span);
    const badge = portBadgeFromLine(rawLine);
    if (badge) { badge.style.marginRight = ".9rem"; wrap.appendChild(badge); }
    pl.appendChild(wrap);
  });
  return pl;
}

function renderDvsFiles(files, targetId, editMode) {
  const body = document.getElementById(targetId || "dvs-file-body");
  if (!body) return;
  body.innerHTML = "";

  if (!files.length) {
    body.innerHTML = '<div class="stub-panel" style="min-height:40px">No files configured.</div>';
    return;
  }

  files.forEach(f => {
    const isHidden  = !!f.hidden;
    const portLines = f.port_lines || [];

    const row = document.createElement("div");
    row.className = "ast-row";
    if (isHidden) row.style.opacity = "0.45";
    row.onclick = e => { if (e.target.tagName === "BUTTON") return; openDvsEditor(f.label); };

    const nameEl = document.createElement("span");
    nameEl.className = "ast-name";
    nameEl.innerHTML =
      `${esc(f.label)}<span style="color:#fff;font-size:var(--fs-xs);margin-left:.6rem">${esc(f.path)}</span>`;
    if (!f.exists) {
      nameEl.innerHTML +=
        `<span style="color:var(--amber);font-size:var(--fs-xs);margin-left:.4rem">⚠ not found</span>`;
    }
    if (isHidden) {
      nameEl.innerHTML +=
        `<span style="color:#fff;font-size:var(--fs-xs);margin-left:.4rem">hidden</span>`;
    }

    const btns = document.createElement("div");
    btns.style.cssText = "display:flex;gap:.3rem";

    const editBtn = document.createElement("button");
    editBtn.className   = "btn btn-muted btn-sm";
    editBtn.textContent = "Edit";
    editBtn.onclick     = e => { e.stopPropagation(); openDvsEditor(f.label); };
    btns.appendChild(editBtn);

    if (editMode) {
      const hideBtn = document.createElement("button");
      hideBtn.className   = "btn btn-sm " + (isHidden ? "btn-green" : "btn-amber");
      hideBtn.textContent = isHidden ? "Show" : "Hide";
      hideBtn.onclick     = e => { e.stopPropagation(); edToggleFileHidden(f.label, isHidden); };
      btns.appendChild(hideBtn);
    }

    row.appendChild(nameEl);
    row.appendChild(btns);
    body.appendChild(row);

    const checks      = (typeof f === "object" && Array.isArray(f.checks)) ? f.checks : [];
    if (checks.length) {
      const cb = document.createElement("div");
      cb.className = "ast-checks";
      _fileCheckRows(cb, checks);
      body.appendChild(cb);
    }

    if (portLines.length) body.appendChild(_filePortLinesEl(portLines));
  });
}

function _ufOpenReset(unit, title, pathText) {
  _ufUnit = unit;
  document.getElementById("uf-title").textContent      = `✎ ${title}`;
  document.getElementById("uf-path").textContent       = pathText;
  document.getElementById("uf-textarea").value         = "";
  document.getElementById("uf-status").textContent     = "";
  document.getElementById("uf-promoted-bar").classList.remove("show");
  document.getElementById("uf-save-btn").disabled      = true;
  document.getElementById("uf-restart-btn").disabled   = true;
  document.getElementById("uf-restart-btn").style.display = "none";
  findReset("uf");
  document.getElementById("uf-overlay").classList.add("open");
}

async function _ufOpenLabelFile(prefix, apiBase, label) {
  _ufOpenReset(prefix + label, label, "Loading…");
  const d = await api(`${apiBase}?label=${encodeURIComponent(label)}`);
  if (!d || !d.ok) {
    ufSetStatus(d?.message || "Failed to load", false);
    return;
  }
  document.getElementById("uf-textarea").value      = d.content;
  document.getElementById("uf-save-btn").disabled   = !d.writable;
  document.getElementById("uf-path").textContent    = d.path;
  if (!d.exists) {
    ufSetStatus("⚠ File does not exist yet — saving will create it", false);
  } else {
    ufSetStatus(d.writable ? "" : "Read-only (not running as root)");
  }
}

async function openDvsEditor(label) {
  return _ufOpenLabelFile("\x00dvs:", "/api/dvswitch/file", label);
}

async function loadAllmon3Files() {
  const d = await api("/api/allmon3/files");
  if (!d) return;
  renderAllmon3Files(d.files || []);
}

function renderAllmon3Files(files, targetId, editMode) {
  const body = document.getElementById(targetId || "allmon3-file-body");
  if (!body) return;
  body.innerHTML = "";

  if (!files.length) {
    body.innerHTML =
      '<div class="stub-panel" style="min-height:40px">No Allmon3 files found.</div>';
    return;
  }

  files.forEach(f => {
    const isHidden  = !!f.hidden;
    const isRO      = !!f.readonly;
    const portLines = f.port_lines || [];

    const row = document.createElement("div");
    row.className = "ast-row";
    if (isHidden) row.style.opacity = "0.45";
    row.onclick = e => { if (e.target.tagName === "BUTTON") return; openAllmon3Editor(f.label); };

    const nameEl = document.createElement("span");
    nameEl.className = "ast-name";
    nameEl.innerHTML =
      `${esc(f.label)}<span style="color:#fff;font-size:var(--fs-xs);margin-left:.6rem">${esc(f.path)}</span>`;
    if (!f.exists) {
      nameEl.innerHTML +=
        `<span style="color:var(--amber);font-size:var(--fs-xs);margin-left:.4rem">⚠ not found</span>`;
    }
    if (isHidden) {
      nameEl.innerHTML +=
        `<span style="color:#fff;font-size:var(--fs-xs);margin-left:.4rem">hidden</span>`;
    }
    if (isRO) {
      nameEl.innerHTML +=
        `<span style="color:#fff;font-size:var(--fs-xs);margin-left:.4rem">read-only</span>`;
    }

    const btns = document.createElement("div");
    btns.style.cssText = "display:flex;gap:.3rem";

    const editBtn = document.createElement("button");
    editBtn.className   = "btn btn-muted btn-sm";
    editBtn.textContent = isRO ? "View" : "Edit";
    editBtn.onclick     = e => { e.stopPropagation(); openAllmon3Editor(f.label); };
    btns.appendChild(editBtn);

    if (editMode) {
      const hideBtn = document.createElement("button");
      hideBtn.className   = "btn btn-sm " + (isHidden ? "btn-green" : "btn-amber");
      hideBtn.textContent = isHidden ? "Show" : "Hide";
      hideBtn.onclick     = e => { e.stopPropagation(); edToggleFileHidden(f.label, isHidden); };
      btns.appendChild(hideBtn);
    }

    row.appendChild(nameEl);
    row.appendChild(btns);
    body.appendChild(row);

    const checks = (typeof f === "object" && Array.isArray(f.checks)) ? f.checks : [];
    if (checks.length) {
      const cb = document.createElement("div");
      cb.className = "ast-checks";
      _fileCheckRows(cb, checks);
      body.appendChild(cb);
    }

    if (portLines.length) body.appendChild(_filePortLinesEl(portLines));
  });
}

async function openAllmon3Editor(label) {
  _ufOpenReset("\x00allmon3:" + label, label, "Loading…");

  const d = await api(`/api/allmon3/file?label=${encodeURIComponent(label)}`);
  if (!d || !d.ok) {
    ufSetStatus(d?.message || "Failed to load", false);
    return;
  }
  document.getElementById("uf-textarea").value    = d.content;
  document.getElementById("uf-path").textContent  = d.path;
  if (d.readonly) {
    document.getElementById("uf-save-btn").disabled = true;
    ufSetStatus("⚠ Managed by allmon3-passwd — read-only via this UI", false);
  } else if (!d.exists) {
    ufSetStatus("⚠ File does not exist yet — saving will create it", false);
  } else {
    document.getElementById("uf-save-btn").disabled = !d.writable;
    ufSetStatus(d.writable ? "" : "Read-only (not running as root)");
  }
}

window.loadTab_tune = function() { loadSimpleUSBTune(); loadRptNodes(); Promise.all([loadRadioPresets(), loadRadioDriver()]).then(() => { updateRadioButtons(); restoreActiveRadioButton(); }); };

const RN_DUPLEX = [
  ["0", "0 – half duplex, no telemetry or hang time"],
  ["1", "1 – half duplex, telemetry and hang time"],
  ["2", "2 – full duplex (repeater)"],
  ["3", "3 – full duplex, no repeated audio"],
  ["4", "4 – full duplex, repeat only when autopatch is down"],
];
const RN_TELEM = [
  ["0", "0 – off"],
  ["1", "1 – on"],
  ["2", "2 – timed (2 min after a command)"],
];
window.rnData = null;
window.rnOrig = {};

function tuneCardDefaultOpen(moduleState) {
  return moduleState === "load" || moduleState === "require";
}
function setCardOpen(bodyId, btnId, open) {
  const body = document.getElementById(bodyId);
  const btn  = document.getElementById(btnId);
  if (!body || !btn) return;
  body.classList.toggle("hidden", !open);
  btn.textContent = open ? "Hide" : "Show";
  btn.setAttribute("aria-expanded", open ? "true" : "false");
}
function setTuneCardOpen(open) {
  setCardOpen("su-tune-body", "su-tune-toggle", open);
}

window._radioRestartBusy = false;

function setRadioRestartBusy(busy) {
  window._radioRestartBusy = !!busy;
  const ids = ["su-save-btn", "su-reload-btn", "ur-save-btn", "ur-reload-btn"];
  for (const id of ids) {
    const el = document.getElementById(id);
    if (el) el.disabled = !!busy;
  }
  for (let i = 1; i <= 5; i++) {
    const btn = document.getElementById(`radio-btn-${i}`);
    if (btn && busy) btn.disabled = true;
  }
  if (!busy) updateRadioButtons();
}

async function pollRadioStackStatus() {
  const DEADLINE_MS = 35000;
  const INTERVAL_MS = 1500;
  const t0 = Date.now();

  while (Date.now() - t0 < DEADLINE_MS) {
    await new Promise(r => setTimeout(r, INTERVAL_MS));
    const s = await api("/api/radio/stack_status");
    if (!s || !s.ok) continue;

    if (s.restarting) continue;

    if (s.last_ok === false) {
      return { ok: false, msg: s.last_msg || "Asterisk restart failed" };
    }
    if (s.up === true) {
      return { ok: true, msg: "Asterisk restarted" };
    }
  }
  return {
    ok: false,
    msg: "Restart started but the stack is slow to settle — check the Services tab",
  };
}

const TUNE_CFG = {
  label: "SimpleUSB",
  readEndpoint: "/api/simpleusb/tune",
  notFoundMsg: "⚠ simpleusb.conf not found at /etc/asterisk/simpleusb.conf",
  fields: [
    { id: "rxmixerset", label: "RX Mixer Set", color: "var(--blue)",   tint: "rgba(100,150,220,0.15)", min: 0, max: 1000, step: 1, dec: 0, def: 500 },
    { id: "txmixaset",  label: "TX Mix A Set", color: "var(--green)",  tint: "rgba(100,180,100,0.15)", min: 0, max: 1000, step: 1, dec: 0, def: 300 },
    { id: "txmixbset",  label: "TX Mix B Set", color: "var(--orange)", tint: "rgba(220,140,60,0.15)",  min: 0, max: 1000, step: 1, dec: 0, def: 300 },
  ],
  advFields: [
    { id: "carrierfrom",        label: "Carrier From",          type: "select", def: "no",
      options: ["no", "usb", "usbinvert", "pp", "ppinvert"] },
    { id: "rxboost",            label: "RX Boost",              type: "bool",   def: "no", always: true },
    { id: "ctcssfrom",          label: "CTCSS From",            type: "select", def: "no",
      options: ["no", "usb", "usbinvert", "pp", "ppinvert"] },
    { id: "deemphasis",         label: "De-emphasis",           type: "bool",   def: "no", always: true },
    { id: "plfilter",           label: "PL Filter",             type: "bool",   def: "no" },
    { id: "invertptt",          label: "Invert PTT",            type: "bool",   def: "no" },
    { id: "preemphasis",        label: "Pre-emphasis",          type: "bool",   def: "no", always: true },
    { id: "legacyaudioscaling", label: "Legacy Audio Scaling",  type: "bool",   def: "yes" },
  ],
  pinGroups: [
    { id: "gpio", label: "GPIO", title: "GPIO pins",
      note: "Extra GPIO on the USB interface (pin 3 is PTT; 5-8 CM119 only)",
      pins: [1, 2, 4, 5, 6, 7, 8], collapsed: false,
      options: ["in", "out0", "out1"] },
    { id: "pp",   label: "PP",   title: "Parallel port pins",
      note: "Hardware parallel port pins 1-17",
      pins: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17], collapsed: true,
      options: ["in", "out0", "out1", "ptt", "cor", "ctcss"] },
  ],
  numberFields: [
    { id: "rxondelay",  label: "RX On Delay",  hint: "ms Frames 0-100 Range", min: 0, max: 100 },
    { id: "txoffdelay", label: "TX Off Delay", hint: "ms Frames 0-100 Range", min: 0, max: 100 },
  ],
};

function tuneFieldSpec(fieldId) {
  return TUNE_CFG.fields.find(f => f.id === fieldId);
}

async function loadSimpleUSBTune() {
  const cfg    = TUNE_CFG;
  const prefix = "su";
  const body   = document.getElementById(`${prefix}-tune-body`);
  const status = document.getElementById(`${prefix}-tune-status`);
  try {
    const resp = await api(cfg.readEndpoint);
    if (!resp || !resp.exists) {
      if (body)   body.innerHTML = `<div class="stub-panel" style="min-height:60px">${cfg.notFoundMsg}</div>`;
      if (status) status.textContent = "not found";
      if (resp) setTuneCardOpen(tuneCardDefaultOpen(resp.module));
      return;
    }
    if (status) status.textContent = "ready";
    renderTuneCard(resp.settings || {});
    setTuneCardOpen(tuneCardDefaultOpen(resp.module));
  } catch (e) {
    if (body)   body.innerHTML = `<div class="stub-panel" style="color:var(--red);min-height:60px">Error: ${e.message}</div>`;
    if (status) status.textContent = "error";
  }
}

function renderTuneCard(s) {
  const cfg    = TUNE_CFG;
  const prefix = "su";
  const body   = document.getElementById(`${prefix}-tune-body`);
  if (!body) return;

  const originals = {};
  const fieldHtml = cfg.fields.map(f => {
    const val = s[f.id] ?? f.def;
    originals[f.id] = Number(val);
    const pct   = ((Number(val) - f.min) / (f.max - f.min)) * 100;
    const shown = f.dec ? Number(val).toFixed(f.dec) : val;
    return `
      <div style="display: grid; gap: 0.6rem">
        <label for="${prefix}-${f.id}" style="
          font-weight: 600;
          font-size:var(--fs-md);
          color: ${f.color};
          display: flex;
          justify-content: space-between;
          align-items: center">
          <span>${f.label}</span>
          <input type="number" id="${prefix}-${f.id}-val"
            value="${shown}" step="${f.step}" min="${f.min}" max="${f.max}"
            aria-label="${f.label} exact value"
            style="
              font-family: var(--sans);
              font-size:var(--fs-base);
              font-weight: 400;
              background: ${f.tint};
              border: 1px solid var(--border2);
              border-radius: 0.3rem;
              padding: 0.2rem 0.4rem;
              width: 5.5rem;
              text-align: right;
              color: var(--text)"
            onchange="tuneNumberInput('${f.id}')"
            oninput="tuneNumberInput('${f.id}')">
        </label>
        <input type="range" id="${prefix}-${f.id}"
          min="${f.min}" max="${f.max}" step="${f.step}" value="${val}"
          aria-label="${f.label} slider (${f.min}-${f.max})"
          aria-valuemin="${f.min}" aria-valuemax="${f.max}" aria-valuenow="${val}"
          style="
            width: 100%;
            height: 6px;
            border-radius: 3px;
            background: linear-gradient(to right,
              ${f.color} 0%,
              ${f.color} ${pct}%,
              #ddd ${pct}%,
              #ddd 100%);
            accent-color: ${f.color};
            cursor: pointer"
          title="Valid range: ${f.min}–${f.max}"
          oninput="tuneSlide('${f.id}')">
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; font-size:var(--fs-sm); color: #ffffff">
          <span>Min: ${f.min}</span>
          <span style="text-align: right">Max: ${f.max}</span>
        </div>
      </div>`;
  }).join("");

  const selStyle = "font-family: var(--sans); font-size:var(--fs-base); " +
    "background: var(--surface2); border: 1px solid var(--border2); " +
    "border-radius: 0.3rem; padding: 0.25rem 0.4rem; color: var(--text)";
  let boolFieldsHtml = "";
  if (cfg.advFields && cfg.advFields.length) {
    const rows = cfg.advFields.map(f => {
      if (f.type === "select") {
        const cur = f.options.includes(s[f.id]) ? s[f.id] : f.def;
        originals[f.id] = cur;
        const opts = f.options.map(o =>
          `<option value="${o}"${o === cur ? " selected" : ""}>${o}</option>`).join("");
        return `
        <label for="${prefix}-${f.id}" style="
          display: flex;
          align-items: center;
          gap: 0.5rem;
          font-size:var(--fs-base);
          color: var(--text)">
          <span>${f.label}</span>
          <select id="${prefix}-${f.id}" aria-label="${f.label}"
            style="${selStyle}" onchange="checkTuneDirty()">${opts}</select>
        </label>`;
      }
      const cur     = (s[f.id] === "yes" || s[f.id] === "no") ? s[f.id] : f.def;
      const checked = cur === "yes";
      originals[f.id] = checked ? "yes" : "no";
      return `
        <label for="${prefix}-${f.id}" style="
          display: flex;
          align-items: center;
          gap: 0.5rem;
          font-size:var(--fs-base);
          color: var(--text);
          cursor: pointer">
          <input type="checkbox" id="${prefix}-${f.id}"
            ${checked ? "checked" : ""}
            aria-label="${f.label}"
            onchange="checkTuneDirty()">
          <span>${f.label}</span>
        </label>`;
    }).join("");

    const pinHtml = (cfg.pinGroups || []).map(g => {
      const cells = g.pins.map(n => {
        const id  = `${g.id}${n}`;
        const cur = g.options.includes(s[id]) ? s[id] : "";
        originals[id] = cur;
        const opts = [`<option value=""${cur === "" ? " selected" : ""}>—</option>`]
          .concat(g.options.map(o =>
            `<option value="${o}"${o === cur ? " selected" : ""}>${o}</option>`)).join("");
        return `
          <label for="${prefix}-${id}" style="
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.4rem;
            font-size:var(--fs-base);
            color: var(--text)">
            <span>${g.label} ${n}</span>
            <select id="${prefix}-${id}" aria-label="${g.title} ${n}"
              style="${selStyle}" onchange="checkTuneDirty()">${opts}</select>
          </label>`;
      }).join("");
      const inner = `
        <div style="font-size:var(--fs-xs); color: #ffffff">${g.note}</div>
        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(9.5rem, 1fr)); gap: 0.5rem">
          ${cells}
        </div>`;
      const titleCss = "font-weight: 600; font-size:var(--fs-md); color: var(--text)";
      if (g.collapsed) {
        return `
        <details style="display: grid; gap: 0.5rem">
          <summary style="cursor: pointer; ${titleCss}">${g.title}</summary>
          <div style="display: grid; gap: 0.5rem; margin-top: 0.5rem">${inner}</div>
        </details>`;
      }
      return `
        <div style="display: grid; gap: 0.5rem">
          <div style="${titleCss}">${g.title}</div>
          ${inner}
        </div>`;
    }).join("");

    boolFieldsHtml = `
      <div style="display: grid; gap: 0.6rem">
        <div style="
          font-weight: 600;
          font-size:var(--fs-md);
          color: var(--text)">Simpleusb Advanced Settings</div>
        <div style="display: grid; gap: 0.5rem">
          ${rows}
        </div>
        ${pinHtml}
      </div>`;
  }

  let numberFieldsHtml = "";
  if (cfg.numberFields && cfg.numberFields.length) {
    const rows = cfg.numberFields.map(f => {
      const val = Number(s[f.id] ?? 0);
      originals[f.id] = val;
      const checked = val > 0;
      return `
        <div style="display: grid; gap: 0.4rem">
          <label for="${prefix}-${f.id}-enable" style="
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size:var(--fs-base);
            color: var(--text);
            cursor: pointer">
            <input type="checkbox" id="${prefix}-${f.id}-enable"
              ${checked ? "checked" : ""}
              aria-label="Enable ${f.label}"
              onchange="tuneDelayToggle('${f.id}')">
            <span>${f.label}</span>
            <span style="font-size:var(--fs-xs); color: #ffffff">${f.hint}</span>
          </label>
          <input type="number" id="${prefix}-${f.id}"
            value="${val}" min="${f.min}" max="${f.max}" step="1"
            ${checked ? "" : "disabled"}
            aria-label="${f.label} value (${f.min}-${f.max})"
            style="
              font-family: var(--sans);
              font-size:var(--fs-base);
              background: var(--surface2);
              border: 1px solid var(--border2);
              border-radius: 0.3rem;
              padding: 0.3rem 0.5rem;
              width: 6rem;
              color: var(--text)"
            onchange="tuneDelayInput('${f.id}')"
            oninput="tuneDelayInput('${f.id}')">
        </div>`;
    }).join("");
    numberFieldsHtml = `
      <div style="display: grid; gap: 0.6rem">
        <div style="
          font-weight: 600;
          font-size:var(--fs-md);
          color: var(--text)">RX/TX Delay</div>
        <div style="display: grid; gap: 0.8rem">
          ${rows}
        </div>
      </div>`;
  }

  window[`${prefix}_original_values`] = originals;

  const tipText = "RX adjusts input levels. TX adjusts output levels for each channel.";

  const defaultInfo = `
      <div style="
        font-size:var(--fs-base);
        color: #fff;
        padding: 0.8rem;
        background: rgba(60,180,200,0.08);
        border-radius: 0.3rem;
        border-left: 3px solid var(--teal);
        line-height: 1.4">
        <strong>ℹ Default:</strong> Radio 1 preset is applied on startup.
      </div>`;

  body.innerHTML = `
    <div style="display: grid; gap: 1.4rem; padding: 1rem">

      <div style="
        padding: 0.8rem;
        background: rgba(100,120,140,0.08);
        border-radius: 0.4rem;
        font-size:var(--fs-base);
        border-left: 3px solid var(--blue)">
        <div style="color: #ffffff; font-weight: 500; margin-bottom: 0.2rem">USB Device</div>
        <div style="font-family: var(--sans); color: var(--blue)">${esc(s.devstr || "—")}</div>
      </div>

      ${fieldHtml}
      ${boolFieldsHtml}
      ${numberFieldsHtml}

      <div style="display: flex; gap: 0.4rem; flex-wrap: wrap; margin-top: 0.5rem">
        <button class="btn btn-blue btn-sm" id="${prefix}-save-btn"
          onclick="openTuneSaveDialog()"
          title="Save — choose preset and reload options">
          💾 Save
        </button>
        <button class="btn btn-muted btn-sm" id="${prefix}-reset-btn"
          onclick="resetTuneCard()"
          title="Revert to server values without saving">
          ↺ Reset
        </button>
        <span id="${prefix}-dirty-indicator" style="display:none;font-size:var(--fs-base);color:var(--amber);align-self:center">● unsaved changes</span>
      </div>

      <div style="
        font-size:var(--fs-base);
        color: #ffffff;
        padding: 0.8rem;
        background: rgba(100,120,140,0.04);
        border-radius: 0.3rem;
        line-height: 1.4">
        <strong>Tip:</strong> ${tipText} Use <strong>Save</strong> and enable restart in the dialog to apply changes immediately to Asterisk.
      </div>

      ${defaultInfo}

    </div>
  `;
}

function tuneSlide(fieldId) {
  const spec = tuneFieldSpec(fieldId);
  const sl = document.getElementById(`su-${fieldId}`);
  if (!spec || !sl) return;
  const v = parseFloat(sl.value);
  const pct = ((v - spec.min) / (spec.max - spec.min)) * 100;
  const box = document.getElementById(`su-${fieldId}-val`);
  if (box) box.value = spec.dec ? v.toFixed(spec.dec) : String(v);
  sl.setAttribute("aria-valuenow", sl.value);
  sl.style.background =
    `linear-gradient(to right, ${spec.color} 0%, ${spec.color} ${pct}%, #ddd ${pct}%, #ddd 100%)`;
  checkTuneDirty();
}

function tuneNumberInput(fieldId) {
  const spec = tuneFieldSpec(fieldId);
  const box  = document.getElementById(`su-${fieldId}-val`);
  const sl   = document.getElementById(`su-${fieldId}`);
  if (!spec || !box || !sl) return;
  let v = parseFloat(box.value);
  if (!Number.isFinite(v)) return;
  if (v < spec.min) v = spec.min;
  if (v > spec.max) v = spec.max;
  if (spec.step) {
    const steps = Math.round((v - spec.min) / spec.step);
    v = spec.min + steps * spec.step;
  }
  if (spec.dec) v = parseFloat(v.toFixed(spec.dec));
  sl.value = v;
  box.value = spec.dec ? v.toFixed(spec.dec) : String(v);
  const pct = ((v - spec.min) / (spec.max - spec.min)) * 100;
  sl.setAttribute("aria-valuenow", v);
  sl.style.background =
    `linear-gradient(to right, ${spec.color} 0%, ${spec.color} ${pct}%, #ddd ${pct}%, #ddd 100%)`;
  checkTuneDirty();
}

function tuneDelaySpec(fieldId) {
  return (TUNE_CFG.numberFields || []).find(f => f.id === fieldId);
}

function tuneDelayToggle(fieldId) {
  const cb  = document.getElementById(`su-${fieldId}-enable`);
  const box = document.getElementById(`su-${fieldId}`);
  if (!cb || !box) return;
  box.disabled = !cb.checked;
  if (!cb.checked) {
    box.value = "0";
  }
  checkTuneDirty();
}

function tuneDelayInput(fieldId) {
  const spec = tuneDelaySpec(fieldId);
  const box  = document.getElementById(`su-${fieldId}`);
  if (!spec || !box) return;
  let v = parseInt(box.value, 10);
  if (!Number.isFinite(v)) return;
  if (v < spec.min) v = spec.min;
  if (v > spec.max) v = spec.max;
  box.value = String(v);
  checkTuneDirty();
}

function resetTuneCard() {
  const cfg    = TUNE_CFG;
  const prefix = "su";
  const orig   = window[`${prefix}_original_values`];
  if (!orig) return;
  for (const f of cfg.fields) {
    if (orig[f.id] === undefined) continue;
    const sl = document.getElementById(`${prefix}-${f.id}`);
    if (sl) { sl.value = orig[f.id]; tuneSlide(f.id); }
  }
  if (cfg.advFields) {
    for (const f of cfg.advFields) {
      if (orig[f.id] === undefined) continue;
      const el = document.getElementById(`${prefix}-${f.id}`);
      if (!el) continue;
      if (f.type === "select") el.value = orig[f.id];
      else el.checked = orig[f.id] === "yes";
    }
  }
  if (cfg.pinGroups) {
    for (const g of cfg.pinGroups) {
      for (const n of g.pins) {
        const id = `${g.id}${n}`;
        if (orig[id] === undefined) continue;
        const el = document.getElementById(`${prefix}-${id}`);
        if (el) el.value = orig[id];
      }
    }
  }
  if (cfg.numberFields) {
    for (const f of cfg.numberFields) {
      if (orig[f.id] === undefined) continue;
      const cb  = document.getElementById(`${prefix}-${f.id}-enable`);
      const box = document.getElementById(`${prefix}-${f.id}`);
      if (cb)  cb.checked = orig[f.id] > 0;
      if (box) { box.value = String(orig[f.id]); box.disabled = !(orig[f.id] > 0); }
    }
  }
  checkTuneDirty();
  toast("Reset to server values", 1);
}

function getTuneValues() {
  const cfg    = TUNE_CFG;
  const prefix = "su";
  const out = {};
  for (const f of cfg.fields) {
    const el = document.getElementById(`${prefix}-${f.id}`);
    if (!el || el.value === "") continue;
    out[f.id] = f.dec ? parseFloat(el.value) : parseInt(el.value);
  }
  const orig = window[`${prefix}_original_values`] || {};
  if (cfg.advFields) {
    for (const f of cfg.advFields) {
      const el = document.getElementById(`${prefix}-${f.id}`);
      if (!el) continue;
      const v = f.type === "select" ? el.value : (el.checked ? "yes" : "no");
      if (f.always || v !== orig[f.id]) out[f.id] = v;
    }
  }
  if (cfg.pinGroups) {
    for (const g of cfg.pinGroups) {
      for (const n of g.pins) {
        const id = `${g.id}${n}`;
        const el = document.getElementById(`${prefix}-${id}`);
        if (el && el.value !== orig[id]) out[id] = el.value;
      }
    }
  }
  if (cfg.numberFields) {
    for (const f of cfg.numberFields) {
      const cb  = document.getElementById(`${prefix}-${f.id}-enable`);
      const box = document.getElementById(`${prefix}-${f.id}`);
      if (!cb) continue;
      if (!cb.checked) { out[f.id] = 0; continue; }
      let v = box ? parseInt(box.value, 10) : 0;
      if (!Number.isFinite(v)) v = 0;
      if (v < f.min) v = f.min;
      if (v > f.max) v = f.max;
      out[f.id] = v;
    }
  }
  return out;
}

function isTuneDirty() {
  const prefix = "su";
  const orig = window[`${prefix}_original_values`];
  if (!orig) return false;
  const cur = getTuneValues();
  for (const [k, v] of Object.entries(cur)) {
    if (orig[k] === undefined) continue;
    if (typeof v === "string" || typeof orig[k] === "string") {
      if (String(v) !== String(orig[k])) return true;
      continue;
    }
    if (Math.abs(Number(v) - Number(orig[k])) > 0.005) return true;
  }
  return false;
}

function checkTuneDirty() {
  const dirty = isTuneDirty();
  const ind = document.getElementById("su-dirty-indicator");
  if (ind) ind.style.display = dirty ? "inline" : "none";
  return dirty;
}

window.radioDialogSlot = null;
window.radioDialogMode = null;
window.radioDialogDriver = null;
window._tuneReloadChoice = false;

async function loadRadioPresets() {
  try {
    const result = await api("/api/radio/presets");
    if (!result || !result.ok) {
      console.warn("Failed to load radio presets");
      window.radioPresets = {};
      return;
    }
    window.radioPresets = result.presets || {};
    window.radioTune = result.tune || { active_slot: 0, active_driver: "", simpleusb: {} };
  } catch (e) {
    console.error("Error loading radio presets:", e);
    window.radioPresets = {};
    window.radioTune = { active_slot: 0, active_driver: "", simpleusb: {} };
  }
}

function restoreActiveRadioButton() {
  const tune = window.radioTune;
  const currentDrv = window.radioDriver?.active || null;
  const slot = tune?.active_slot || 0;
  const drvMatch = slot >= 1 && slot <= 5 &&
                   currentDrv && tune.active_driver === currentDrv;
  setActiveRadioButton(drvMatch ? slot : 0);
}

function radioPresetIsStale(slot) {
  const tune = window.radioTune;
  const currentDrv = window.radioDriver?.active || null;
  if (!tune || !currentDrv) return false;
  if (tune.active_slot !== slot || tune.active_driver !== currentDrv) return false;
  const preset = window.radioPresets?.[slot];
  const mirror = tune[currentDrv] || {};
  if (!preset) return false;
  for (const k of Object.keys(preset)) {
    if (k === "title") continue;
    if (mirror[k] === undefined) continue;
    const a = Number(preset[k]), b = Number(mirror[k]);
    if (Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) > 0.005) return true;
  }
  return false;
}

async function loadRadioDriver() {
  try {
    const r = await api("/api/radio/driver");
    window.radioDriver = (r && r.ok) ? r : null;
  } catch (e) {
    console.error("Error loading radio driver:", e);
    window.radioDriver = null;
  }
  return window.radioDriver;
}

function showRadioDialogFormView() {
  document.getElementById("radio-dialog-form-view").style.display = "block";
  document.getElementById("radio-dialog-restart-view").style.display = "none";
}

function openTuneSaveDialog() {
  const driver = "simpleusb";
  if (!isTuneDirty()) {
    toast("No changes to save", 1);
    return;
  }

  window.radioDialogMode = "tunesave";
  window.radioDialogDriver = driver;
  window.radioDialogSlot = null;
  window.radioDialogSource = null;

  document.getElementById("radio-dialog-hdr").textContent = "Save SimpleUSB Tune";
  document.getElementById("radio-dialog-msg").textContent = "Optional preset name:";
  document.getElementById("radio-dialog-error").style.display = "none";
  document.getElementById("radio-dialog-save-btn").textContent = "Save";

  const tune = window.radioTune;
  const preselect = (tune && tune.active_driver === driver &&
                      tune.active_slot >= 1 && tune.active_slot <= 5)
    ? String(tune.active_slot) : "1";
  const sel = document.getElementById("radio-dialog-preset-select");
  sel.value = preselect;
  document.getElementById("radio-dialog-preset-row").style.display = "block";
  tuneDialogPresetChanged();

  const reloadToggle = document.getElementById("radio-dialog-reload-toggle");
  reloadToggle.checked = window._tuneReloadChoice;
  document.getElementById("radio-dialog-reload-row").style.display = "block";
  tuneDialogReloadChanged();

  showRadioDialogFormView();
  document.getElementById("radio-dialog-overlay").style.display = "flex";
}

function tuneDialogPresetChanged() {
  const sel = document.getElementById("radio-dialog-preset-select");
  const titleInput = document.getElementById("radio-dialog-title");
  const titleRow = titleInput?.parentElement;
  if (titleRow) titleRow.style.display = sel.value ? "" : "none";
  if (titleInput) {
    const preset = sel.value ? window.radioPresets?.[parseInt(sel.value)] : null;
    titleInput.value = preset?.title ?? "";
  }
}

function tuneDialogReloadChanged() {
  const on = document.getElementById("radio-dialog-reload-toggle")?.checked;
  window._tuneReloadChoice = !!on;
  const warn = document.getElementById("radio-dialog-reload-warn");
  if (warn) warn.style.display = on ? "block" : "none";
}

function updateRadioButtons() {
  const presets = window.radioPresets || {};
  const drv = window.radioDriver;
  const noDriver = !!(drv && drv.none);

  for (let slot = 1; slot <= 5; slot++) {
    const btn = document.getElementById(`radio-btn-${slot}`);
    if (!btn) continue;

    const preset = presets[slot];
    const populated = preset && preset.rxmixerset !== undefined;

    if (populated && !noDriver) {
      btn.disabled = false;
      btn.classList.remove("empty");
      const stale = radioPresetIsStale(slot);
      btn.textContent = (preset.title || `Radio ${slot}`) + (stale ? " *" : "");
      btn.style.opacity = stale ? "0.75" : "";
      btn.title = `Apply ${preset.title || `Radio ${slot}`}: ` +
                  `RX=${preset.rxmixerset}, TX-A=${preset.txmixaset}, TX-B=${preset.txmixbset}` +
                  (stale ? " — current settings have been changed since this preset was applied" : "");
    } else if (populated && noDriver) {
      btn.disabled = true;
      btn.classList.add("empty");
      btn.textContent = preset.title || `Radio ${slot}`;
      btn.title = "No radio channel driver loaded (chan_simpleusb)";
    } else {
      btn.disabled = true;
      btn.classList.add("empty");
      btn.textContent = `Radio ${slot}`;
      btn.title = `Radio ${slot} preset is empty`;
    }
  }
}

async function applyRadioPreset(slot) {

  const preset = window.radioPresets?.[slot];
  if (!preset || preset.rxmixerset === undefined) {
    toast(`⚠ Preset ${slot} is empty`, 0);
    return;
  }

  let drv = window.radioDriver;
  if (!drv) drv = await loadRadioDriver();
  const active = drv?.active || null;

  if (!active) {
    toast("⚠ No radio channel driver loaded (chan_simpleusb)", 0);
    updateRadioButtons();
    return;
  }
  const endpoint   = "/api/simpleusb/tune";
  const cardPrefix = "su";
  const refreshFn  = loadSimpleUSBTune;
  const payload    = {
    rxmixerset: preset.rxmixerset,
    txmixaset:  preset.txmixaset,
    txmixbset:  preset.txmixbset,
    reload:     true,
    slot:       slot,
  };

  const body = document.getElementById(`${cardPrefix}-tune-body`);
  const isCardVisible = body && body.offsetParent !== null;

  if (isCardVisible) {
    const rxId  = "su-rxmixerset";
    const txaId = "su-txmixaset";
    const txbId = "su-txmixbset";
    const curRx  = document.getElementById(rxId)?.value;
    const curTxa = document.getElementById(txaId)?.value;
    const curTxb = document.getElementById(txbId)?.value;

    if (curRx && curTxa && curTxb &&
        parseInt(curRx)  === preset.rxmixerset &&
        parseInt(curTxa) === preset.txmixaset &&
        parseInt(curTxb) === preset.txmixbset) {
      toast(`✓ ${preset.title || `Radio ${slot}`} already applied`, 1);
      setActiveRadioButton(slot);
      return;
    }
  }

  if (window._radioRestartBusy) {
    toast("⚠ Restart in progress — try again shortly", 0);
    return;
  }

  const btn = document.getElementById(`radio-btn-${slot}`);
  if (btn) btn.disabled = true;
  const presetName = preset.title || `Radio ${slot}`;
  const originalText = btn ? btn.textContent : presetName;

  try {
    const result = await api(endpoint, "POST", payload);
    if (!result || !result.ok) {
      const errMsg = result?.message || "Unknown error";
      toast(`✗ Apply failed: ${errMsg}`, 0);
      return;
    }

    if (window.radioTune) {
      window.radioTune.active_slot = slot;
      window.radioTune.active_driver = active;
      const mirror = window.radioTune[active] || (window.radioTune[active] = {});
      for (const k of Object.keys(preset)) {
        if (k !== "title" && preset[k] !== undefined) mirror[k] = preset[k];
      }
    }
    setActiveRadioButton(slot);

    if (result.restart !== "started") {
      toast(`⚠ ${presetName} applied, but restart not started: ${result.restart_msg || "unknown"}`, 0);
      return;
    }

    if (btn) { btn.classList.add("spinner"); btn.textContent = "⟳"; }
    setRadioRestartBusy(true);
    const r = await pollRadioStackStatus();
    setRadioRestartBusy(false);
    if (btn) { btn.classList.remove("spinner"); btn.textContent = originalText; }

    if (r.ok) {
      toast(`✓ Applied & Asterisk restarted: ${presetName}`, 2);
      if (isCardVisible && refreshFn) refreshFn();
      updateRadioButtons();
      setActiveRadioButton(slot);
    } else {
      toast(`⚠ ${presetName} applied, but: ${r.msg}`, 0);
    }
  } catch (e) {
    toast(`✗ Error: ${e.message}`, 0);
  } finally {
    if (btn && !window._radioRestartBusy) btn.disabled = false;
  }
}

function setActiveRadioButton(slot) {
  for (let i = 1; i <= 5; i++) {
    const btn = document.getElementById(`radio-btn-${i}`);
    if (btn) btn.classList.remove("active");
  }
  const activeBtn = document.getElementById(`radio-btn-${slot}`);
  if (activeBtn) activeBtn.classList.add("active");
}

function renderAstFiles(files, dir, targetId, editMode) {
  const body = document.getElementById(targetId || "ast-file-body");
  if (!body) return;
  body.innerHTML = "";

  if (!files.length) {
    body.innerHTML =
      `<div class="stub-panel" style="min-height:60px">` +
      `No .conf files found in ${esc(dir)}</div>`;
    return;
  }

  files.forEach(f => {
    const name     = typeof f === "string" ? f : f.name;
    const isHidden = typeof f === "object" && !!f.hidden;
    const portLines = (typeof f === "object" && f.port_lines) || [];

    const row = document.createElement("div");
    row.className = "ast-row";
    if (isHidden) row.style.opacity = "0.45";
    row.onclick = e => { if (e.target.tagName === "BUTTON") return; openAstEditor(name); };

    const nameEl = document.createElement("span");
    nameEl.className   = "ast-name";
    nameEl.textContent = name;
    if (isHidden) {
      const dim = document.createElement("span");
      dim.style.cssText = "color:#fff;font-size:var(--fs-xs);margin-left:.5rem";
      dim.textContent   = "hidden";
      nameEl.appendChild(dim);
    }

    const btns = document.createElement("div");
    btns.style.cssText = "display:flex;gap:.3rem";

    const editBtn = document.createElement("button");
    editBtn.className   = "btn btn-muted btn-sm";
    editBtn.textContent = "Edit";
    editBtn.onclick     = e => { e.stopPropagation(); openAstEditor(name); };
    btns.appendChild(editBtn);

    if (editMode) {
      const hideBtn = document.createElement("button");
      hideBtn.className   = "btn btn-sm " + (isHidden ? "btn-green" : "btn-amber");
      hideBtn.textContent = isHidden ? "Show" : "Hide";
      hideBtn.onclick     = e => { e.stopPropagation(); edToggleFileHidden(name, isHidden); };
      btns.appendChild(hideBtn);
    }

    row.appendChild(nameEl);
    row.appendChild(btns);
    body.appendChild(row);

    const checks      = (typeof f === "object" && Array.isArray(f.checks)) ? f.checks : [];
    const collapsible = (typeof f === "object" && !!f.collapsible);
    if (checks.length) {
      const cb = document.createElement("div");
      cb.className = "ast-checks";

      if (collapsible) {
        cb.style.display = "none";
        const toggleBtn = document.createElement("button");
        toggleBtn.className   = "ast-toggle";
        toggleBtn.textContent = "▶ Show";
        toggleBtn.onclick     = e => {
          e.stopPropagation();
          const open = cb.style.display !== "none";
          cb.style.display    = open ? "none" : "";
          toggleBtn.textContent = open ? "▶ Show" : "▼ Hide";
        };
        btns.insertBefore(toggleBtn, btns.firstChild);
      }

      _fileCheckRows(cb, checks);
      body.appendChild(cb);
    }

    if (portLines.length) body.appendChild(_filePortLinesEl(portLines));
  });
}

async function openAstEditor(name) {
  document.getElementById("dpanel")?.style.setProperty("--panel-accent", "var(--red)");
  document.getElementById("uf-overlay").style.setProperty("--uf-accent", "var(--red)");
  _ufOpenReset("\x00ast:" + name, name, `/etc/asterisk/${name}`);


  const d = await api(`/api/asterisk/file?name=${encodeURIComponent(name)}`);
  if (!d || !d.ok) {
    ufSetStatus(d?.message || "Failed to load", false);
    return;
  }
  document.getElementById("uf-textarea").value      = d.content;
  document.getElementById("uf-save-btn").disabled   = !d.writable;
  document.getElementById("uf-path").textContent    = d.path;
  ufSetStatus(d.writable ? "" : "Read-only (not running as root)");
}

async function _ufSaveFile(url, payload, what, confirmText, after) {
  if (!await confirm(confirmText)) return;
  const content = document.getElementById("uf-textarea").value;
  const btn     = document.getElementById("uf-save-btn");
  if (btn) btn.disabled = true;
  ufSetStatus("Saving…");
  const d = await api(url, "POST", {...payload, content});
  if (btn) btn.disabled = false;
  if (!d || !d.ok) {
    ufSetStatus(d?.message || "Save failed", false);
    toast(d?.message || "Save failed", "err");
    return;
  }
  ufSetStatus("Saved ✓", true);
  toast(`Saved ${what}`, "ok");
  if (after) after();
}

async function ufSave() {
  const overwrite = l => `Save changes to ${l}?\n\nThis overwrites the file on disk.`;
  if (_ufUnit.startsWith("\x00ast:")) {
    const name = _ufUnit.slice(5);
    return _ufSaveFile("/api/asterisk/file", {name}, name,
      `Save changes to ${name}?\n\nThis overwrites /etc/asterisk/${name} on disk.`);
  } else if (_ufUnit.startsWith("\x00dvs:")) {
    const label = _ufUnit.slice(5);
    return _ufSaveFile("/api/dvswitch/file", {label}, label, overwrite(label), loadDvsFiles);
  } else if (_ufUnit.startsWith("\x00allmon3:")) {
    const label = _ufUnit.slice(9);
    return _ufSaveFile("/api/allmon3/file", {label}, label, overwrite(label), loadAllmon3Files);
  } else if (_ufUnit.startsWith("\x00appconf:")) {
    const label = _ufUnit.slice(9);
    return _ufSaveFile("/api/appconf/file", {label}, label, overwrite(label));
  } else {
    return _ufSaveOrig();
  }
}

function portBadgeFromLine(line) {
  const m = line.match(/[=:]\s*(\d{4,5})\s*(?:[;#]|$)/);
  if (!m) return null;
  const port = m[1];
  const lower = line.toLowerCase();
  const proto = (lower.includes("udp") ||
                 ["4569","34000","34001","31100","17000","42000","42020","42021"].includes(port))
                ? "udp" : "tcp";
  return portBadge(port, proto);
}

window.loadTab_dvsm = function() { loadDvsm(); };

const _dvsmRevealed = new Map();
const _dvsmSecrets  = new Map();


window.loadTab_stfu = function() { loadStfu(); };
window.loadTab_m17  = function() { loadM17(); };


const _stfuSecrets  = new Map();
const _stfuRevealed = new Map();

let _stfuSampleText = "";

let _stfuDvsPath = "";

let _stfuLoadedContent = null;

let _m17SampleText = "";
let _m17IniPath = "";
let _m17LoadedContent = null;


function _startApp() {
  _appStarted = true;
  if (sessionStorage.getItem("sysmon_paused_by_nav")) {
    sessionStorage.removeItem("sysmon_paused_by_nav");
    _pausedByNavigation = true;
  }

  const lnk = document.getElementById("lnk-dashboard");
  if (lnk) {
    const port = window.location.port || "8989";
    const host = window.location.hostname;
    const dashboardUrl = `http://${host}:8989/`;
    lnk.href = dashboardUrl;
    lnk.title = "Return to ASL-DVS Dashboard";
  }

  const qlHost = window.location.hostname;
  const qlPorts = {"lnk-allmon3": 8080, "lnk-cockpit": 9090, "lnk-wifimon": 8991};
  for (const [id, port] of Object.entries(qlPorts)) {
    const el = document.getElementById(id);
    if (el) el.href = `http://${qlHost}:${port}/`;
  }
  const qlPaths = {"lnk-dvswitch": "/dvswitch", "lnk-m17": "/m17"};
  for (const [id, path] of Object.entries(qlPaths)) {
    const el = document.getElementById(id);
    if (el) el.href = `http://${qlHost}${path}`;
  }

  api("/api/config").then(d => {
    if (d && d.ok) {
      _savedEnabledTabs = d.ui?.enabled_tabs || TABS.slice();
      _applyTabVisibilityGated();
      _applyThresholds(d.thresholds);
    }
  }).catch(() => {});

  Promise.all([loadRadioPresets(), loadRadioDriver()]).then(() => {
    updateRadioButtons();
    restoreActiveRadioButton();
  });

  if (_pausedByNavigation) {
    resumeAllPolling();
  } else {
    startStatusPolling();
  }

  if (typeof switchTab === "function") {
    switchTab("overview", "0,255,229");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  (async function _authBoot() {
    try {
      const r = await fetch("/api/whoami");
      if (r.ok) { hideLoginScreen(); _startApp(); return; }
    } catch (_) { }
    let relogin = null;
    try { relogin = sessionStorage.getItem(_RELOGIN_KEY); } catch (_) {}
    showLoginScreen(relogin ? _SESSION_EXPIRED_MSG : "");
  })();
});

window.addEventListener("beforeunload", () => {
  stopStatusPolling();
});

// ========================================================================
// TAB: Overview
// ========================================================================
// ---- general ----
async function svcGlobal(action, btn) {
  if (btn) btn.disabled = true;
  const d = await api("/api/svc", "POST", {action: action});
  if (btn) btn.disabled = false;
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "OK" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) setTimeout(loadOverview, 1200);
}

// ========================================================================
// TAB: Services
// ========================================================================
// ---- general ----
async function loadGeneralList() {
  const qs = `?scope=${_s3Scope}&filter=${encodeURIComponent(_s3Filter)}&all=1`;
  const d  = await api("/api/services" + qs);
  if (!d) return;
  renderGeneralList(d);
}

// ---- card: Services ----
function renderGeneralList(d) {
  _s3Items = d.items || [];
  const body = document.getElementById("s3-gen-body");
  if (!body) return;
  body.innerHTML = "";

  if (!d.items || d.items.length === 0) {
    body.innerHTML = '<div class="stub-panel" style="min-height:60px">No services found.</div>';
    return;
  }

  d.items.forEach(svc => {
    const row = document.createElement("div");
    row.className = "s3-gen-row";
    row.onclick   = e => {
      if (e.target.tagName === "BUTTON") return;
      openServicePanel(svc.unit, "");
    };

    const editBtn = document.createElement("button");
    editBtn.className   = "btn btn-muted btn-sm";
    editBtn.textContent = "Edit";
    editBtn.onclick     = e => { e.stopPropagation(); openUnitFileEditor(svc.unit); };

    row.innerHTML =
      `<span class="dot ${dotClass(svc.state, svc.enabled)}"></span>` +
      `<span class="s3-gen-name">${esc(svc.unit)}</span>`;

    row.appendChild(_ovOwnerCell(svc));
    row.appendChild(_ovModeCell(svc));

    const row2 = document.createElement("div");
    row2.className = "s3-gen-row2";
    const stateEl = document.createElement("span");
    stateEl.className   = "s3-state " + stateClass(svc.state);
    stateEl.textContent = svc.state;
    row2.appendChild(stateEl);
    row2.appendChild(editBtn);

    row.appendChild(row2);
    body.appendChild(row);
  });
}

function s3SetScope(scope) {
  _s3Scope = scope;
  document.getElementById("s3-btn-active").classList.toggle("on", scope === "active");
  document.getElementById("s3-btn-all").classList.toggle("on", scope === "all");
  loadGeneralList();
}

function s3FilterChanged() {
  clearTimeout(_s3FilterTimer);
  _s3FilterTimer = setTimeout(() => {
    _s3Filter = document.getElementById("s3-filter").value.trim();
    loadGeneralList();
  }, 300);
}

// ========================================================================
// TAB: Ports
// ========================================================================
// ---- general ----
function ptSetProto(proto) {
  _ptProto = proto;
  ["both","tcp","udp"].forEach(p => {
    const btn = document.getElementById("pt-btn-" + p);
    if (btn) btn.classList.toggle("on", p === proto);
  });
  if (_ptAll.length) renderPorts(_ptShown());
  loadPorts();
}

// ========================================================================
// TAB: Reg
// ========================================================================
// ---- general ----
function _regShowUnreachable(ids) {
  const body = document.getElementById(ids.body);
  if (body) body.innerHTML = '<div class="stub-panel" style="min-height:60px">Server unreachable</div>';
  const status = document.getElementById(ids.status);
  if (status) { status.className = "reg-card-status"; status.textContent = "—"; }
}

// ========================================================================
// TAB: Phone
// ========================================================================
// ---- general ----
function phSetCard(pfx, status, label, meta) {
  const st = document.getElementById("ph-" + pfx + "-status");
  const mt = document.getElementById("ph-" + pfx + "-meta");
  if (st) { st.className = "reg-card-status " + (status || "info"); st.textContent = label || "—"; }
  if (mt) mt.textContent = meta || "—";
}

function phBody(pfx) {
  const b = document.getElementById("ph-" + pfx + "-body");
  if (b) b.innerHTML = "";
  return b;
}

function phNote(body, text) { body.appendChild(phEl("div", "ph-note", text)); }

function phSec(d, id) { return (d && d.sections || []).find(s => s.id === id) || null; }

function phStar(code) { return code ? "*" + code : ""; }

function phRenderLive(s) {
  const body = phBody("live");
  if (!body) return;
  if (!s) { phSetCard("live", "info", "—", "—"); phNote(body, "No data"); return; }
  if (!s.found) {
    phSetCard("live", "fail", "DOWN", s.running === false ? "Asterisk not running" : "unavailable");
    phNote(body, s.note || "Live status is unavailable");
    return;
  }
  const label = {idle: "IDLE", dialing: "DIALING", incoming: "INCOMING", in_call: "IN CALL"}[s.state] || s.state.toUpperCase();
  phSetCard("live", s.state === "idle" ? "info" : "pass", label,
            s.calls.length ? s.calls.length + " call" + (s.calls.length === 1 ? "" : "s") : "no calls");
  const pn = s.phone_node || {};
  const pnName = pn.node ? pn.node + (pn.network ? " (" + pn.network + ")" : "") : "";
  let linkTxt = pn.linked === true ? `${pnName} is linked to ${pn.main_node}`
                : pn.linked === false ? `${pnName} is not linked to ${pn.main_node} (it links while the dashboard Phone tab is open)`
                : pn.node ? "unknown" : "";
  if ((pn.others_linked || []).length)
    linkTxt += ` — also linked: ${pn.others_linked.join(", ")} (only the picked network's node should be)`;
  const f = s.flags || {};
  body.appendChild(phKV([
    ["Phone node", linkTxt],
    ["Dashboard Phone tab", f.open === "1" ? "open (incoming calls are answered)" : (f.open === undefined ? "" : "closed (callers get busy)")],
    ["Network in use", f.active],
    ["Phone patch", f.patch === "0" ? "OFF" : (f.patch === "1" ? "on" : "")],
  ]));
  if (s.calls.length) {
    body.appendChild(phEl("div", "ph-sub", "Calls now"));
    const t = phEl("table", "ph-tbl");
    s.calls.forEach(c => {
      const tr = phEl("tr");
      [c.direction, c.network_name, c.state.replace("_", " "), c.seconds + " s", c.who_last4 ? "…" + c.who_last4 : ""]
        .forEach(x => tr.appendChild(phEl("td", "", x)));
      t.appendChild(tr);
    });
    body.appendChild(t);
  }
  if ((s.registrations || []).length) {
    body.appendChild(phEl("div", "ph-sub", "Sign-in"));
    const t = phEl("table", "ph-tbl");
    s.registrations.forEach(r => {
      const tr = phEl("tr");
      tr.appendChild(phEl("td", "", r.name));
      const td = phEl("td");
      td.appendChild(phBadge(r.state, r.registered === true ? "pass" : r.registered === false ? "fail" : "info"));
      tr.appendChild(td);
      t.appendChild(tr);
    });
    body.appendChild(t);
  }
}

function phRenderNode(s) {
  const body = phBody("node");
  if (!body) return;
  if (!s || !s.found) {
    phSetCard("node", "info", "NONE", "—");
    phNote(body, (s && s.note) || "No data");
    return;
  }
  phSetCard("node", "pass", "FOUND", s.nodes.length + " node" + (s.nodes.length === 1 ? "" : "s"));
  s.nodes.forEach(n => {
    const blk = phEl("div", "ph-blk");
    const hdr = phEl("div", "ph-blk-hdr", "Node " + n.node);
    hdr.appendChild(phBadge(n.role, n.is_phone_bridge ? "pass" : "info"));
    hdr.appendChild(phBadge(n.managed_by, "info"));
    blk.appendChild(hdr);
    const ap = n.autopatch;
    const opts = ap ? Object.entries(ap.options || {}).map(e => e[0] + "=" + e[1]).join(", ") : "";
    const sx = Object.entries(n.simplex || {}).map(e => e[0] + " " + e[1]).join(", ");
    blk.appendChild(phKV([
      ["Mode", n.mode + " (duplex " + n.duplex + ")"],
      ["Channel", n.rxchannel],
      ["In [nodes]", n.in_nodes_list ? (n.nodes_line || "yes") : "no"],
      ["Dialing context", n.context],
      ["Dial code", ap ? phStar(ap.code) + (opts ? "  —  " + opts : "") : "none"],
      ["Hang-up", (n.hangup || []).map(h => phStar(h.code) + " " + h.kind).join(", ") || "none"],
      ["Patch on / off", (n.patch_on || n.patch_off) ? phStar(n.patch_on) + " / " + phStar(n.patch_off) : ""],
      ["Key transmitter", phStar(n.ptt)],
      ["Function list", n.functions],
      ["Simplex timing", sx],
      ["Written in", n.file],
    ]));
    body.appendChild(blk);
  });
}

function phRenderNets(s, live) {
  const body = phBody("nets");
  if (!body) return;
  if (!s || !s.found) {
    phSetCard("nets", "info", "NONE", "—");
    phNote(body, (s && s.note) || "No data");
    return;
  }
  const regs = {};
  (live && live.found ? live.registrations || [] : []).forEach(r => { regs[r.id] = r; });
  phSetCard("nets", "pass", "FOUND", s.networks.length + " network" + (s.networks.length === 1 ? "" : "s"));
  s.networks.forEach(n => {
    const blk = phEl("div", "ph-blk");
    const hdr = phEl("div", "ph-blk-hdr", n.name);
    hdr.appendChild(phBadge(n.type_label, "info"));
    hdr.appendChild(phBadge(n.source, "info"));
    blk.appendChild(hdr);
    const r = regs[n.id];
    let signIn = "";
    if (!n.registers) signIn = n.type === "sip_ip" ? "no login (matched by address)" : "does not sign in";
    else if (r) signIn = r.state;
    else signIn = live && live.found ? "unknown" : "Asterisk not running";
    blk.appendChild(phKV([
      ["Server", n.host ? n.host + (n.port ? ":" + n.port : "") : ""],
      ["Username", n.username],
      ["Password", n.type === "sip_ip" ? "" : (n.has_secret ? "set" : "MISSING")],
      ["Caller ID", n.caller_id],
      ["Sign-in", signIn],
      ["Incoming context", n.context],
      ["Matched address", n.match],
      ["Written in", n.file],
    ]));
    body.appendChild(blk);
  });
  (s.transports || []).forEach(t => {
    const blk = phEl("div", "ph-blk");
    const hdr = phEl("div", "ph-blk-hdr", "SIP transport " + t.name);
    hdr.appendChild(phBadge(t.source, "info"));
    blk.appendChild(hdr);
    blk.appendChild(phKV([
      ["Protocol / bind", [t.protocol, t.bind].filter(Boolean).join("  ")],
      ["Home network", t.local_net],
      ["Public address", [t.external_signaling, t.external_media].filter((v, i, a) => v && a.indexOf(v) === i).join(", ")],
    ]));
    body.appendChild(blk);
  });
}

function phRenderDialing(s, nets) {
  const body = phBody("dial");
  if (!body) return;
  if (!s || !s.found) {
    phSetCard("dial", "info", "NONE", "—");
    phNote(body, (s && s.note) || "No data");
    return;
  }
  const names = {};
  ((nets && nets.networks) || []).forEach(n => { names[n.id] = n.name; });
  const miss = s.missing_contexts || [];
  phSetCard("dial", miss.length ? "fail" : "pass", miss.length ? "MISSING" : "FOUND",
            s.outgoing.length + " context" + (s.outgoing.length === 1 ? "" : "s"));
  miss.forEach(c => phNote(body, "Context " + c + " is named by an autopatch code but is not in extensions.conf"));
  body.appendChild(phEl("div", "ph-sub", "Outgoing"));
  s.outgoing.forEach(o => {
    const blk = phEl("div", "ph-blk");
    if (o.kind === "dashboard") {
      const hdr = phEl("div", "ph-blk-hdr", names[o.network] || o.network);
      hdr.appendChild(phBadge(o.dialing, "info"));
      blk.appendChild(hdr);
      blk.appendChild(phKV([
        ["Number sent as", o.number_format],
        ["911", o.e911 ? "allowed" : "off"],
        ["International", o.international ? "allowed" : "off"],
        ["Blocked groups", o.blocked && o.blocked.length ? o.blocked.length + ":  " + o.blocked.join("  ") : "none"],
        ["Dials", (o.dials || []).join("  ")],
      ]));
    } else {
      const hdr = phEl("div", "ph-blk-hdr", "Context " + o.context);
      hdr.appendChild(phBadge("as written", "info"));
      blk.appendChild(hdr);
      if (o.lines && o.lines.length) {
        blk.appendChild(phEl("pre", "ph-pre", o.lines.join("\n") + (o.truncated ? "\n…" : "")));
      }
    }
    body.appendChild(blk);
  });
  if (s.outgoing.some(o => /^dvs-radio-/.test(o.context))) {
    const det = document.createElement("details");
    det.className = "ph-howto";
    const sm = document.createElement("summary");
    sm.textContent = "Why there's a short dvs-radio context (show/hide)";
    det.appendChild(sm);
    [
      "*61 from the radio lands in the dvs-radio context. It doesn't dial: it hands the number to the dashboard and hangs up, which ends the autopatch straight away.",
      "The dashboard then places the call through the network's dialing rules (the dvs-node and dvs-net contexts shown here), the same way as its own Dial button. The call joins the node like an incoming call, so the radio only transmits while the far end talks.",
      "Before sysmon 6.13.67.4 this card started only from the *61 context, so it stopped at the dvs-radio step and didn't show the dialing rules. It now also starts from each phone node's own context.",
    ].forEach(t => det.appendChild(phEl("p", "", t)));
    body.appendChild(det);
  }
  if ((s.incoming || []).length) {
    body.appendChild(phEl("div", "ph-sub", "Incoming"));
    s.incoming.forEach(i => {
      const blk = phEl("div", "ph-blk");
      const hdr = phEl("div", "ph-blk-hdr", names[i.network] || i.network);
      hdr.appendChild(phBadge(i.mode, /straight|missing|no context/.test(i.mode) ? "warn" : "info"));
      blk.appendChild(hdr);
      blk.appendChild(phKV([
        ["Context", i.context],
        ["Trusted numbers", i.trusted_last4.length ? i.trusted_last4.map(x => "…" + x).join("  ") : ""],
        ["Connects to node", i.connects_node],
        ["Answered only while dashboard Phone tab is open", i.busy_when_tab_closed ? "yes" : (i.mode === "asks for a PIN" || i.mode.indexOf("straight") === 0 || i.mode.indexOf("only trusted") === 0 ? "no" : "")],
      ]));
      if (i.lines && i.lines.length) blk.appendChild(phEl("pre", "ph-pre", i.lines.join("\n")));
      body.appendChild(blk);
    });
  }
}

function phRenderHealth(s) {
  if (!s || !s.found) {
    phSetCard("health", "info", "—", "—");
    const b = phBody("health"); if (b) phNote(b, "No data");
    return;
  }
  const checks = (s.checks || []).map(c => Object.assign({}, c, {status: c.status === "ok" ? "pass" : c.status}));
  const overall = checks.some(c => c.status === "fail") ? "fail" : checks.some(c => c.status === "warn") ? "warn"
                : checks.some(c => c.status === "pass") ? "pass" : "info";
  renderRegChecks(checks, overall, {body: "ph-health-body", meta: "ph-health-meta", status: "ph-health-status"});
}

function phRenderCalls(s) {
  const body = phBody("calls");
  if (!body) return;
  if (!s || !s.found) {
    phSetCard("calls", "info", "N/A", "—");
    phNote(body, (s && s.note) || "No data");
    return;
  }
  phSetCard("calls", "info", "LOG", s.calls.length + " attempt" + (s.calls.length === 1 ? "" : "s"));
  if (!s.calls.length) { phNote(body, s.note || "No phone call attempts in the last 24 hours"); return; }
  const t = phEl("table", "ph-tbl");
  const head = phEl("tr");
  ["When", "Direction", "Network", "Number"].forEach(h => head.appendChild(phEl("th", "", h)));
  t.appendChild(head);
  s.calls.forEach(c => {
    const tr = phEl("tr");
    [c.time, c.direction, c.network_name, c.last4 ? "…" + c.last4 : ""].forEach(x => tr.appendChild(phEl("td", "", x)));
    t.appendChild(tr);
  });
  body.appendChild(t);
  body.appendChild(phEl("div", "ph-note", "Each row is a call attempt seen in the last 24 hours (a ring, not proof it was answered)"
                        + (s.sources && s.sources.length ? " · from " + s.sources.join(", ") : "")
                        + (s.note ? " · " + s.note : "")));
}

function phHoipLink(url) {
  if (!/^https:\/\/([a-z0-9-]+\.)*hamsoverip\.com\//i.test(url || "")) return "";
  const a = phEl("a", "btn btn-muted btn-sm ph-link", "Open HOIP website");
  a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer";
  return a;
}

function phCardText(pfx) {
  const body = document.getElementById("ph-" + pfx + "-body");
  if (!body) return "";
  const t = x => (x || "").replace(/\s+/g, " ").trim();
  const txt = id => t((document.getElementById(id) || {}).textContent);
  const card = body.closest(".s3-card");
  const title = card ? t((card.querySelector(".s3-card-title") || {}).textContent) : pfx;
  const sum = [txt("ph-" + pfx + "-status"), txt("ph-" + pfx + "-meta")].filter(x => x && x !== "—").join(", ");
  const out = ["Phone · " + title + (sum ? " — " + sum : ""),
               "sysmon v__VERSION__ · " + new Date().toLocaleString(), ""];
  const walk = el => {
    for (const n of el.children) {
      const c = n.classList;
      if (c.contains("ph-nocopy")) continue;
      if (c.contains("ph-kv")) {
        const kids = [...n.children];
        for (let i = 0; i + 1 < kids.length; i += 2) {
          const a = kids[i + 1].querySelector("a");
          out.push(t(kids[i].textContent) + ": " + (a ? a.href : t(kids[i + 1].textContent)));
        }
      } else if (c.contains("ast-check-row")) {
        const g = sel => t((n.querySelector(sel) || {}).textContent);
        out.push(t(n.lastElementChild ? n.lastElementChild.textContent : "") + " " +
                 g(".ast-check-title") + (g(".ast-check-value") ? " — " + g(".ast-check-value") : ""));
      } else if (c.contains("ast-check-note")) {
        out.push("    " + t(n.textContent));
      } else if (n.tagName === "TABLE") {
        n.querySelectorAll("tr").forEach(tr => out.push([...tr.children].filter(x => !x.classList.contains("ph-nocopy"))
                                                           .map(x => t(x.textContent)).join(" | ")));
      } else if (n.tagName === "PRE") {
        out.push(n.textContent.replace(/\s+$/, ""));
      } else if (c.contains("ph-blk-hdr")) {
        out.push("", [...n.childNodes].filter(x => !(x.classList && x.classList.contains("ph-nocopy")))
                                      .map(x => t(x.textContent)).filter(Boolean).join(" · "));
      } else if (c.contains("ph-sub")) {
        out.push("", t(n.textContent).toUpperCase());
      } else if (n.children.length && !c.contains("ph-note") && !c.contains("stub-panel")) {
        walk(n);
      } else if (t(n.textContent)) {
        out.push(t(n.textContent));
      }
    }
  };
  walk(body);
  return out.join("\n").replace(/\n{3,}/g, "\n\n").trim() + "\n";
}

function rtHeader() {
  const vals = Object.values(_rtResult);
  if (!vals.length) return;
  const s = vals.includes("fail") ? "fail" : vals.includes("warn") ? "warn" : vals.includes("pass") ? "pass" : "info";
  phSetCard("rt", s, s.toUpperCase(), Object.keys(_rtResult).length + " of 3 run");
}

function rtChecks(boxId, key, checks) {
  const cs = (checks || []).map(c => Object.assign({}, c, {status: c.status === "ok" ? "pass" : c.status}));
  const st = cs.some(c => c.status === "fail") ? "fail" : cs.some(c => c.status === "warn") ? "warn"
           : cs.some(c => c.status === "pass") ? "pass" : "info";
  renderRegChecks(cs, st, {body: boxId});
  _rtResult[key] = st; rtHeader();
}

function phRenderAll() {
  const d = _phData;
  const live = phSec(d, "live"), nets = phSec(d, "networks");
  phRenderLive(live);
  phRenderNode(phSec(d, "node"));
  phRenderNets(nets, live);
  phRenderHoip(phSec(d, "hoip"));
  phRenderDialing(phSec(d, "dialing"), nets);
  phRenderHealth(phSec(d, "health"));
  phRenderModules(phSec(d, "modules"));
  phRenderCalls(phSec(d, "calls"));
}

function pmConfText(r) {
  if (r.conf === "-") return "any one";
  const w = (r.where || []).filter(x => x !== "modules.conf");
  return r.conf + (w.length ? " (" + w.join(", ") + ")" : "");
}

function pmCell(text, cls) { return phEl("td", cls || "", text); }

function pmTable(rows) {
  const t = phEl("table", "ph-tbl");
  const head = phEl("tr");
  ["Module", "modules.conf", "Now", "File"].forEach(h => head.appendChild(phEl("th", "", h)));
  head.appendChild(phEl("th", "ph-nocopy", "Change"));
  t.appendChild(head);
  rows.forEach(r => {
    const tr = phEl("tr");
    const name = pmCell(r.module + (r.locked ? "  🔒" : ""));
    name.title = r.why + (r.locked ? " -- locked: stopping it would take down the nodes or every call" : "");
    if (r.shown) name.title += " (running: " + r.shown + ")";
    tr.appendChild(name);
    tr.appendChild(pmCell(pmConfText(r), r.conf === "noload" ? "pm-warn" : (r.conf === "not listed" ? "pm-dim" : "")));
    tr.appendChild(pmCell(r.running === null ? "?" : (r.running ? "running" : "stopped"),
                          r.running === null ? "pm-dim" : (r.running ? "pm-ok" : "pm-bad")));
    tr.appendChild(pmCell(r.file === null ? "?" : (r.file ? "yes" : "MISSING"),
                          r.file === false ? "pm-bad" : ""));
    tr.appendChild(pmControls(r));
    tr.dataset.module = r.module;
    t.appendChild(tr);
  });
  return t;
}

function phRenderModules(s) {
  const body = phBody("mods");
  if (!body) return;
  if (!s || !s.found) {
    phSetCard("mods", "info", "—", "—");
    phNote(body, (s && s.note) || "No data");
    return;
  }
  const gs = s.groups || [];
  const conf = gs.filter(g => g.configured);
  let st = ["info", "—"];
  if (!s.asterisk_running) st = ["warn", "ASTERISK DOWN"];
  else if (conf.some(g => g.state === "missing")) st = ["fail", "MISSING"];
  else if (conf.length && conf.every(g => g.state === "ready")) st = ["pass", "READY"];
  else if (conf.some(g => g.state === "off")) st = ["info", "PART OFF"];
  phSetCard("mods", st[0], st[1], gs.map(g => (g.feature === "reverse" ? "reverse" : "autopatch") + ": " + g.state).join(" · "));
  if (s.note) phNote(body, s.note);
  _pmRoot = !!s.root;
  const rows = s.rows || [];
  gs.forEach(g => {
    const blk = phEl("div", "ph-blk");
    const hdr = phEl("div", "ph-blk-hdr");
    hdr.appendChild(phEl("span", "", g.label));
    const b = PM_STATE[g.state] || ["info", g.state.toUpperCase()];
    hdr.appendChild(phBadge(b[1], b[0]));
    hdr.dataset.feature = g.feature;
    hdr.appendChild(pmGroupButtons(g, rows));
    blk.appendChild(hdr);
    if (_pmLast && _pmLast.feature === g.feature)
      blk.appendChild(phEl("pre", "ph-pre " + (_pmLast.ok ? "" : "pm-warn"), _pmLast.lines.join("\n")));
    if (!g.configured) phNote(blk, "Not set up on this node, so nothing here is needed for it.");
    else if (g.state === "missing") phNote(blk, "Not running or missing: " + g.not_running.join(", "));
    else if (g.state === "off") phNote(blk, "Turned off: its own modules are set to noload and stopped.");
    const own = rows.filter(r => r.features.length === 1 && r.features[0] === g.feature);
    if (own.length) { blk.appendChild(phEl("div", "ph-sub", "Only this feature uses")); blk.appendChild(pmTable(own)); }
    body.appendChild(blk);
  });
  const shared = rows.filter(r => r.features.length > 1);
  if (shared.length) {
    const blk = phEl("div", "ph-blk");
    blk.appendChild(phEl("div", "ph-sub", "Used by both  (🔒 = locked)"));
    blk.appendChild(pmTable(shared));
    body.appendChild(blk);
  }
  const foot = [];
  if (s.moddir) foot.push("Module folder: " + s.moddir);
  else foot.push("Couldn't find Asterisk's module folder, so file checks show ?");
  foot.push("modules.conf autoload: " + (s.autoload ? "on (unlisted modules load too)" : "off (only listed modules load)"));
  foot.forEach(x => phNote(body, x));
  if (s.missing_files && s.missing_files.length) { body.appendChild(pmInstallBlock(s)); pmJobPoll(); }
  if (!s.root) phNote(body, "sysmon isn't running as root, so the buttons can't change anything.");
}

function pmInstallBlock(s) {
  const blk = phEl("div", "ph-blk");
  blk.id = "pm-install";
  blk.appendChild(phEl("div", "ph-sub", "Install options"));
  phNote(blk, "Missing from the Pi: " + s.missing_files.join(", "));
  const pk = s.packages || [];
  if (pk.length) {
    phNote(blk, "These come in the package " + pk.join(", ") + ". Reinstalling it puts the files back.");
    const row = phEl("div", "pm-btns ph-nocopy");
    row.style.padding = "0 .9rem .3rem";
    const lab = phEl("label", "pm-dim");
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = true; cb.id = "pm-upd";
    lab.appendChild(cb); lab.appendChild(document.createTextNode(" Update the package list first"));
    row.appendChild(lab);
    if (_pmRoot) row.appendChild(pmBtn("Reinstall " + pk.join(", "), false, "Runs apt-get install --reinstall",
                                       () => pmReinstall(pk)));
    blk.appendChild(row);
  } else {
    phNote(blk, "Couldn't tell which package should have these files. Steps: 1) run  dpkg -l | grep asterisk  to see the Asterisk packages; 2) reinstall the main one with  sudo apt-get install --reinstall <package>; 3) press Re-check.");
  }
  phNote(blk, "Or by hand, in a terminal on the Pi:");
  blk.appendChild(phEl("pre", "ph-pre", "sudo apt-get update\nsudo apt-get install --reinstall -y " + (pk.join(" ") || "<package>")));
  const out = phEl("pre", "ph-pre ph-nocopy");
  out.id = "pm-job-out"; out.style.display = "none";
  blk.appendChild(out);
  return blk;
}

async function pmReinstall(pk) {
  const upd = !!(document.getElementById("pm-upd") || {}).checked;
  if (!await confirm(`Reinstall ${pk.join(", ")}?\n\n` + (upd ? "Updates the package list first, then reinstalls. " : "") +
                     "This can take a few minutes. If the package restarts Asterisk, any call drops and the nodes are briefly down.")) return;
  const r = await api("/api/phone/modules", "POST", {op: "reinstall", update: upd});
  if (!r || !r.ok) { toast((r && r.message) || "Couldn't start", "err", 7000); return; }
  toast(r.message || "Started", "ok");
  pmJobPoll();
}

async function pmJobPoll() {
  if (_pmJobTimer) { clearTimeout(_pmJobTimer); _pmJobTimer = null; }
  const j = await api("/api/net/job");
  const out = document.getElementById("pm-job-out");
  if (!j || j.action !== "phone_reinstall") return;
  if (out) {
    out.style.display = "";
    out.textContent = (j.lines || []).slice(-40).join("\n") + (j.status === "running" ? "\n… running (" + j.elapsed + "s)" : "");
    out.scrollTop = out.scrollHeight;
  }
  if (j.status === "running") { _pmJobTimer = setTimeout(pmJobPoll, 2000); return; }
  if (!out || out.dataset.done === j.finished_key) return;
  out.dataset.done = j.finished_key;
  toast(j.success ? "Reinstall finished" : "Reinstall failed -- see the output on the card", j.success ? "ok" : "err", 7000);
  if (j.success) setTimeout(pmReload, 1500);
}

function pmGroupButtons(g, rows) {
  const w = phEl("span", "pm-btns ph-nocopy");
  w.style.marginLeft = "auto";
  if (!g.configured || !_pmRoot) return w;
  w.appendChild(pmBtn("Activate", false, "Set load and start every module this feature needs",
                      () => pmFeature(g, rows, true)));
  w.appendChild(pmBtn("Deactivate", false, "Set noload and stop the modules only this feature uses",
                      () => pmFeature(g, rows, false)));
  return w;
}

async function pmFeature(g, rows, on) {
  const other = (_phData.sections && phSec(_phData, "modules") || {}).groups || [];
  const otherOn = other.some(x => x.feature !== g.feature && x.configured);
  const free = rows.filter(r => !r.locked && r.features.indexOf(g.feature) >= 0);
  let q;
  if (on) {
    q = `Activate ${g.label}?\n\nSets load in modules.conf for:\n  ${free.map(r => r.module).join("\n  ") || "(nothing)"}\n\nand starts any that are stopped. modules.conf is backed up first.`;
  } else {
    const alone = free.filter(r => r.features.length === 1 || !otherOn);
    const kept = free.filter(r => alone.indexOf(r) < 0);
    q = `Deactivate ${g.label}?\n\nSets noload and stops:\n  ${alone.map(r => r.module).join("\n  ") || "(nothing)"}` +
        (kept.length ? `\n\nLeft running (the other feature uses them):\n  ${kept.map(r => r.module).join("\n  ")}` : "") +
        `\n\nmodules.conf is backed up first.`;
  }
  if (!await confirm(q)) return;
  const r = await api("/api/phone/modules", "POST", {op: on ? "activate" : "deactivate", feature: g.feature});
  if (r) _pmLast = {feature: g.feature, lines: [r.message].concat(r.details || []), ok: r.ok};
  await pmShowResult(r);
  pmReload();
}

function pmBtn(label, dis, title, fn) {
  const b = phEl("button", "btn btn-muted btn-sm", label);
  b.disabled = !!dis; if (title) b.title = title;
  b.onclick = fn;
  return b;
}

function pmControls(r) {
  const td = phEl("td", "ph-nocopy");
  if (r.locked || !_pmRoot) return td;
  const w = phEl("div", "pm-btns");
  w.appendChild(pmBtn("Load", r.conf === "load", "Set 'load' in modules.conf (at next Asterisk restart)",
                      () => pmChange("conf", r.module, "load")));
  w.appendChild(pmBtn("No load", r.conf === "noload", "Set 'noload' in modules.conf (at next Asterisk restart)",
                      () => pmChange("conf", r.module, "noload")));
  w.appendChild(pmBtn("Start", r.running !== false || r.file === false,
                      r.file === false ? "The module file is missing -- see install options" : "Load it now",
                      () => pmChange("live", r.module, "start")));
  w.appendChild(pmBtn("Stop", r.running !== true, "Unload it now", () => pmChange("live", r.module, "stop")));
  td.appendChild(w);
  return td;
}

async function pmReload() {
  const d = await api("/api/phone?section=modules");
  if (!d || !d.ok || !d.sections || !d.sections.length) return;
  _phData.sections = (_phData.sections || []).filter(x => x.id !== "modules").concat(d.sections);
  phRenderModules(d.sections[0]);
}

async function pmShowResult(r) {
  if (!r) { toast("Server unreachable", "err"); return; }
  toast(r.message || (r.ok ? "Done" : "Failed"), r.ok ? "ok" : "err", r.ok ? 3500 : 7000);
  (r.warnings || []).forEach(w => toast(w, "err", 8000));
  if (!r.ok && r.restart_hint && await confirm("Restart Asterisk now?\n\nThis drops any call and briefly takes the nodes down.")) {
    const s = await api("/api/svc", "POST", {unit: "asterisk.service", action: "restart"});
    toast(s && s.ok ? "Asterisk restarting" : ((s && s.message) || "Restart failed"), s && s.ok ? "ok" : "err");
    setTimeout(pmReload, 6000);
  }
}

async function pmChange(op, module, value) {
  if (!await confirm(PM_ASK[op + ":" + value](module))) return;
  const r = await api("/api/phone/modules", "POST", {op: op, module: module, value: value});
  await pmShowResult(r);
  pmReload();
}

async function phPollLive() {
  const d = await api("/api/phone?section=live");
  if (!d || !d.ok || !d.sections || !d.sections.length) return;
  const secs = (_phData.sections || []).filter(x => x.id !== "live");
  _phData.sections = secs.concat(d.sections);
  phRenderLive(d.sections[0]);
  phRenderNets(phSec(_phData, "networks"), d.sections[0]);
}

// ---- card: Hams Over IP ----
function phRenderHoip(s) {
  const card = document.getElementById("ph-hoip-card");
  if (!card) return;
  if (!s || !s.found || !(s.accounts || []).length) { card.style.display = "none"; return; }
  card.style.display = "";
  const body = phBody("hoip");
  if (!body) return;
  let fails = 0, warns = 0, passes = 0;
  s.accounts.forEach((a, i) => {
    const blk = phEl("div", "ph-blk");
    blk.appendChild(phEl("div", "ph-blk-hdr", a.name + (a.callsign ? " · " + a.callsign : "")));
    blk.appendChild(phKV([
      ["Server", a.host + (a.port ? ":" + a.port : "")],
      ["Extension", a.extension || a.username],
      ["SIP username", a.username],
      ["Caller ID", a.caller_id],
      ["Incoming calls go to", a.context],
      ["Pi SIP port", a.sip_port ? "UDP " + a.sip_port : ""],
      ["Audio ports", a.rtp && a.rtp.length === 2 ? "UDP " + a.rtp[0] + "-" + a.rtp[1] : ""],
      ["Voicemail", a.voicemail_access ? "dial " + (a.voicemail_dial || a.voicemail_access) : ""],
      ["Website", phHoipLink(a.login_url)],
    ]));
    const box = phEl("div");
    box.id = "ph-hoip-checks-" + i;
    blk.appendChild(box);
    body.appendChild(blk);
    const checks = (a.checks || []).map(c => Object.assign({}, c, {status: c.status === "ok" ? "pass" : c.status}));
    fails  += checks.filter(c => c.status === "fail").length;
    warns  += checks.filter(c => c.status === "warn").length;
    passes += checks.filter(c => c.status === "pass").length;
    renderRegChecks(checks, null, {body: box.id});
  });
  const overall = fails ? "fail" : warns ? "warn" : passes ? "pass" : "info";
  phSetCard("hoip", overall, overall.toUpperCase(),
            fails ? fails + " issue" + (fails === 1 ? "" : "s")
                  : warns ? warns + " warning" + (warns === 1 ? "" : "s") : "all clear");
  phNote(body, "Password and PIN are never shown. The only thing sent from the Pi is one test packet to the HOIP server (no login); nothing on the Pi is changed.");
}

// ========================================================================
// TAB: Tune
// ========================================================================
// ---- general ----
function toggleRptCard() {
  toggleCard("rn-body", "rn-toggle");
}

async function loadRptNodes() {
  const body   = document.getElementById("rn-body");
  const status = document.getElementById("rn-status");
  if (!body) return;
  const resp = await api("/api/rpt/nodesettings");
  if (!resp || !resp.ok) {
    if (status) status.textContent = "unavailable";
    body.innerHTML = `<div class="stub-panel" style="min-height:60px">${esc((resp && resp.message) || "Could not read rpt.conf")}</div>`;
    return;
  }
  window.rnData = resp;
  if (status) status.textContent = `${resp.nodes.length} node${resp.nodes.length === 1 ? "" : "s"}`;
  renderRptNodes();
}

function rnSelect(id, list, cur, disabled) {
  const known = list.some(([v]) => v === cur);
  const extra = known ? "" : `<option value="${esc(cur)}" selected>${esc(cur || "(blank)")} – value in file</option>`;
  const opts = list.map(([v, t]) =>
    `<option value="${v}"${v === cur ? " selected" : ""}>${esc(t)}</option>`).join("");
  return `<select id="${id}" ${disabled ? "disabled" : ""} onchange="rnChanged('${id.split("-")[1]}')"
    style="font-family:var(--sans);font-size:var(--fs-base);background:var(--surface2);border:1px solid var(--border2);border-radius:.3rem;padding:.25rem .4rem;color:var(--text);max-width:100%">${extra}${opts}</select>`;
}

function rnSrc(src) {
  return `<div style="font-size:var(--fs-xs);color:#ffffff">${esc(src)}</div>`;
}

function rnValues(id) {
  const g = k => document.getElementById(`rn-${id}-${k}`);
  if (!g("duplex")) return null;
  return {duplex: g("duplex").value, telemdefault: g("telemdefault").value,
          hangtime: g("hangtime").value.trim(), linktolink: g("linktolink").checked ? "yes" : "no"};
}

function rnChanges(id) {
  const cur = rnValues(id), orig = window.rnOrig[id];
  if (!cur || !orig) return {};
  const out = {};
  for (const k of Object.keys(cur)) if (cur[k] !== orig[k]) out[k] = cur[k];
  return out;
}

function rnChanged(id, quiet) {
  const cur = rnValues(id);
  if (!cur) return;
  const row = (window.rnData && window.rnData.nodes || []).find(n => n.node === id);
  const ht = document.getElementById(`rn-${id}-hangtime`);
  if (ht && row && row.editable) ht.disabled = cur.duplex === "0";
  const warn = [];
  if (cur.duplex === "0") warn.push("hangtime has no effect with duplex 0.");
  if (cur.linktolink === "yes" && cur.duplex !== "0") warn.push("linktolink only works with duplex 0.");
  const hv = Number(cur.hangtime);
  if (cur.hangtime === "" || !Number.isInteger(hv) || hv < 0 || hv > 60000)
    warn.push("hangtime must be a whole number from 0 to 60000.");
  const w = document.getElementById(`rn-${id}-warn`);
  if (w) w.textContent = warn.join(" ");
  if (!quiet) rnDirtyAll();
}

function rnDirtyAll() {
  const d = window.rnData;
  const dirty = !!d && d.nodes.some(n => Object.keys(rnChanges(n.node)).length);
  const el = document.getElementById("rn-dirty");
  if (el) el.style.display = dirty ? "" : "none";
  return dirty;
}

async function saveRptNodes() {
  const d = window.rnData;
  const res = document.getElementById("rn-result");
  if (!d || !res) return;
  const todo = d.nodes.filter(n => n.editable && Object.keys(rnChanges(n.node)).length);
  if (!todo.length) { res.style.color = "var(--text)"; res.textContent = "No changes to save."; return; }
  for (const n of todo) {
    const c = rnChanges(n.node);
    if ("hangtime" in c) {
      const hv = Number(c.hangtime);
      if (c.hangtime === "" || !Number.isInteger(hv) || hv < 0 || hv > 60000) {
        res.style.color = "var(--red)";
        res.textContent = `Node ${n.node}: hangtime must be a whole number from 0 to 60000.`;
        return;
      }
    }
  }
  const reload = document.getElementById("rn-reload").checked;
  const btn = document.getElementById("rn-save-btn");
  if (btn) btn.disabled = true;
  res.style.color = "var(--text)";
  res.textContent = "Saving…";
  const lines = [];
  let allOk = true;
  for (let i = 0; i < todo.length; i++) {
    const n = todo[i];
    const r = await api("/api/rpt/nodesettings", "POST",
      {node: n.node, changes: rnChanges(n.node), reload: reload && i === todo.length - 1});
    const ok = !!(r && r.ok);
    allOk = allOk && ok;
    lines.push(`${ok ? "✓" : "✗"} ${(r && r.message) || `Node ${n.node}: no response`}`);
  }
  if (btn) btn.disabled = false;
  await loadRptNodes();
  const res2 = document.getElementById("rn-result");
  if (res2) {
    res2.style.color = allOk ? "var(--green)" : "var(--red)";
    res2.textContent = lines.join("\n");
  }
}

function toggleCard(bodyId, btnId) {
  const body = document.getElementById(bodyId);
  if (!body) return;
  setCardOpen(bodyId, btnId, body.classList.contains("hidden"));
}

function toggleTuneCard() {
  toggleCard("su-tune-body", "su-tune-toggle");
}

function showRadioDialogError(msg) {
  const el = document.getElementById("radio-dialog-error");
  if (el) { el.textContent = "✗ " + msg; el.style.display = "block"; }
}

function closeRadioDialog() {
  document.getElementById("radio-dialog-overlay").style.display = "none";
  document.getElementById("radio-dialog-preset-row").style.display = "none";
  document.getElementById("radio-dialog-reload-row").style.display = "none";
  showRadioDialogFormView();
  window.radioDialogSlot = null;
  window.radioDialogSource = null;
  window.radioDialogMode = null;
  window.radioDialogDriver = null;
}

async function confirmRadioDialog() {
  if (window.radioDialogMode === "tunesave") {
    await confirmTuneSaveDialog();
    return;
  }

  const slot = window.radioDialogSlot;
  if (slot === null || slot === undefined) return;
  const title = document.getElementById("radio-dialog-title")?.value?.trim() || "";

  const driver = "simpleusb";
  const payload = {
    slot: slot,
    title: title,
    driver: driver,
    ...getTuneValues(),
  };

  try {
    const result = await api("/api/radio/presets", "POST", payload);
    if (!result || !result.ok) {
      toast(`✗ Failed: ${result?.message || "unknown error"}`, 0);
      return;
    }

    toast(`✓ ${result.message}`, 2);
    closeRadioDialog();

    await loadRadioPresets();
    updateRadioButtons();
    restoreActiveRadioButton();
  } catch (e) {
    toast(`✗ Error: ${e.message}`, 0);
  }
}

async function confirmTuneSaveDialog() {
  const driver = window.radioDialogDriver;
  if (!driver) return;

  if (window._radioRestartBusy) {
    showRadioDialogError("Restart in progress — try again shortly");
    return;
  }

  const fields  = getTuneValues();
  const slotVal = document.getElementById("radio-dialog-preset-select")?.value || "";
  const reload  = !!document.getElementById("radio-dialog-reload-toggle")?.checked;
  const title   = document.getElementById("radio-dialog-title")?.value?.trim() || "";

  const payload = { driver, ...fields, reload };
  if (slotVal) {
    payload.preset_slot  = parseInt(slotVal);
    payload.preset_title = title;
  }

  const saveBtn = document.getElementById("radio-dialog-save-btn");
  if (saveBtn) saveBtn.disabled = true;
  document.getElementById("radio-dialog-error").style.display = "none";

  try {
    const result = await api("/api/radio/tune/save", "POST", payload);
    if (!result || !result.ok) {
      showRadioDialogError(result?.message || "Unknown error — check if running as root");
      return;
    }

    if (result.preset_saved === false && result.preset_msg) {
      toast(`⚠ ${result.preset_msg}`, 0);
    }

    if (!reload) {
      toast("✓ Saved — " + result.message, 2);
      closeRadioDialog();
      refreshTuneCardAfterSave();
      return;
    }

    if (result.restart !== "started") {
      showRadioDialogError(`Saved, but restart not started: ${result.restart_msg || "unknown"}`);
      return;
    }

    document.getElementById("radio-dialog-form-view").style.display = "none";
    document.getElementById("radio-dialog-restart-view").style.display = "block";
    document.getElementById("radio-dialog-restart-msg").style.display = "none";
    document.getElementById("radio-dialog-restart-dismiss").style.display = "none";

    setRadioRestartBusy(true);
    const r = await pollRadioStackStatus();
    setRadioRestartBusy(false);

    if (r.ok) {
      toast("✓ Saved & Asterisk restarted — " + result.message, 2);
      closeRadioDialog();
      refreshTuneCardAfterSave();
    } else {
      const rmsg = document.getElementById("radio-dialog-restart-msg");
      if (rmsg) { rmsg.textContent = "⚠ " + r.msg; rmsg.style.display = "block"; }
      document.getElementById("radio-dialog-restart-dismiss").style.display = "inline-block";
    }
  } catch (e) {
    showRadioDialogError(e.message);
  } finally {
    if (saveBtn) saveBtn.disabled = false;
  }
}

function refreshTuneCardAfterSave() {
  loadSimpleUSBTune();
  loadRadioPresets().then(() => {
    updateRadioButtons();
    restoreActiveRadioButton();
  });
}

// ---- card: Node Settings — rpt.conf ----
function renderRptNodes() {
  const body = document.getElementById("rn-body");
  const d = window.rnData;
  if (!body || !d) return;
  window.rnOrig = {};
  if (!d.nodes.length) {
    body.innerHTML = `<div class="stub-panel" style="min-height:60px">No nodes found in ${esc(d.path)}</div>`;
    return;
  }
  const lab = "font-size:var(--fs-base);color:var(--text);display:grid;gap:.2rem;align-content:start";
  const rows = d.nodes.map(n => {
    const v = n.values;
    const id = n.node;
    const dis = !n.editable;
    window.rnOrig[id] = {duplex: v.duplex.value, telemdefault: v.telemdefault.value,
                         hangtime: v.hangtime.value, linktolink: v.linktolink.value};
    const lock = dis ? `<div style="font-size:var(--fs-xs);color:var(--amber)">🔒 ${esc(n.locked)}</div>` : "";
    return `
      <div id="rn-row-${id}" style="padding:.7rem .8rem;background:rgba(100,120,140,0.06);border-radius:.4rem;border-left:3px solid var(--blue);display:grid;gap:.5rem">
        <div style="display:flex;gap:.6rem;align-items:baseline;flex-wrap:wrap">
          <strong style="color:var(--blue)">${esc(id)}</strong>
          <span style="font-size:var(--fs-xs);color:#ffffff">${esc(n.role)}${n.private ? " · private" : ""}</span>
        </div>
        ${lock}
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(13rem,1fr));gap:.6rem">
          <label style="${lab}"><span>duplex</span>${rnSelect(`rn-${id}-duplex`, RN_DUPLEX, v.duplex.value, dis)}${rnSrc(v.duplex.source)}</label>
          <label style="${lab}"><span>telemdefault</span>${rnSelect(`rn-${id}-telemdefault`, RN_TELEM, v.telemdefault.value, dis)}${rnSrc(v.telemdefault.source)}</label>
          <label style="${lab}"><span>hangtime (ms)</span>
            <input type="number" id="rn-${id}-hangtime" value="${esc(v.hangtime.value)}" min="0" max="60000" step="100" ${dis ? "disabled" : ""}
              oninput="rnChanged('${id}')" onchange="rnChanged('${id}')"
              aria-label="hangtime in milliseconds (0-60000)"
              style="font-family:var(--sans);font-size:var(--fs-base);background:var(--surface2);border:1px solid var(--border2);border-radius:.3rem;padding:.3rem .5rem;width:7rem;color:var(--text)">
            <div style="font-size:var(--fs-xs);color:#ffffff">Default 5000 ms · range 0–60000 ms</div>
            ${rnSrc(v.hangtime.source)}</label>
          <label style="${lab}"><span>linktolink</span>
            <span style="display:flex;align-items:center;gap:.4rem"><input type="checkbox" id="rn-${id}-linktolink" ${v.linktolink.value === "yes" ? "checked" : ""} ${dis ? "disabled" : ""}
              onchange="rnChanged('${id}')"> full duplex radio link</span>
            ${rnSrc(v.linktolink.source)}</label>
        </div>
        <div id="rn-${id}-warn" style="font-size:var(--fs-xs);color:var(--amber)"></div>
      </div>`;
  }).join("");
  body.innerHTML = `
    <div style="display:grid;gap:1rem;padding:1rem">
      <div style="font-size:var(--fs-base);color:#ffffff;line-height:1.4">
        Values shown are what each node uses. The tag under each one says where it comes from:
        <strong>set on node</strong>, <strong>from</strong> a template, or the ASL3 <strong>default</strong>.
        Saving writes only changed settings into that node's own section of ${esc(d.path)}; templates are never changed.
      </div>
      ${rows}
      <div style="display:flex;gap:.6rem;flex-wrap:wrap;align-items:center">
        <button class="btn btn-blue btn-sm" id="rn-save-btn" onclick="saveRptNodes()" title="Save changed settings">💾 Save</button>
        <button class="btn btn-muted btn-sm" id="rn-reset-btn" onclick="renderRptNodes()" title="Revert to the values in the file">↺ Reset</button>
        <label style="display:flex;align-items:center;gap:.4rem;font-size:var(--fs-base);color:var(--text)">
          <input type="checkbox" id="rn-reload"> Reload app_rpt after save</label>
        <span id="rn-dirty" style="display:none;font-size:var(--fs-base);color:var(--amber)">● unsaved changes</span>
      </div>
      <div style="font-size:var(--fs-xs);color:var(--amber)">Reloading app_rpt drops this system's current links.</div>
      <div id="rn-result" style="font-size:var(--fs-base);white-space:pre-line"></div>
    </div>`;
  d.nodes.forEach(n => rnChanged(n.node, true));
  rnDirtyAll();
}

// ========================================================================
// TAB: Hardware
// ========================================================================
// ---- general ----
let _healthData = null;
async function loadHealth() {
  const d = await api("/api/health");
  const body = document.getElementById("hw-health-body");
  const meta = document.getElementById("hw-health-meta");
  if (!body) return;
  if (!d || !d.checks) {
    if (meta) meta.textContent = "error";
    body.innerHTML = '<div class="stub-panel">Server error</div>';
    return;
  }
  _healthData = d.checks;
  const cls = {pass: "ok", warn: "warn", fail: "hot", unknown: "dim"};
  const word = {pass: "OK", warn: "WARN", fail: "PROBLEM", unknown: "?"};
  const bad = d.checks.filter(c => c.status === "fail").length;
  const warn = d.checks.filter(c => c.status === "warn").length;
  const unk = d.checks.filter(c => c.status === "unknown").length;
  if (meta) meta.textContent = bad ? `${bad} problem${bad > 1 ? "s" : ""}` : warn ? `${warn} warning${warn > 1 ? "s" : ""}`
    : unk ? `OK · ${unk} couldn't be checked` : "all OK";
  body.innerHTML = '<table class="hw-pwr-tbl">' + d.checks.map(c => {
    const rows = (c.rows || []).map(r => `<div class="hw-pwr-note">${esc(r[0])}: ${esc(r[1])}</div>`).join("");
    const note = c.note ? `<div class="hw-pwr-note" style="margin-top:.2rem">${esc(c.note)}</div>` : "";
    return `<tr><td class="hw-pwr-lbl">${esc(c.title)}</td>
      <td class="hw-pwr-val ${cls[c.status] || ""}"><b>${word[c.status] || "?"}</b> — ${esc(c.headline)}
      <details style="margin-top:.15rem"><summary class="hw-pwr-note" style="cursor:pointer">details</summary>${rows}${note}</details></td></tr>`;
  }).join("") + "</table>";
}

async function loadHardware() {
  loadHealth();
  const d = await api("/api/hardware");
  if (d) _hwData = d;
  if (!d) {
    document.getElementById("hw-ambe-meta").textContent  = "error";
    document.getElementById("hw-audio-meta").textContent = "error";
    document.getElementById("hw-pwr-meta").textContent   = "error";
    return;
  }
  renderAmbeSection(d.ambe  || []);
  renderAudioSection(d.audio || []);
  renderPowerSection(d.power || null);
  renderVideoSection(d.video || null);
  loadHardwareDiag();
}

async function loadHardwareDiag() {
  ["hw-usb-body", "hw-afs-body", "hw-alsa-body"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = '<div class="stub-panel" style="min-height:48px">Loading…</div>';
  });
  const d = await api("/api/hardware/diag");
  if (!d) {
    ["hw-usb-body","hw-afs-body","hw-alsa-body"].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = '<div class="stub-panel">Server error</div>';
    });
    return;
  }
  _hwDiagData = d;
  renderUsbSection(d.lsusb         || {});
  renderAslFindSoundSection(d.asl_find_sound || {});
  renderAlsaSection(d.alsa         || {});
}

function _usbLineBadge(line) {
  
  const m = line.match(/ID\s+([0-9a-f]{4}):([0-9a-f]{4})/i);
  if (!m) return "";
  const key = `${m[1].toLowerCase()}:${m[2].toLowerCase()}`;
  const vid  = m[1].toLowerCase();
  if (_HW_AMBE_PAIRS[key]) {
    return `<span class="hw-usb-badge ambe">${_esc(_HW_AMBE_PAIRS[key])}</span>`;
  }
  if (_HW_FTDI_VIDS[vid]) {
    return `<span class="hw-usb-badge ftdi">possible AMBE</span>`;
  }
  return "";
}

function renderUsbSection(data) {
  const body = document.getElementById("hw-usb-body");
  const meta = document.getElementById("hw-usb-meta");
  if (!body) return;

  if (!data.available) {
    if (meta) meta.textContent = "unavailable";
    body.innerHTML =
      `<div class="hw-diag-note">${_esc(data.error || "lsusb not available")}</div>`;
    return;
  }

  const flat  = data.flat  || [];
  const tree  = data.tree  || "";
  if (meta) meta.textContent = flat.length + " device" + (flat.length !== 1 ? "s" : "");

  _hwUsbView = _hwUsbView || "flat";
  _renderUsbView(flat, tree);
}

function _renderUsbView(flat, tree) {
  const body = document.getElementById("hw-usb-body");
  if (!body) return;

  const btnFlat = document.getElementById("hw-usb-btn-flat");
  const btnTree = document.getElementById("hw-usb-btn-tree");
  if (btnFlat) btnFlat.classList.toggle("active", _hwUsbView === "flat");
  if (btnTree) btnTree.classList.toggle("active", _hwUsbView === "tree");

  body.innerHTML = "";

  if (_hwUsbView === "flat") {
    if (!flat.length) {
      body.innerHTML = '<div class="hw-diag-note">No USB devices found.</div>';
      return;
    }
    const pre = document.createElement("pre");
    pre.className = "hw-diag-pre";
    flat.forEach(line => {
      const span = document.createElement("span");
      span.style.display = "block";
      span.innerHTML = _esc(line) + _usbLineBadge(line);
      pre.appendChild(span);
    });
    body.appendChild(pre);
  } else {
    const pre = document.createElement("pre");
    pre.className = "hw-diag-pre";
    pre.textContent = tree || "(no tree output)";
    body.appendChild(pre);
  }
}

function hwUsbToggle(view) {
  _hwUsbView = view;
  if (!_hwDiagData) return;
  const data = _hwDiagData.lsusb || {};
  _renderUsbView(data.flat || [], data.tree || "");
}

function renderAslFindSoundSection(data) {
  const body = document.getElementById("hw-afs-body");
  const meta = document.getElementById("hw-afs-meta");
  if (!body) return;

  if (!data.installed) {
    if (meta) meta.textContent = "not installed";
    body.innerHTML =
      `<div class="hw-diag-note">${_esc(data.error ||
        "asl-find-sound not found — install asl3 or asl-apt-utils")}</div>`;
    return;
  }

  if (meta) meta.textContent = "installed";

  body.innerHTML = "";
  const note = document.createElement("div");
  note.className   = "hw-diag-note";
  note.textContent = "Run this tool when chan_simpleusb reports no audio device. " +
                     "It identifies C-Media USB sound cards compatible with chan_simpleusb.";
  body.appendChild(note);

  const pre = document.createElement("pre");
  pre.className   = "hw-diag-pre";
  pre.textContent = data.output || "(no output)";
  body.appendChild(pre);
}

function renderAlsaSection(data) {
  const body = document.getElementById("hw-alsa-body");
  const meta = document.getElementById("hw-alsa-meta");
  if (!body) return;

  if (!data.available) {
    if (meta) meta.textContent = "unavailable";
    body.innerHTML =
      `<div class="hw-diag-note">${_esc(data.error || "aplay not available")}</div>`;
    return;
  }

  const cardLines = (data.playback || "").split("\n")
    .filter(l => l.match(/^card\s+\d+/i)).length;
  if (meta) meta.textContent = cardLines + " card" + (cardLines !== 1 ? "s" : "");

  _hwAlsaView = _hwAlsaView || "playback";
  _renderAlsaView(data);
}

function _renderAlsaView(data) {
  const body = document.getElementById("hw-alsa-body");
  if (!body) return;

  const btnPb  = document.getElementById("hw-alsa-btn-pb");
  const btnCap = document.getElementById("hw-alsa-btn-cap");
  if (btnPb)  btnPb.classList.toggle("active",  _hwAlsaView === "playback");
  if (btnCap) btnCap.classList.toggle("active", _hwAlsaView === "capture");

  body.innerHTML = "";

  const note = document.createElement("div");
  note.className   = "hw-diag-note";
  note.textContent = _hwAlsaView === "playback"
    ? "Playback devices — set devusb = hw:CARD,0 in chan_simpleusb.conf (e.g. devusb = hw:1,0)"
    : "Capture devices — microphone/line-in paths for the same card index";
  body.appendChild(note);

  const pre = document.createElement("pre");
  pre.className = "hw-diag-pre";
  const text = _hwAlsaView === "playback"
    ? (data.playback || "(no playback devices)")
    : (data.capture  || "(no capture devices)");
  pre.textContent = text;
  body.appendChild(pre);
}

function hwAlsaToggle(view) {
  _hwAlsaView = view;
  if (!_hwDiagData) return;
  _renderAlsaView(_hwDiagData.alsa || {});
}

function renderPowerSection(pwr) {
  const body = document.getElementById("hw-pwr-body");
  const meta = document.getElementById("hw-pwr-meta");
  if (!body) return;

  if (!pwr) {
    if (meta) meta.textContent = "—";
    body.innerHTML =
      `<div class="stub-panel" style="min-height:60px">No data</div>`;
    return;
  }

  const ts   = pwr.throttle  || {};
  const temp = pwr.cpu_temp;
  const cv   = pwr.core_volts;

  if (meta) {
    if (!ts.available) {
      meta.textContent = "vcgencmd unavailable";
    } else {
      meta.textContent = ts.raw || "0x0";
    }
  }

  const cls = (status) => ({
    ok: "ok", warn: "warn", uv: "hot", throttled: "hot"
  }[status] || "");

  const pwrLabel = {
    ok:        "OK",
    warn:      "WARN — past events (see flags below)",
    uv:        "⚡ UNDER-VOLTAGE NOW",
    throttled: "⚡ THROTTLED NOW",
  }[ts.pwr_status] || "—";

  let cvHtml = "";
  if (cv != null) {
    cvHtml = `<tr>
      <td class="hw-pwr-lbl">Core Voltage</td>
      <td class="hw-pwr-val">
        ${cv.toFixed(4)}V
        <span class="hw-pwr-note">Internal SoC rail — not the 5V supply voltage</span>
      </td>
    </tr>`;
  }

  let tempHtml = "";
  if (temp != null) {
    const tc = temp > 75 ? "hot" : temp > 60 ? "warn" : "ok";
    const tn = temp > 80 ? "Hard throttle active above 80°C"
             : temp > 75 ? "Approaching throttle threshold"
             : temp > 60 ? "Soft temperature limit may engage"
             : "Normal operating range";
    tempHtml = `<tr>
      <td class="hw-pwr-lbl">SoC Temp</td>
      <td class="hw-pwr-val ${tc}">
        ${temp}°C
        <span class="hw-pwr-note">${_esc(tn)}</span>
      </td>
    </tr>`;
  }

  let html = `<table class="hw-pwr-tbl">`;

  if (ts.available) {
    html += `<tr>
      <td class="hw-pwr-lbl">Power Health</td>
      <td class="hw-pwr-val ${cls(ts.pwr_status)}">${_esc(pwrLabel)}</td>
    </tr>
    <tr>
      <td class="hw-pwr-lbl">Bitmask</td>
      <td class="hw-pwr-val">
        ${_esc(ts.raw)}
        <span class="hw-pwr-note">vcgencmd get_throttled — threshold ~4.63V</span>
      </td>
    </tr>`;
  } else {
    html += `<tr>
      <td class="hw-pwr-lbl">Power Health</td>
      <td class="hw-pwr-val dim">vcgencmd unavailable
        <span class="hw-pwr-note">install libraspberrypi-bin or check PATH</span>
      </td>
    </tr>`;
  }

  html += cvHtml + tempHtml + `</table>`;

  if (ts.available) {
    const flags = [
      { label: "UV now",       set: ts.uv_now,        kind: "now"  },
      { label: "Freq cap now", set: ts.freq_cap_now,  kind: "now"  },
      { label: "Throttled now",set: ts.throttled_now, kind: "now"  },
      { label: "Temp now",     set: ts.temp_now,      kind: "now"  },
      { label: "UV since boot",       set: ts.uv_ever,        kind: "ever" },
      { label: "Freq cap since boot", set: ts.freq_cap_ever,  kind: "ever" },
      { label: "Throttled since boot",set: ts.throttled_ever, kind: "ever" },
      { label: "Temp since boot",     set: ts.temp_ever,      kind: "ever" },
    ];
    html += `<div class="hw-diag-note">
      "now" = actively occurring at this moment; "since boot" = happened at
      least once since the last reboot, may not still be happening.
    </div>`;
    html += `<div class="hw-pwr-flags">`;
    flags.forEach(f => {
      const cls = f.set ? (f.kind === "now" ? "set-now" : "set-ever") : "clear";
      html += `<span class="hw-pwr-flag ${cls}">${_esc(f.label)}</span>`;
    });
    html += `</div>`;
  }

  body.innerHTML = html;
}

function renderVideoSection(v) {
  const body = document.getElementById("hw-vid-body");
  const meta = document.getElementById("hw-vid-meta");
  if (!body) return;
  if (!v || !v.available) {
    if (meta) meta.textContent = "not available";
    body.innerHTML = `<div class="stub-panel" style="min-height:48px">${_esc((v && v.message) || "No data")}</div>`;
    return;
  }
  const lv = v.live || {};
  const pend = v.video_pending || v.gpumem_pending;
  if (meta) meta.textContent = pend ? "reboot required" : "config.txt in effect";
  const pb = (on) => on ? `<span class="hw-vid-pend">REBOOT REQUIRED</span>` : "";
  const hdmi = (lv.hdmi || []).map(c => `${c.name}: ${c.status}`).join(", ");
  const noVid = v.video_lines === 0;
  let html = `<table class="hw-pwr-tbl">
    <tr><td class="hw-pwr-lbl">Video driver</td>
      <td class="hw-pwr-val ${lv.vc4_loaded ? "" : "ok"}">${lv.vc4_loaded ? "vc4 loaded" : "vc4 not loaded"}
        <span class="hw-pwr-note">${_esc(hdmi ? "HDMI " + hdmi : "no HDMI outputs listed")}</span>${pb(v.video_pending)}</td></tr>
    <tr><td class="hw-pwr-lbl">GPU memory</td>
      <td class="hw-pwr-val">${lv.gpu_mb != null ? lv.gpu_mb + " MB" : "—"}
        <span class="hw-pwr-note">vcgencmd get_mem gpu</span>${pb(v.gpumem_pending)}</td></tr>
    <tr><td class="hw-pwr-lbl">CMA reserved</td>
      <td class="hw-pwr-val">${lv.cma_mb != null ? lv.cma_mb + " MB" : "—"}
        <span class="hw-pwr-note">memory kept back for the video driver (CmaTotal)</span></td></tr>
  </table>`;
  html += `<label class="hw-vid-opt${noVid && !v.video_off ? " disabled" : ""}">
      <input type="checkbox" id="hw-vid-chk-video" ${v.video_off ? "checked" : ""}
        ${noVid && !v.video_off ? "disabled" : ""} onchange="hwBootOpt('video', this)">
      <span>Disable HDMI and video driver (headless)
        <span class="hw-pwr-note">${noVid ? "no dtoverlay=vc4-kms-v3d line in config.txt" :
          "comments out dtoverlay=vc4-kms-v3d; frees the driver and its memory"}</span></span></label>`;
  html += `<label class="hw-vid-opt">
      <input type="checkbox" id="hw-vid-chk-gpumem" ${v.gpumem_low ? "checked" : ""}
        onchange="hwBootOpt('gpumem', this)">
      <span>Lower GPU memory to ${v.gpumem_low_mb} MB
        <span class="hw-pwr-note">adds gpu_mem=${v.gpumem_low_mb}; camera and video decoding stop working</span></span></label>`;
  if ((lv.hdmi_sound || []).length) {
    html += `<div class="hw-diag-note">HDMI sound card(s) (${_esc(lv.hdmi_sound.join(", "))}) go away with the video
      driver, so other sound cards can get a new number.</div>`;
  }
  if ((v.hw_refs || []).length) {
    html += `<div class="hw-diag-note">These settings name a sound card by number and may need changing:</div>
      <div class="hw-vid-refs">${_esc(v.hw_refs.join("\n"))}</div>`;
  }
  html += `<div class="hw-diag-note">With the video driver off you cannot plug in a monitor to get back in. If the network
    fails, edit config.txt on the SD card from another computer (remove the #ASL-DVS-VIDEO-OFF# prefix).
    Copy from before the last change: ${_esc(v.backup)}</div>`;
  if (pend) {
    html += `<div class="hw-vid-actions"><button class="btn btn-sm" onclick="postAction('/api/reboot','reboot',this,'⟳ Reboot now to apply the config.txt change?')">⟳ Reboot now</button></div>`;
  }
  body.innerHTML = html;
}

async function hwBootOpt(opt, el) {
  const on = el.checked;
  let msg;
  if (opt === "video") {
    msg = on ? "Disable HDMI and the video driver in config.txt? Takes effect after a reboot. A monitor will no longer show anything."
             : "Turn the HDMI video driver back on in config.txt? Takes effect after a reboot.";
    const refs = document.querySelector(".hw-vid-refs");
    if (on && refs) msg += " Some settings name a sound card by number (listed on the card). Check them after the reboot.";
  } else {
    msg = on ? "Lower GPU memory to 16 MB in config.txt? Takes effect after a reboot."
             : "Put GPU memory back to the default in config.txt? Takes effect after a reboot.";
  }
  const ok = await confirm(msg);
  if (!ok) { el.checked = !on; return; }
  el.disabled = true;
  const d = await api("/api/hardware", "POST", {action: "boot_opt", opt, on});
  el.disabled = false;
  if (!d) { el.checked = !on; toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "OK" : "Failed"), d.ok ? "ok" : "err");
  if (d.video) renderVideoSection(d.video);
  else if (!d.ok) el.checked = !on;
}

function renderAmbeSection(devices) {
  const body = document.getElementById("hw-ambe-body");
  const meta = document.getElementById("hw-ambe-meta");
  if (!body) return;

  if (!devices.length) {
    body.innerHTML = '<div class="stub-panel" style="min-height:50px">No AMBE devices detected</div>';
    meta.textContent = "none detected";
    return;
  }

  const primary = devices.find(d => d.ambe_known) || devices[0];
  const nodeStr = (primary.dev_nodes || []).join(" · ") || "no node";
  meta.textContent = primary.label + " · " + nodeStr;

  let html = "";

  if (devices.length > 1) {
    html += `<div class="hw-multi-warn">
      ⚠ ${devices.length} AMBE devices detected — showing first recognized
    </div>`;
  }

  const dotCls = primary.ambe_known ? "dot-on" : "dot-warn";
  const dotTitle = primary.ambe_known
    ? "Recognized AMBE VID:PID — confirmed dongle"
    : "Not a recognized AMBE VID:PID — treated as generic serial";
  const badge  = primary.ambe_known
    ? `<span class="hw-badge hw-badge-ambe" title="Confirmed AMBE dongle (known VID:PID)">AMBE</span>`
    : `<span class="hw-badge hw-badge-serial" title="Generic serial device — VID:PID not in the known AMBE list">SERIAL</span>`;
  const sym = primary.udev_symlink
    ? `<span style="color:var(--teal)"> → ${primary.udev_symlink}</span>` : "";
  const srcTag = primary.source === "watchdog"
    ? `<span class="hw-badge hw-badge-watchdog" title="Detected by DMRWatchMon's background scan, not this page's own live probe">watchdog</span>` : "";

  html += `<div class="hw-dev-row-hdr">
    <span class="dot ${dotCls}" title="${_esc(dotTitle)}"></span>
    <span style="font-family:var(--sans);font-size:var(--fs-md);
      color:var(--text-bright);font-weight:bold">${_esc(primary.label)}</span>
    ${badge}
    <span style="font-family:var(--sans);font-size:var(--fs-xs);
      color:#fff;margin-left:.2rem">${_esc(nodeStr)}${sym}</span>
    ${srcTag}
    <span style="margin-left:auto">
      <button class="hw-gear-btn" id="hw-gear-btn"
        onclick="hwToggleActionZone(this)" title="Configure">⚙ Configure</button>
    </span>
  </div>`;

  const vid_pid = primary.vid && primary.pid
    ? `<span class="hw-dev-val dim">${_esc(primary.vid)}:${_esc(primary.pid)}</span>` : "";
  const mfr = primary.manufacturer
    ? `<div class="hw-dev-row">
        <span class="hw-dev-label">Mfr</span>
        <span class="hw-dev-val dim">${_esc(primary.manufacturer)}</span>
      </div>` : "";
  html += `<div class="hw-dev-info">
    <div class="hw-dev-row">
      <span class="hw-dev-label">Chip</span>
      <span class="hw-dev-val" id="hw-chip-name">${_esc(primary.product || primary.label)}</span>
    </div>
    <div class="hw-dev-row">
      <span class="hw-dev-label">VID:PID</span>
      ${vid_pid}
    </div>
    ${mfr}
    <div class="hw-dev-row">
      <span class="hw-dev-label">Node</span>
      <span class="hw-dev-val">${_esc(nodeStr)}</span>
      ${primary.udev_symlink
        ? `<span style="font-family:var(--sans);font-size:var(--fs-xs);color:#fff;margin-left:.4rem">→</span>
           <span class="hw-dev-val sym">${_esc(primary.udev_symlink)}</span>` : ""}
    </div>
  </div>`;

  html += `<div class="hw-section-lbl">AMBE Health</div>`;

  const layerDefs = [
    ["l1", "Kernel recognized"],
    ["l2", "Serial port accessible"],
    ["l3", "Process holding port"],
  ];
  for (const [key, label] of layerDefs) {
    const l = (primary.layers || {})[key] || {ok: null, detail: ""};
    html += _hwCheckRow(label, l.ok, l.detail, key);
  }

  const cached = _hwPingCache[primary.dev_nodes && primary.dev_nodes[0]];
  const l4 = cached || (primary.layers || {}).l4 || {ok: null, detail: "press Ping to test"};
  html += _hwCheckRow("Chip responding", l4.ok, l4.detail, "l4");
  html += _hwCheckLegend();
  if (l4.ok === null) {
    html += `<div class="hw-diag-note">
      ◌ here just means this session hasn't run the ping test yet — not a
      failure. It's manual-only because it needs exclusive access to the
      serial port: if AMBE is working normally, DVSwitch is already holding
      that port, so a ping right now would likely fail because the port is
      busy doing its job, not because the chip is bad. To get a real
      pass/fail, stop DVSwitch first, then Ping, then restart it.
    </div>`;
  }

  const symlinkVal = primary.udev_rule ? primary.udev_rule.symlink
    : (primary.product || primary.label || "").replace(/\s+/g, "");
  const hasRule = !!(primary.udev_rule);
  const devNode = (primary.dev_nodes || [])[0] || "";

  html += `<div class="hw-action-zone" id="hw-action-zone">
    
    <div class="hw-action-sub">
      <div class="hw-action-sub-title">Persistent Name (udev symlink)</div>
      <div class="hw-action-row">
        <input class="hw-action-inp" id="hw-symlink-inp"
          value="${_esc(symlinkVal)}" placeholder="e.g. ThumbDV" maxlength="32">
        <button class="btn btn-teal btn-sm"
          onclick="hwApplyUdev('${_esc(primary.vid)}','${_esc(primary.pid)}')">Apply</button>
        <button class="btn btn-muted btn-sm hw-remove-btn${hasRule ? " visible" : ""}"
          id="hw-remove-btn"
          onclick="hwDelUdev('${_esc(primary.vid)}','${_esc(primary.pid)}')">Remove</button>
      </div>
      <div class="hw-symlink-hint">
        Creates <span>/dev/${_esc(symlinkVal)}</span> — point DVSwitch config here
      </div>
    </div>
    
    <div class="hw-action-sub">
      <div class="hw-action-sub-title">Baud Rate</div>
      <div class="hw-action-row">
        <select class="hw-action-sel" id="hw-baud-sel">
          <option value="460800">460800 — standard</option>
          <option value="230400">230400 — early units</option>
        </select>
        <button class="btn btn-blue btn-sm"
          onclick="hwSetBaud('${_esc(devNode)}')">Set</button>
      </div>
      <div class="hw-action-note">
        stty is session-only — lost on reconnect and reboot.<br>
        Point DVSwitch config to /dev/&lt;symlink&gt; for persistence.
      </div>
    </div>
    
    <div class="hw-action-sub">
      <div class="hw-action-sub-title">Chip Ping — DVSI PROD_ID Query</div>
      <div class="hw-action-row">
        <button class="btn btn-purple btn-sm" id="hw-ping-btn"
          onclick="hwPing('${_esc(devNode)}')">⚡ Ping Chip</button>
        <span class="hw-ping-result" id="hw-ping-result"></span>
      </div>
      <div class="hw-action-note">
        Ping will fail if DVSwitch is holding the port — stop it first.
      </div>
    </div>
  </div>`;

  html += `<div class="hw-card-footer">
    <button class="btn btn-muted btn-sm" onclick="loadHardware()">↻ Re-check</button>
    <button class="hw-reset-chip-btn" id="hw-reset-btn"
      onclick="hwResetChip('${_esc(devNode)}')">⟳ Reset Chip</button>
    <span class="hw-reset-status" id="hw-reset-status"></span>
    <span class="hw-source-tag" style="margin-left:auto">
      source: ${_esc(primary.source || "live")}</span>
  </div>`;

  body.innerHTML = html;

  if (cached) _hwApplyPingResult(cached, false);
}

function _hwCheckRow(label, ok, detail, id) {
  const icon  = ok === true  ? ["ok",   "✓"]
              : ok === false ? ["fail", "✗"]
              : ok === "warn"? ["warn", "⚠"]
              :                ["pend", "◌"];
  const detCls = ok === true ? "ok" : ok === false ? "fail" : "";
  return `<div class="hw-check-row" id="hw-row-${id}">
    <span class="hw-check-icon ${icon[0]}" id="hw-icon-${id}">${icon[1]}</span>
    <span class="hw-check-label">${_esc(label)}</span>
    <span class="hw-check-detail ${detCls}" id="hw-det-${id}">${_esc(detail)}</span>
  </div>`;
}

function _hwCheckLegend() {
  return `<div class="hw-diag-note">
    ✓ pass &nbsp;·&nbsp; ✗ fail &nbsp;·&nbsp; ⚠ warning &nbsp;·&nbsp; ◌ not yet tested
  </div>`;
}

function renderAudioSection(devices) {
  const body = document.getElementById("hw-audio-body");
  const meta = document.getElementById("hw-audio-meta");
  if (!body) return;

  const usb = devices.filter(d => d.is_usb);

  if (!usb.length) {
    body.innerHTML = '<div class="stub-panel" style="min-height:50px">No USB audio devices detected</div>';
    meta.textContent = "none detected";
    return;
  }

  const primary = usb[0];
  meta.textContent = (primary.card_name || "USB Audio") +
                     " · hw:" + primary.card_index;

  let html = "";

  const dotCls = (primary.checks.c1.ok && primary.checks.c2.ok)
    ? "dot-on" : "dot-warn";
  const dotTitle = (primary.checks.c1.ok && primary.checks.c2.ok)
    ? "Recognized by the kernel and not held by another process"
    : "Not fully ready — see Audio Health rows below for which check is failing";
  html += `<div class="hw-dev-row-hdr">
    <span class="dot ${dotCls}" title="${_esc(dotTitle)}"></span>
    <span style="font-family:var(--sans);font-size:var(--fs-md);
      color:var(--text-bright);font-weight:bold">${_esc(primary.card_name)}</span>
    <span class="hw-badge hw-badge-audio">USB AUDIO</span>
    <span style="font-family:var(--sans);font-size:var(--fs-xs);
      color:#fff;margin-left:.4rem">hw:${primary.card_index}</span>
  </div>`;

  const chipset = primary.vid && primary.pid
    ? `<div class="hw-dev-row">
        <span class="hw-dev-label">VID:PID</span>
        <span class="hw-dev-val dim">${_esc(primary.vid)}:${_esc(primary.pid)}</span>
      </div>` : "";
  const ttyRow = (primary.tty_nodes && primary.tty_nodes.length)
    ? `<div class="hw-dev-row">
        <span class="hw-dev-label">Node</span>
        <span class="hw-dev-val">${_esc(primary.tty_nodes.join(" · "))}</span>
      </div>` : "";
  html += `<div class="hw-dev-info">
    <div class="hw-dev-row">
      <span class="hw-dev-label">Card</span>
      <span class="hw-dev-val">${_esc(primary.card_name)}</span>
    </div>
    <div class="hw-dev-row">
      <span class="hw-dev-label">ALSA</span>
      <span class="hw-dev-val">hw:${primary.card_index},0</span>
    </div>
    ${chipset}
    ${ttyRow}
  </div>`;

  html += `<div class="hw-section-lbl">Audio Health</div>`;
  html += _hwCheckRow("Kernel recognized",    primary.checks.c1.ok, primary.checks.c1.detail, "au-c1");
  html += _hwCheckRow("Device free",          primary.checks.c2.ok, primary.checks.c2.detail, "au-c2");
  html += _hwCheckLegend();

  html += `<div class="hw-section-lbl">Compatibility</div>
  <div class="hw-diag-note">
    DVSwitch needs 8kHz mono capture+playback (AMBE bridging); ASL Node needs
    CM1xx-style GPIO (PTT/COS/CTCSS) for a full repeater-style node. A generic
    USB headset can pass one and not the other — that's normal, not a fault.
  </div>
  <div class="hw-compat-section">`;

  if (primary.dvswitch_ok) {
    html += `<div class="hw-compat-row">
      <span class="hw-compat-label">DVSwitch</span>
      <span class="hw-compat-ok">YES</span>
      <span class="hw-compat-reason">8kHz · S16_LE · mono · capture+playback</span>
    </div>`;
  } else {
    html += `<div class="hw-compat-row">
      <span class="hw-compat-label">DVSwitch</span>
      <span class="hw-compat-fail">NO</span>
      <span class="hw-compat-reason">${_esc(primary.dvswitch_fail_reason || "check failed")}</span>
    </div>`;
  }

  if (primary.asl_ok) {
    html += `<div class="hw-compat-row">
      <span class="hw-compat-label">ASL Node</span>
      <span class="hw-compat-ok">YES</span>
      <span class="hw-compat-reason">CM1xx GPIO capable (PTT · COS · CTCSS)</span>
    </div>`;
  } else {
    const aslCls = primary.dvswitch_ok ? "hw-compat-warn" : "hw-compat-fail";
    html += `<div class="hw-compat-row">
      <span class="hw-compat-label">ASL Node</span>
      <span class="${aslCls}">NO</span>
      <span class="hw-compat-reason">${_esc(primary.asl_fail_reason || "")}</span>
    </div>`;
    if (primary.dvswitch_ok) {
      html += `<div class="hw-compat-note">
        DVSwitch YES + ASL NO is expected for generic headsets — not a detection error
      </div>`;
    }
  }

  html += `</div>`;

  html += `<div class="hw-card-footer">
    <button class="btn btn-muted btn-sm" onclick="loadHardware()">↻ Re-check</button>
  </div>`;

  body.innerHTML = html;
}

function hwToggleActionZone(btn) {
  const zone = document.getElementById("hw-action-zone");
  if (!zone) return;
  const open = zone.classList.toggle("open");
  btn.classList.toggle("open", open);
  btn.textContent = open ? "✕ Close" : "⚙ Configure";
}

async function hwApplyUdev(vid, pid) {
  const inp = document.getElementById("hw-symlink-inp");
  if (!inp) return;
  const sym = inp.value.trim();
  if (!sym || !/^[A-Za-z0-9_\-]{1,32}$/.test(sym)) {
    toast("Invalid name — A-Z 0-9 _ - only, max 32 chars", "err"); return;
  }
  const d = await api("/api/hardware", "POST",
    {action:"set_udev", vid, pid, symlink: sym});
  if (!d) { toast("Request failed", "err"); return; }
  toast(d.message || (d.ok ? "Rule saved" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) {
    const hint = document.querySelector(".hw-symlink-hint span");
    if (hint) hint.textContent = "/dev/" + sym;
    const rm = document.getElementById("hw-remove-btn");
    if (rm) rm.classList.add("visible");
    loadHardware();
  }
}

async function hwDelUdev(vid, pid) {
  const d = await api("/api/hardware", "POST",
    {action:"del_udev", vid, pid});
  if (!d) { toast("Request failed", "err"); return; }
  toast(d.message || (d.ok ? "Rule removed" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) loadHardware();
}

async function hwSetBaud(dev) {
  const sel  = document.getElementById("hw-baud-sel");
  const baud = sel ? parseInt(sel.value, 10) : 460800;
  const d = await api("/api/hardware", "POST",
    {action:"set_tty", dev, baud});
  if (!d) { toast("Request failed", "err"); return; }
  toast(d.message || (d.ok ? "Baud set" : "Failed"), d.ok ? "ok" : "err");
}

async function hwPing(dev) {
  const btn    = document.getElementById("hw-ping-btn");
  const result = document.getElementById("hw-ping-result");
  if (!dev) { toast("No device node", "err"); return; }
  if (btn) { btn.disabled = true; btn.textContent = "⚡ Pinging…"; }
  if (result) { result.className = "hw-ping-result"; result.style.display = "none"; }

  const d = await api("/api/hardware", "POST", {action:"ping", dev});

  if (btn)  { btn.disabled = false; btn.textContent = "⚡ Ping Chip"; }
  if (!d)   { toast("Ping request failed", "err"); return; }

  _hwPingCache[dev] = {
    ok:     d.ok,
    detail: d.ok
      ? `${d.product_id} · ${d.baud_used} baud`
      : (d.error || "no response"),
  };
  _hwApplyPingResult(_hwPingCache[dev], true);
  toast(d.ok
    ? `Chip responding — ${d.product_id}`
    : (d.error || "No response"), d.ok ? "ok" : "err");
}

async function hwResetChip(dev) {
  const btn    = document.getElementById("hw-reset-btn");
  const status = document.getElementById("hw-reset-status");
  if (!dev) { toast("No device node", "err"); return; }

  if (btn) {
    btn.disabled      = true;
    btn.textContent   = "⟳ Working…";
    btn.style.opacity = ".55";
  }
  if (status) {
    status.className     = "hw-reset-status warn";
    status.textContent   = "stopping services…";
  }

  const d = await api("/api/hardware", "POST", {action: "reset_ambe", dev});

  if (btn) {
    btn.disabled      = false;
    btn.textContent   = "⟳ Reset Chip";
    btn.style.opacity = "";
  }

  if (!d) {
    toast("Reset request failed", "err");
    if (status) {
      status.textContent = "request failed";
      status.className   = "hw-reset-status fail";
    }
    return;
  }

  if (status) {
    if (d.ok) {
      const reEnum  = d.re_detected ? "re-enumerated ✓" : "sent — allow a moment";
      const svcPart = d.svc_summary ? ` · ${d.svc_summary}` : "";
      status.textContent = reEnum + svcPart;
      status.className   = "hw-reset-status " + (d.re_detected ? "ok" : "warn");
    } else {
      status.textContent = d.message || "reset failed";
      status.className   = "hw-reset-status fail";
    }
  }

  if (d.ok) {
    const failedRestarts = (d.restart_results || []).filter(r => !r.ok);
    if (failedRestarts.length) {
      const names = failedRestarts.map(r => r.unit).join(", ");
      toast(`Chip reset · failed to restart: ${names}`, "info");
    } else {
      toast(d.re_detected
        ? `Chip reset — services restarted · ${d.svc_summary || ""}`
        : `Reset sent · ${d.svc_summary || ""}`, "ok");
    }
    setTimeout(() => loadHardware(), 2500);
  } else {
    toast(d.message || "Reset failed", "err");
  }
}

function _hwApplyPingResult(cached, showInline) {
  const icon = document.getElementById("hw-icon-l4");
  const det  = document.getElementById("hw-det-l4");
  if (icon && det) {
    if (cached.ok) {
      icon.className   = "hw-check-icon ok";
      icon.textContent = "✓";
      det.className    = "hw-check-detail ok";
    } else {
      icon.className   = "hw-check-icon fail";
      icon.textContent = "✗";
      det.className    = "hw-check-detail fail";
    }
    det.textContent = cached.detail;
  }
  if (showInline) {
    const result = document.getElementById("hw-ping-result");
    if (result) {
      result.textContent = cached.detail;
      result.className   = "hw-ping-result " + (cached.ok ? "ok" : "fail");
    }
  }
  if (cached.ok) {
    const chipEl = document.getElementById("hw-chip-name");
    if (chipEl) {
      const prod = cached.detail.split(" · ")[0];
      if (prod) chipEl.textContent = prod;
    }
  }
}

// ========================================================================
// TAB: DVSM
// ========================================================================
// ---- general ----
async function loadDvsm() {
  
  ["direct", "iaxrpt", "node", "usrp"].forEach(k =>
    _dvsmSetBadge("dvsm-badge-" + k, "info", "...")
  );

  const d = await api("/api/dvsm");
  if (!d) {
    ["direct", "iaxrpt", "node", "usrp"].forEach(k =>
      _dvsmSetBadge("dvsm-badge-" + k, "fail", "ERR")
    );
    toast("DVSM: failed to load config", "warn");
    return;
  }

  const ipEl = document.getElementById("dvsm-node-ip");
  if (ipEl) ipEl.textContent = d.node_ip || "—";

  const a = d.accounts || {};
  _dvsmRenderAccount("dvsm-body-direct", "dvsm-badge-direct", a.direct_iax2 || {}, "direct");
  _dvsmRenderAccount("dvsm-body-iaxrpt", "dvsm-badge-iaxrpt", a.iaxrpt      || {}, "iaxrpt");
  _dvsmRenderAccount("dvsm-body-node",   "dvsm-badge-node",   a.node_mode   || {}, "node");
  _dvsmRenderAccount("dvsm-body-usrp",   "dvsm-badge-usrp",   a.usrp        || {}, "usrp");

  _dvsmRenderCompat("dvsm-body-compat", d.compat || []);
}

// ========================================================================
// TAB: STFU
// ========================================================================
// ---- general ----
function _stfuCopySecret(btn, fid) {
  dvsmCopy(btn, _stfuSecrets.get(fid) || "");
}

function _stfuReveal(eyeBtn, fid) {
  _toggleReveal(eyeBtn, fid, _stfuRevealed, _stfuSecrets);
}

function _stfuRenderInstall(bodyId, badgeId, inst) {
  _renderInstallTable(bodyId, badgeId, inst, {
    binDefault: "/opt/STFU/STFU",
    binLabel:   "Binary present and executable",
    binFix:     "Download STFU.armhf from DVSwitch GitHub → copy to /opt/STFU/STFU → chmod +x",
    unit:       "stfu",
    unitFix:    "Copy stfu.service to /lib/systemd/system/ → systemctl daemon-reload",
  });
}

function _stfuRenderConfig(bodyId, badgeId, pathId, cfgWrapper) {
  
  const fields = cfgWrapper.fields || [];
  
  let hasBmAddr = false, hasBmPw = false, hasDmrId = false;
  fields.forEach(f => {
    if (!f.label) return;
    if (f.label === "BM Server"   && f.value && f.value !== "—") hasBmAddr = true;
    if (f.label === "BM Password" && f.secret)                    hasBmPw   = true;
    if (f.label === "DMR ID"      && f.value && f.value !== "—") hasDmrId  = true;
  });
  const status = (hasBmAddr && hasBmPw && hasDmrId) ? "pass"
               : (hasBmAddr || hasDmrId)             ? "warn" : "fail";
  _dvsmSetBadge(badgeId, status);

  const pathEl = document.getElementById(pathId);
  if (pathEl && cfgWrapper.dvs_path) {
    pathEl.textContent = cfgWrapper.dvs_path + " [STFU]";
  }

  const body = document.getElementById(bodyId);
  if (!body) return;

  if (!cfgWrapper.raw_ok) {
    body.innerHTML =
      `<div class="dvsm-note err">&#x26A0; ${_esc(cfgWrapper.error || "DVSwitch.ini not readable")}</div>`;
    return;
  }
  if (!cfgWrapper.stfu_present) {
    body.innerHTML =
      `<div class="dvsm-note warn">&#x26A0; No [STFU] section found in DVSwitch.ini —` +
      ` paste the sample stanza below into the file and restart.</div>`;
    return;
  }

  let html   = "";
  let inTbl  = false;
  let cardKey = 0;

  fields.forEach(f => {
    
    if (f.group) {
      if (inTbl) { html += `</table>`; inTbl = false; }
      html += `<span class="dvsm-sec-lbl">${_esc(f.group)}</span>`;
      return;
    }

    if (!inTbl) { html += `<table class="dvsm-fields">`; inTbl = true; }

    const fid = `stfu-fv-${cardKey++}`;
    let valTd, actTd;

    if (f.masked) {
      _stfuRevealed.delete(fid);
      if (f.secret) {
        _stfuSecrets.set(fid, f.secret);
        valTd = `<td class="dvsm-val-cell">` +
                `<span id="${fid}" class="dvsm-val masked">` +
                `&#x25CF;&#x25CF;&#x25CF;&#x25CF;&#x25CF;&#x25CF;&#x25CF;&#x25CF;</span></td>`;
        actTd = `<td class="dvsm-actions">` +
                `<button class="dvsm-eye" title="Reveal"` +
                ` onclick="_stfuReveal(this,'${fid}')">&#x1F441;</button>` +
                `<button class="dvsm-copy"` +
                ` onclick="_stfuCopySecret(this,'${fid}')">&#x2398;</button>` +
                `</td>`;
      } else {
        valTd = `<td class="dvsm-val-cell">` +
                `<span class="dvsm-val placeholder">${_esc(f.note || "not set")}</span></td>`;
        actTd = `<td class="dvsm-actions"></td>`;
      }
    } else {
      const raw     = (f.value !== null && f.value !== undefined) ? String(f.value) : "—";
      const noteHtml = f.note
        ? `<span style="display:block;font-size:var(--fs-xs);color:#fff;margin-top:.1rem">` +
          `${_esc(f.note)}</span>`
        : "";
      valTd = `<td class="dvsm-val-cell">` +
              `<span class="dvsm-val${raw === "—" ? " placeholder" : ""}">` +
              `${_esc(raw)}</span>${noteHtml}</td>`;
      actTd = raw !== "—"
        ? `<td class="dvsm-actions">` +
          `<button class="dvsm-copy" data-copyval="${_esc(raw)}"` +
          ` onclick="dvsmCopyAttr(this)">&#x2398;</button></td>`
        : `<td class="dvsm-actions"></td>`;
    }
    html += `<tr><td class="dvsm-lbl">${_esc(f.label)}</td>${valTd}${actTd}</tr>`;
  });
  if (inTbl) html += `</table>`;
  body.innerHTML = html;
}

function _stfuRenderSample(bodyId, rawText) {
  _stfuSampleText = rawText;
  _renderSampleCode(bodyId, rawText, /^\s*;/, /^([^=]+)(=)(.*)/);
}

function _stfuRenderCompat(bodyId, compat) {
  _renderCompatTable(bodyId, compat);
}

function stfuCopyStanza(btn) {
  dvsmCopy(btn, _stfuSampleText);
}

async function stfuOpenEditor() {
  if (!_stfuDvsPath) { toast("DVSwitch.ini path unknown — refresh first", "warn"); return; }

  const taExisting = document.getElementById("stfu-textarea");
  if (taExisting && _stfuLoadedContent !== null && taExisting.value !== _stfuLoadedContent) {
    if (!await confirm("Discard unsaved changes to DVSwitch.ini?")) return;
  }

  const label = _stfuDvsPath.split("/").pop();

  const d = await api(`/api/dvswitch/file?label=${encodeURIComponent(label)}`);
  if (!d || !d.ok) {
    toast(d?.message || "Could not load DVSwitch.ini", "err"); return;
  }

  const ta = document.getElementById("stfu-textarea");
  if (ta) ta.value = d.content || "";
  _stfuLoadedContent = d.content || "";

  const pathEl = document.getElementById("stfu-editor-path");
  if (pathEl) pathEl.textContent = _stfuDvsPath;

  const wrap   = document.getElementById("stfu-editor-wrap");
  const togBtn = document.getElementById("stfu-editor-toggle");
  if (wrap)   { wrap.classList.add("open"); }
  if (togBtn) { togBtn.textContent = "▲ Collapse"; }

  if (wrap) wrap.closest(".s3-card")
    .scrollIntoView({ behavior: "smooth", block: "start" });

  if (ta) {
    const idx = ta.value.indexOf("[STFU]");
    if (idx !== -1) {
      ta.focus();
      ta.setSelectionRange(idx, idx + 6);
      const linesBefore = ta.value.substring(0, idx).split("\n").length - 1;
      const lh = parseFloat(getComputedStyle(ta).lineHeight) || 22;
      ta.scrollTop = linesBefore * lh;
    }
  }
}

function stfuToggleEditor() {
  const wrap   = document.getElementById("stfu-editor-wrap");
  const togBtn = document.getElementById("stfu-editor-toggle");
  if (!wrap) return;
  const opening = !wrap.classList.contains("open");
  wrap.classList.toggle("open", opening);
  if (togBtn) togBtn.textContent = opening ? "▲ Collapse" : "▼ Expand";
  if (opening) stfuOpenEditor();
}

async function stfuRestart() {
  if (!await confirm("Restart STFU service?")) return;
  const d = await api("/api/stfu", "POST", {action: "restart"});
  if (!d || !d.ok) { toast(d?.message || "Restart failed", "err"); return; }
  toast("STFU restarted", "ok");
}

function stfuDiscardEdit() {
  const wrap   = document.getElementById("stfu-editor-wrap");
  const togBtn = document.getElementById("stfu-editor-toggle");
  const ta     = document.getElementById("stfu-textarea");
  if (wrap)   wrap.classList.remove("open");
  if (togBtn) togBtn.textContent = "▼ Expand";
  if (ta)     ta.value = "";
}

async function loadStfu() {
  
  _stfuSecrets.clear();
  _stfuRevealed.clear();

  ["install", "config"].forEach(k =>
    _dvsmSetBadge("stfu-badge-" + k, "info", "...")
  );

  const d = await api("/api/stfu");
  if (!d || !d.ok) {
    ["install", "config"].forEach(k =>
      _dvsmSetBadge("stfu-badge-" + k, "fail", "ERR")
    );
    toast("STFU: failed to load config", "warn");
    return;
  }

  _stfuDvsPath = d.dvs_path || "";

  _stfuRenderInstall("stfu-body-install", "stfu-badge-install", d.install || {});
  _stfuRenderConfig("stfu-body-config",  "stfu-badge-config",
                    "stfu-config-path",  d.config || {});
  _stfuRenderCompat("stfu-body-compat",  d.compat || []);
  _stfuRenderSample("stfu-body-sample",  d.sample_stanza || "");
}

// ---- card: Edit DVSwitch.ini ----
async function stfuSave() {
  const ta = document.getElementById("stfu-textarea");
  if (!ta || !_stfuDvsPath) return;
  const label   = _stfuDvsPath.split("/").pop();
  const content = ta.value;
  if (!await confirm(`Save changes to ${label}?\n\nThis overwrites the file on disk.`)) return;
  const d = await api("/api/dvswitch/file", "POST", {label, content});
  if (!d || !d.ok) { toast(d?.message || "Save failed", "err"); return; }
  _stfuLoadedContent = content;
  toast(`Saved ${label}`, "ok");
}

async function stfuCopy() {
  const ta = document.getElementById("stfu-textarea");
  if (!ta || !ta.value) { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(ta.value);
}

// ========================================================================
// TAB: M17
// ========================================================================
// ---- general ----
function _m17RenderInstall(bodyId, badgeId, inst) {
  _renderInstallTable(bodyId, badgeId, inst, {
    binDefault: "/opt/USRP2M17/USRP2M17",
    binLabel:   "Binary present and executable",
    binFix:     "See USRP2M17 Bridge Manual §5 — build/install USRP2M17 to /opt/USRP2M17/",
    unit:       "usrp2m17",
    unitFix:    "Copy usrp2m17.service to /lib/systemd/system/ → systemctl daemon-reload",
  });
}

function _m17RenderConfig(bodyId, badgeId, pathId, cfgWrapper) {
  const fields = cfgWrapper.fields || [];

  let hasCallsign = false, hasAddr = false;
  fields.forEach(f => {
    if (!f.label) return;
    if (f.label === "Callsign" && f.value) hasCallsign = true;
    if (f.label === "Address"  && f.value && f.value !== "0.0.0.0") hasAddr = true;
  });
  const status = (hasCallsign && hasAddr) ? "pass" : (hasCallsign || hasAddr) ? "warn" : "fail";
  _dvsmSetBadge(badgeId, status);

  const pathEl = document.getElementById(pathId);
  if (pathEl && cfgWrapper.ini_path) {
    pathEl.textContent = cfgWrapper.ini_path;
  }

  const body = document.getElementById(bodyId);
  if (!body) return;

  if (!cfgWrapper.raw_ok) {
    body.innerHTML =
      `<div class="dvsm-note err">&#x26A0; ${_esc(cfgWrapper.error || "USRP2M17.ini not readable")}</div>`;
    return;
  }

  let html   = "";
  let inTbl  = false;

  fields.forEach(f => {
    if (f.group) {
      if (inTbl) { html += `</table>`; inTbl = false; }
      html += `<span class="dvsm-sec-lbl">${_esc(f.group)}</span>`;
      return;
    }

    if (!inTbl) { html += `<table class="dvsm-fields">`; inTbl = true; }

    const raw      = (f.value !== null && f.value !== undefined) ? String(f.value) : "—";
    const noteHtml = f.note
      ? `<span style="display:block;font-size:var(--fs-xs);color:#fff;margin-top:.1rem">` +
        `${_esc(f.note)}</span>`
      : "";
    const valTd = `<td class="dvsm-val-cell">` +
      `<span class="dvsm-val${raw === "—" ? " placeholder" : ""}">` +
      `${_esc(raw)}</span>${noteHtml}</td>`;
    const actTd = raw !== "—"
      ? `<td class="dvsm-actions">` +
        `<button class="dvsm-copy" data-copyval="${_esc(raw)}"` +
        ` onclick="dvsmCopyAttr(this)">&#x2398;</button></td>`
      : `<td class="dvsm-actions"></td>`;
    html += `<tr><td class="dvsm-lbl">${_esc(f.label)}</td>${valTd}${actTd}</tr>`;
  });
  if (inTbl) html += `</table>`;
  body.innerHTML = html;
}

function _m17RenderCompat(bodyId, compat) {
  _renderCompatTable(bodyId, compat);
}

function _m17RenderSample(bodyId, rawText) {
  _m17SampleText = rawText;
  _renderSampleCode(bodyId, rawText, /^\s*;/, /^([^=]+)(=)(.*)/);
}

function _m17RenderHosts(bodyId, badgeId, hosts) {
  hosts = hosts || {};
  const body = document.getElementById(bodyId);
  if (!body) return;

  let status, badgeText;
  if (!hosts.present) {
    status = "fail"; badgeText = "MISSING";
  } else if (!hosts.ok) {
    status = "fail"; badgeText = "INVALID";
  } else if ((hosts.age_days || 0) > 1) {
    status = "warn"; badgeText = "STALE";
  } else {
    status = "pass"; badgeText = "OK";
  }
  _dvsmSetBadge(badgeId, status, badgeText);

  if (!hosts.present) {
    body.innerHTML = `<div class="stub-panel" style="min-height:60px">` +
      `Reflector list not found — click Update Now to fetch it.</div>`;
    return;
  }

  const rows = [];
  if (hosts.ok) {
    rows.push(["Usable reflectors", String(hosts.count)]);
    rows.push(["List generated", _esc(hosts.generated || "unknown")]);
  } else {
    rows.push(["Problem", _esc(hosts.error || "invalid file")]);
  }
  rows.push(["File age", (hosts.age_days == null ? "—" : `${hosts.age_days}d`)]);
  rows.push(["File size", `${(hosts.size || 0).toLocaleString()} bytes`]);

  body.innerHTML = `<table class="dvsm-compat-tbl">` +
    rows.map(([k, v]) => `<tr><td class="dvsm-ct-key">${k}</td>` +
      `<td class="dvsm-ct-enables" colspan="2">${v}</td></tr>`).join("") +
    `</table>`;
}

async function m17UpdateHosts() {
  _dvsmSetBadge("m17-badge-hosts", "info", "...");
  const d = await api("/api/m17", "POST", {action: "update_hosts"});
  if (!d || !d.ok) { toast(d?.message || "Reflector list update failed", "err"); }
  else { toast(d.message || "Reflector list updated", "ok"); }
  loadM17();
}

function m17CopyStanza(btn) {
  dvsmCopy(btn, _m17SampleText);
}

async function m17Restart() {
  if (!await confirm("Restart usrp2m17 service?")) return;
  const d = await api("/api/m17", "POST", {action: "restart"});
  if (!d || !d.ok) { toast(d?.message || "Restart failed", "err"); return; }
  toast("usrp2m17 restarted", "ok");
  loadM17();
}

async function m17OpenEditor() {
  if (!_m17IniPath) { toast("USRP2M17.ini path unknown — refresh first", "warn"); return; }

  const taExisting = document.getElementById("m17-textarea");
  if (taExisting && _m17LoadedContent !== null && taExisting.value !== _m17LoadedContent) {
    if (!await confirm("Discard unsaved changes to USRP2M17.ini?")) return;
  }

  const label = _m17IniPath.split("/").pop();

  const d = await api(`/api/dvswitch/file?label=${encodeURIComponent(label)}`);
  if (!d || !d.ok) {
    toast(d?.message || "Could not load USRP2M17.ini", "err"); return;
  }

  const ta = document.getElementById("m17-textarea");
  if (ta) ta.value = d.content || "";
  _m17LoadedContent = d.content || "";

  const pathEl = document.getElementById("m17-editor-path");
  if (pathEl) pathEl.textContent = _m17IniPath;

  const wrap   = document.getElementById("m17-editor-wrap");
  const togBtn = document.getElementById("m17-editor-toggle");
  if (wrap)   { wrap.classList.add("open"); }
  if (togBtn) { togBtn.textContent = "▲ Collapse"; }

  if (wrap) wrap.closest(".s3-card")
    .scrollIntoView({ behavior: "smooth", block: "start" });

  if (ta) ta.focus();
}

function m17ToggleEditor() {
  const wrap   = document.getElementById("m17-editor-wrap");
  const togBtn = document.getElementById("m17-editor-toggle");
  if (!wrap) return;
  const opening = !wrap.classList.contains("open");
  wrap.classList.toggle("open", opening);
  if (togBtn) togBtn.textContent = opening ? "▲ Collapse" : "▼ Expand";
  if (opening) m17OpenEditor();
}

function m17DiscardEdit() {
  const wrap   = document.getElementById("m17-editor-wrap");
  const togBtn = document.getElementById("m17-editor-toggle");
  const ta     = document.getElementById("m17-textarea");
  if (wrap)   wrap.classList.remove("open");
  if (togBtn) togBtn.textContent = "▼ Expand";
  if (ta)     ta.value = "";
}

async function loadM17() {
  ["install", "config", "hosts"].forEach(k =>
    _dvsmSetBadge("m17-badge-" + k, "info", "...")
  );

  const d = await api("/api/m17");
  if (!d || !d.ok) {
    ["install", "config", "hosts"].forEach(k =>
      _dvsmSetBadge("m17-badge-" + k, "fail", "ERR")
    );
    toast("M17: failed to load config", "warn");
    return;
  }

  _m17RenderInstall("m17-body-install", "m17-badge-install", d.install || {});
  _m17RenderConfig("m17-body-config",  "m17-badge-config",
                    "m17-config-path",  d.config || {});
  _m17RenderCompat("m17-body-compat",  d.compat || []);
  _m17RenderHosts("m17-body-hosts", "m17-badge-hosts", d.hosts || {});
  _m17RenderSample("m17-body-sample",  d.sample_stanza || "");
  _m17IniPath = (d.config && d.config.ini_path) || "";
}

// ---- card: Edit USRP2M17.ini ----
async function m17Save() {
  const ta = document.getElementById("m17-textarea");
  if (!ta || !_m17IniPath) return;
  const label   = _m17IniPath.split("/").pop();
  const content = ta.value;
  if (!await confirm(`Save changes to ${label}?\n\nThis overwrites the file on disk. ` +
                      `Remember: the ASL-DVS-M17 dashboard will overwrite it again on the next connect/disconnect.`)) return;
  const d = await api("/api/dvswitch/file", "POST", {label, content});
  if (!d || !d.ok) { toast(d?.message || "Save failed", "err"); return; }
  _m17LoadedContent = content;
  toast(`Saved ${label}`, "ok");
}

async function m17Copy() {
  const ta = document.getElementById("m17-textarea");
  if (!ta || !ta.value) { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(ta.value);
}

// ========================================================================
// TAB: SD Card
// ========================================================================
// ---- general ----
async function loadSdHealth() {
  const body = document.getElementById("sd-health-body");
  const meta = document.getElementById("sd-health-meta");
  const btn  = document.getElementById("sd-health-refresh");
  if (body) body.innerHTML =
    `<div class="stub-panel" style="min-height:80px">Reading SD card…</div>`;
  if (meta) meta.textContent = "checking…";
  if (btn)  btn.disabled = true;

  const d = await api("/api/sdcard");

  if (btn) btn.disabled = false;
  if (!d || !d.ok) {
    if (meta) meta.textContent = "error";
    if (body) body.innerHTML =
      `<div class="stub-panel" style="min-height:60px">Failed to read SD card status</div>`;
    return;
  }
  renderSdHealth(d);
}

function renderSdHealth(d) {
  const body = document.getElementById("sd-health-body");
  const meta = document.getElementById("sd-health-meta");
  if (!body) return;

  const dev  = d.device     || {};
  const id   = d.identity   || {};
  const cap  = d.capacity   || {};
  const fs   = d.filesystem || {};
  const io   = d.io         || {};
  const err  = d.errors     || {};
  const warn = d.warnings   || [];

  const row = (label, val, cls, note) => {
    if (val === undefined || val === null || val === "") return "";
    const noteHtml = note ? `<span class="hw-pwr-note">${_esc(note)}</span>` : "";
    return `<tr>
      <td class="hw-pwr-lbl">${_esc(label)}</td>
      <td class="hw-pwr-val ${cls || ""}">${_esc(val)}${noteHtml}</td>
    </tr>`;
  };
  const sect = (title, rows) =>
    rows ? `<div class="hw-pwr-lbl" style="padding:.55rem .9rem .15rem;
              color:#fff;letter-spacing:.12em">${_esc(title)}</div>
            <table class="hw-pwr-tbl">${rows}</table>` : "";

  const devName = (id.manufacturer && id.manufacturer !== "n/a")
    ? `${id.manufacturer} ${id.name && id.name !== "n/a" ? id.name : ""}`.trim()
    : (dev.disk_path || "unknown device");
  if (meta) {
    if (warn.length) {
      meta.textContent = `${devName} · ⚠ ${warn.length} issue${warn.length>1?"s":""}`;
      meta.style.color = "var(--red)";
    } else {
      meta.textContent = `${devName} · healthy`;
      meta.style.color = "var(--green)";
    }
  }

  let html = "";

  if (warn.length) {
    html += `<div class="hw-diag-pre" style="border-left:3px solid var(--red);
      color:var(--red);margin:.2rem 0 .4rem">` +
      warn.map(w => "⚠ " + _esc(w)).join("\n") + `</div>`;
  }

  html += sect("Device",
    row("Disk",        dev.disk_path) +
    row("Root source", dev.root_source));

  let idRows =
    row("Manufacturer", id.manufacturer) +
    row("Product",      id.name) +
    row("Serial",       id.serial) +
    row("Mfg date",     id.date) +
    row("FW / HW rev",  (id.fwrev && id.hwrev) ? `${id.fwrev} / ${id.hwrev}` : "") +
    row("Erase size",   id.preferred_erase_size);
  if (id.is_emmc) {
    idRows += row("Life time",   id.life_time, "warn");
    idRows += row("Pre-EOL info", id.pre_eol_info, "warn");
  }
  html += sect("Identity", idRows);

  const upct = cap.fs_used_pct;
  const ucls = upct == null ? "" : upct >= 90 ? "hot" : upct >= 75 ? "warn" : "ok";
  const ipct = cap.inodes_used_pct;
  const icls = ipct == null ? "" : ipct >= 90 ? "hot" : ipct >= 75 ? "warn" : "ok";
  html += sect("Capacity",
    row("Card size",   cap.size_h) +
    row("FS total",    cap.fs_total_h) +
    row("FS used",     upct != null ? `${cap.fs_used_h} (${upct}%)` : cap.fs_used_h, ucls) +
    row("FS available", cap.fs_avail_h) +
    row("Inodes used", ipct != null ? `${ipct}%` : null, icls));

  if (fs.available) {
    const stClean = String(fs.state || "").toLowerCase().includes("clean");
    html += sect("Filesystem (ext4)",
      row("State",          fs.state, stClean ? "ok" : "hot") +
      row("Mount count",    (fs.mount_count != null && fs.max_mount_count != null)
                              ? `${fs.mount_count} / ${fs.max_mount_count}` : fs.mount_count) +
      row("Last checked",   fs.last_checked) +
      row("Lifetime writes", fs.lifetime_writes) +
      row("Errors behavior", fs.errors_behavior));
  } else {
    html += sect("Filesystem (ext4)",
      row("Status", fs.error || "unavailable", "warn",
          "tune2fs reads the superblock — run sysmon as root for FS stats"));
  }

  if (io.available) {
    html += sect("I/O counters (since boot)",
      row("Bytes read",    io.bytes_read_h) +
      row("Bytes written", io.bytes_written_h,
          null, "Cumulative since last boot — wear proxy, not card-lifetime total"));
  }

  let errRows = "";
  if (err.ro_mount) {
    errRows += row("Root mount", err.ro_mount === "ro" ? "READ-ONLY" : "read-write",
                   err.ro_mount === "ro" ? "hot" : "ok",
                   err.ro_mount === "ro" ? "Filesystem dropped to read-only — likely corruption" : "");
  }
  if (err.available) {
    errRows += row("Kernel error lines", String(err.count),
                   err.count > 0 ? "warn" : "ok");
  } else if (err.note) {
    errRows += row("Kernel log", err.note, "warn");
  }
  html += sect("Errors", errRows);

  if (err.available && err.kernel_lines && err.kernel_lines.length) {
    html += `<div style="display:flex;align-items:center;justify-content:space-between;
      padding:.55rem .9rem .15rem">
      <span class="hw-pwr-lbl" style="padding:0;color:#fff;letter-spacing:.12em">
        Kernel storage log (last ${err.kernel_lines.length})</span>
      <button class="btn btn-muted btn-sm" onclick="sdKernelLogCopy()">⎘ Copy</button>
    </div>`;
    html += `<pre class="hw-diag-pre" id="sd-kernel-log-pre" style="max-height:220px;overflow:auto">` +
      err.kernel_lines.map(l => _esc(l)).join("\n") + `</pre>`;
  }

  body.innerHTML = html ||
    `<div class="stub-panel" style="min-height:60px">No SD card data</div>`;
}

async function dpStatusCopy() {
  const out = document.getElementById("dpanel-output");
  const text = out ? Array.from(out.children).map(d => d.textContent).join("\n").trim() : "";
  if (!text || text === "Loading…") { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(text);
}

async function sdKernelLogCopy() {
  const pre = document.getElementById("sd-kernel-log-pre");
  if (!pre || !pre.textContent) { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(pre.textContent);
}

async function loadSdTests() {
  const d = await api("/api/sdcard/test");
  renderSdTests(d || {});
  if (d && d.status === "running" && !_sdTestTimer) {
    _sdTestTimer = setInterval(sdTestPoll, 1500);
  }
}

async function sdTestPoll() {
  const d = await api("/api/sdcard/test");
  renderSdTests(d || {});
  if (!d || d.status !== "running") {
    clearInterval(_sdTestTimer); _sdTestTimer = null;
  }
}

async function sdTestStart(test) {
  const label = "Run a read-only fsck (fsck -n) on the root partition?\n\n" +
    "Safe and non-destructive. Results are advisory because the root filesystem is mounted live.";
  if (!await confirm(label)) return;

  const d = await api("/api/sdcard/test", "POST", {action: "start", test: test});
  if (!d || !d.ok) { toast((d && d.message) || "Could not start test", "err"); }
  else { toast(d.message || "Started", "ok"); }
  await loadSdTests();
  if (d && d.ok && !_sdTestTimer) _sdTestTimer = setInterval(sdTestPoll, 1500);
}

async function sdTestCancel() {
  const d = await api("/api/sdcard/test", "POST", {action: "cancel"});
  if (d && d.message) toast(d.message, d.ok ? "ok" : "err");
  await loadSdTests();
}

function renderSdTests(d) {
  const body = document.getElementById("sd-test-body");
  const meta = document.getElementById("sd-test-meta");
  if (!body) return;

  const running = d.status === "running";
  if (meta) {
    meta.textContent = running ? `running ${d.test || ""}…`
      : (d.status && d.status !== "idle") ? `${d.test || ""}: ${d.status}` : "read-only";
    meta.style.color = running ? "var(--amber)"
      : d.status === "cancelled" ? "var(--text-dim)"
      : (d.status === "done" && /error/i.test(d.message || "")) ? "var(--red)"
      : d.status === "done" ? "var(--green)" : "";
  }

  let html = "";

  html += `<div class="hw-diag-pre" style="border-left:3px solid var(--amber);
    color:var(--amber);margin:.1rem 0 .5rem">⚠ Read-only diagnostics only. ` +
    `fsck -n on a mounted root is advisory.</div>`;

  html += `<div style="display:flex;gap:.4rem;flex-wrap:wrap;margin:.2rem 0 .5rem">`;
  if (running) {
    html += `<button class="btn btn-red btn-sm" onclick="sdTestCancel()">■ Cancel</button>`;
  } else {
    html += `<button class="btn btn-muted btn-sm" onclick="sdTestStart('fsck')">Run fsck -n (advisory)</button>`;
  }
  html += `</div>`;

  if (d.pct != null) {
    const pct = Math.max(0, Math.min(100, d.pct));
    html += `<div style="background:#152033;border-radius:3px;height:14px;overflow:hidden;margin:.2rem 0">
      <div style="height:100%;width:${pct}%;background:var(--amber);transition:width .4s"></div>
    </div>
    <div class="hw-pwr-note" style="margin:0 0 .3rem">${pct}% ${d.progress ? "· " + _esc(d.progress) : ""}</div>`;
  }

  if (d.status && d.status !== "idle") {
    const elapsed = d.elapsed != null ? ` · ${d.elapsed}s` : "";
    html += `<div class="hw-pwr-note" style="margin:.1rem 0 .4rem">
      <b>${_esc((d.test||"").toUpperCase())}</b> on ${_esc(d.target||"?")} — ${_esc(d.status)}${elapsed}
      ${d.message ? "<br>" + _esc(d.message) : ""}</div>`;
  }

  if (d.lines && d.lines.length) {
    html += `<pre class="hw-diag-pre" style="max-height:240px;overflow:auto">` +
      d.lines.map(l => _esc(l)).join("\n") + `</pre>`;
  }

  body.innerHTML = html;
}

// ========================================================================
// TAB: Edit
// ========================================================================
// ---- general ----
function edToggleAslDvs() {
  _edAslOpen = !_edAslOpen;
  const body    = document.getElementById("ed-asl-body");
  const hdr     = document.getElementById("ed-asl-hdr");
  const chevron = document.getElementById("ed-asl-chevron");
  if (!body) return;

  if (_edAslOpen) {
    hdr?.classList.add("open");
    body.classList.remove("collapsed");
    body.style.maxHeight = body.scrollHeight + "px";
    body.addEventListener("transitionend", function _edAslUnfreeze(e) {
      if (e.propertyName !== "max-height") return;
      body.removeEventListener("transitionend", _edAslUnfreeze);
      if (_edAslOpen) body.style.maxHeight = "none";
    });
    edAslDvsLoad();
  } else {
    hdr?.classList.remove("open");
    body.style.maxHeight = body.scrollHeight + "px";
    requestAnimationFrame(() => requestAnimationFrame(() => {
      body.style.maxHeight = "0";
      body.classList.add("collapsed");
    }));
  }
}

const FIND_TEXTAREA = { ed: "ed-pinned", uf: "uf-textarea", allconf: "allconf-textarea" };
const _findIdx = {};

function findHits(ta, needle) {
  const hits = [];
  if (!needle) return hits;
  const text = ta.value.toLowerCase();
  const q = needle.toLowerCase();
  let i = text.indexOf(q);
  while (i !== -1) {
    hits.push(i);
    i = text.indexOf(q, i + q.length);
  }
  return hits;
}

function findShow(p, hits, q) {
  const ta   = document.getElementById(FIND_TEXTAREA[p]);
  const cnt  = document.getElementById(`${p}-find-count`);
  const prev = document.getElementById(`${p}-find-prev`);
  const next = document.getElementById(`${p}-find-next`);
  if (!ta || !cnt) return;
  const idx  = _findIdx[p] || 0;
  const n    = hits.length;
  const none = n === 0;
  prev.disabled = none;
  next.disabled = none;
  cnt.textContent = none ? (q ? "No matches" : "") : `${idx + 1} of ${n}`;
  if (none) return;
  const start = hits[idx];
  const line  = ta.value.slice(0, start).split("\n").length - 1;
  const lh    = parseFloat(getComputedStyle(ta).lineHeight) || 20;
  ta.setSelectionRange(start, start + q.length);
  ta.scrollTop = Math.max(0, line * lh - ta.clientHeight / 3);
}

function findStart(p) {
  _findIdx[p] = 0;
  findStep(p, 0);
}

function findStep(p, dir) {
  const ta = document.getElementById(FIND_TEXTAREA[p]);
  const q  = document.getElementById(`${p}-find-inp`)?.value || "";
  if (!ta) return;
  const hits = findHits(ta, q);
  const n = hits.length;
  const idx = _findIdx[p] || 0;
  _findIdx[p] = n ? (((idx + dir) % n) + n) % n : 0;
  findShow(p, hits, q);
}

function findKey(e, p) {
  if (e.key === "Enter") {
    e.preventDefault();
    findStep(p, e.shiftKey ? -1 : 1);
  } else if (e.key === "Escape") {
    e.target.value = "";
    findStart(p);
  }
}

function findReset(p) {
  const inp = document.getElementById(`${p}-find-inp`);
  if (inp) inp.value = "";
  _findIdx[p] = 0;
  findShow(p, [], "");
}

function edTogglePinned() {
  _edPinnedOpen = !_edPinnedOpen;
  const body    = document.getElementById("ed-pinned-body");
  const hdr     = document.getElementById("ed-pinned-hdr");
  const chevron = document.getElementById("ed-pinned-chevron");
  if (!body) return;

  if (_edPinnedOpen) {
    hdr?.classList.add("open");
    body.classList.remove("collapsed");
    body.style.maxHeight = body.scrollHeight + "px";
    body.addEventListener("transitionend", function _edPinnedUnfreeze(e) {
      if (e.propertyName !== "max-height") return;
      body.removeEventListener("transitionend", _edPinnedUnfreeze);
      if (_edPinnedOpen) body.style.maxHeight = "none";
    });
  } else {
    hdr?.classList.remove("open");
    body.style.maxHeight = body.scrollHeight + "px";
    requestAnimationFrame(() => requestAnimationFrame(() => {
      body.style.maxHeight = "0";
      body.classList.add("collapsed");
    }));
  }
}

async function edReload() {
  const d = await api("/api/config");
  if (!d || !d.ok) { toast("Failed to load config", "err"); return; }

  const set = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.value = val || "";
  };
  set("ed-callsign", d.identity?.callsign);
  set("ed-node",     d.identity?.node);
  set("ed-label",    d.identity?.label);
  set("ed-port",     d.server?.port);
  set("ed-host",     d.server?.host);
  set("ed-cpu-warn", d.thresholds?.cpu_warn_pct);
  set("ed-rss-warn", d.thresholds?.rss_warn_mb);
  set("ed-nr-warn",  d.thresholds?.nr_warn);
  set("ed-nr-crit",  d.thresholds?.nr_crit);
  _applyThresholds(d.thresholds);

  const ta = document.getElementById("ed-pinned");
  if (ta) ta.value = d.services?.pinned || "";

  edSetTabVis(d.ui?.enabled_tabs);

  edCountPinned();
  edClearErrors();
  edSetStatus("");
  _edDirty = false;
  edUpdateSaveBtn(true);
}

function edSetTabVis(enabled) {
  const set = new Set(Array.isArray(enabled) ? enabled : TABS);
  for (const t of TABS) {
    if (ED_LOCKED_TABS.includes(t)) continue;
    const chk = document.getElementById("tabchk-" + t);
    if (chk) chk.checked = set.has(t);
  }
}

function edGetTabVis() {
  const out = [];
  for (const t of TABS) {
    if (ED_LOCKED_TABS.includes(t)) { out.push(t); continue; }
    const chk = document.getElementById("tabchk-" + t);
    if (chk && chk.checked) out.push(t);
  }
  return out;
}

function edTabVisChanged() {
  _edDirty = true;
  edSetStatus("");
}

function edValidate() {
  _edDirty = true;
  let valid = true;

  const cs = (document.getElementById("ed-callsign")?.value || "").trim();
  valid = edField("ed-callsign", "ed-callsign-err",
    cs.length >= 1 && cs.length <= 9 && /^[A-Z0-9 /.\-]+$/i.test(cs),
    "A-Z 0-9 - / . only, max 9 chars") && valid;

  const node = (document.getElementById("ed-node")?.value || "").trim();
  valid = edField("ed-node", "ed-node-err",
    /^\d{1,7}$/.test(node),
    "Numeric only, 1–7 digits") && valid;

  const port = (document.getElementById("ed-port")?.value || "").trim();
  const portN = parseInt(port);
  valid = edField("ed-port", "ed-port-err",
    /^\d+$/.test(port) && portN >= 1024 && portN <= 65535,
    "Integer 1024–65535") && valid;

  const host = (document.getElementById("ed-host")?.value || "").trim();
  valid = edField("ed-host", "ed-host-err",
    host.length > 0, "Must not be empty") && valid;

  edUpdateSaveBtn(valid);
  return valid;
}

function edField(inpId, errId, ok, errMsg) {
  const inp = document.getElementById(inpId);
  const err = document.getElementById(errId);
  if (inp) inp.classList.toggle("invalid", !ok);
  if (err) {
    err.textContent = ok ? "" : errMsg;
    err.classList.toggle("show", !ok);
  }
  return ok;
}

function edClearErrors() {
  ED_FIELDS.forEach(f => {
    const inp = document.getElementById(f.id);
    if (inp) inp.classList.remove("invalid");
  });
  document.querySelectorAll(".ed-err").forEach(el => {
    el.textContent = "";
    el.classList.remove("show");
  });
}

function edUpdateSaveBtn(valid) {
  const btn = document.getElementById("ed-save-btn");
  if (btn) btn.disabled = !valid;
}

function edSetStatus(msg, ok) {
  const el = document.getElementById("ed-status");
  if (!el) return;
  el.textContent = msg;
  el.style.color = ok === true  ? "var(--green)"
                 : ok === false ? "var(--red)"
                 : "#3a5278";
}

async function edSave() {
  if (!edValidate()) {
    toast("Fix validation errors before saving", "err"); return;
  }
  const btn = document.getElementById("ed-save-btn");
  if (btn) btn.disabled = true;
  edSetStatus("Saving…");

  const payload = {};
  ED_FIELDS.forEach(f => {
    const el = document.getElementById(f.id);
    if (el && el.value.trim() !== "") payload[f.key] = el.value.trim();
  });
  const ta = document.getElementById("ed-pinned");
  if (ta) payload["services.pinned"] = ta.value;

  const visTabs = edGetTabVis();
  payload["ui.enabled_tabs"] = visTabs.join(",");

  const d = await api("/api/config", "POST", payload);
  if (btn) btn.disabled = false;

  if (!d) {
    edSetStatus("Server unreachable", false);
    toast("Server unreachable", "err");
    return;
  }
  if (!d.ok) {
    const errMsg = (d.errors || [d.message || "Save failed"]).join("; ");
    edSetStatus(errMsg, false);
    toast(errMsg, "err");
    return;
  }

  _savedEnabledTabs = visTabs;
  _applyTabVisibilityGated();

  edSetStatus("Saved ✓", true);
  toast("Config saved", "ok");
  _edDirty = false;

  const val = id => document.getElementById(id)?.value;
  _applyThresholds({nr_warn: val("ed-nr-warn"), nr_crit: val("ed-nr-crit"),
                    cpu_warn_pct: val("ed-cpu-warn"), rss_warn_mb: val("ed-rss-warn")});
}

async function edAllConf(mode) {
  const overlay = document.getElementById("allconf-overlay");
  const ta      = document.getElementById("allconf-textarea");
  const info    = document.getElementById("allconf-info");
  const title   = document.getElementById("allconf-title");
  if (!overlay || !ta || !info) return;

  ta.value        = "";
  info.textContent = "Loading…";
  if (title) {
    title.textContent = mode === "dvs"
      ? "DVS Config Files"
      : "ASL Config Files";
  }
  findReset("allconf");
  overlay.classList.add("open");

  const sep  = n => "═".repeat(n);
  const hdr  = (label, path) =>
    `# ${sep(60)}\n# ${label}   (${path})\n# ${sep(60)}`;
  const parts = [];

  if (mode !== "dvs") {
    const da = await api("/api/asterisk/files");
    if (da && Array.isArray(da.files)) {
      for (const f of da.files) {
        const name = typeof f === "string" ? f : f.name;
        const d = await api(`/api/asterisk/file?name=${encodeURIComponent(name)}`);
        if (d && d.ok) {
          parts.push(`${hdr(name, d.path)}\n${d.content}`);
        }
      }
    }

    const dm = await api("/api/allmon3/files");
    if (dm && Array.isArray(dm.files)) {
      for (const f of dm.files) {
        if (!f.exists) continue;
        const d = await api(`/api/allmon3/file?label=${encodeURIComponent(f.label)}`);
        if (d && d.ok && d.exists) {
          parts.push(`${hdr(f.label, d.path)}\n${d.content}`);
        }
      }
    }
  }

  if (mode === "dvs") {
    const dd = await api("/api/dvswitch/files");
    if (dd && Array.isArray(dd.files)) {
      for (const f of dd.files) {
        if (!f.exists) continue;
        const d = await api(`/api/dvswitch/file?label=${encodeURIComponent(f.label)}`);
        if (d && d.ok && d.exists) {
          parts.push(`${hdr(f.label, d.path)}\n${d.content}`);
        }
      }
    }
  }

  ta.value = parts.join("\n\n");
  const n  = parts.length;
  info.textContent = n
    ? `${n} file${n !== 1 ? "s" : ""} — select all (Ctrl+A) and copy, or use Copy All`
    : "No visible conf files found";
}

function allConfOverlayClick(e) {
  if (e.target === document.getElementById("allconf-overlay")) closeAllConf();
}

function closeAllConf() {
  document.getElementById("allconf-overlay")?.classList.remove("open");
}

async function allConfCopy() {
  const ta = document.getElementById("allconf-textarea");
  if (!ta || !ta.value) { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(ta.value);
}

async function openAppConfEditor(label) {
  return _ufOpenLabelFile("\x00appconf:", "/api/appconf/file", label);
}

// ========================================================================
// TAB: Ports -- port list and details
// ========================================================================
async function loadPorts() {
  const d = await api("/api/ports?proto=both");
  if (!d) return;
  _ptAll = d.ports || [];
  renderPorts(_ptShown());

  const ts = document.getElementById("pt-refresh-ts");
  if (ts) ts.textContent = "↻ " + new Date().toTimeString().slice(0,8);
}

function _ptShown() {
  return _ptProto === "both" ? _ptAll : _ptAll.filter(p => p.proto === _ptProto);
}

function renderPorts(ports) {
  const body = document.getElementById("pt-body");
  if (!body) return;
  body.innerHTML = "";

  if (!ports.length) {
    body.innerHTML = '<div class="stub-panel" style="min-height:60px">No open ports found.</div>';
    return;
  }

  ports.forEach(p => {
    const row = document.createElement("div");
    row.className = "pt-row";
    row.onclick   = () => openPortPanel(p);

    const svcText = p.service || "— unknown —";
    const svcCls  = p.service ? "pt-service" : "pt-service unknown";
    const dotCls  = p.service ? "dot-on" : "dot-off";

    row.innerHTML =
      `<span class="dot ${dotCls}"></span>` +
      `<span class="pt-port">${esc(p.port)}</span>` +
      `<span class="pt-proto ${p.proto}">${esc(p.proto)}</span>` +
      `<span class="pt-process">${esc(p.process || "—")}</span>` +
      `<span class="pt-pid">${p.pid || "—"}</span>` +
      `<span class="${svcCls}">${esc(svcText)}</span>`;
    row.appendChild(portBadge(p.port, p.proto));
    body.appendChild(row);
  });
}

function openPortPanel(p) {
  
  _dpUnit = "";

  document.getElementById("dpanel").style.setProperty(
    "--panel-accent", "var(--blue)");

  document.getElementById("dpanel-unit").textContent =
    `:${p.port} / ${p.proto}`;
  document.getElementById("dpanel-desc").textContent =
    p.process + (p.service ? "  —  " + p.service + ".service" : "");
  document.getElementById("dpanel-badges").innerHTML = "";
  document.getElementById("dpanel-output").innerHTML =
    '<span class="dp-out-dim">Select an action below</span>';

  const body = document.getElementById("dpanel-body");
  _dpRestoreBody();
  body.dataset.custom = "1";
  body.innerHTML = `
    <div class="dpzone-lbl">Port Details</div>
    <div style="padding:.55rem .9rem;font-family:var(--sans);font-size:var(--fs-sm);
      border-bottom:1px solid var(--border);line-height:1.9">
      <div><span style="color:#fff;letter-spacing:.12em;text-transform:uppercase;
        font-size:var(--fs-xs)">Port&nbsp;&nbsp;&nbsp;</span>
        <span style="color:var(--blue)">${esc(p.port)}</span></div>
      <div><span style="color:#fff;letter-spacing:.12em;text-transform:uppercase;
        font-size:var(--fs-xs)">Proto&nbsp;&nbsp;</span>
        <span style="color:${p.proto==="tcp"?"var(--blue)":"var(--green)"}">
        ${esc(p.proto.toUpperCase())}</span></div>
      <div><span style="color:#fff;letter-spacing:.12em;text-transform:uppercase;
        font-size:var(--fs-xs)">Process</span>
        <span style="color:var(--teal)">${esc(p.process || "—")}</span></div>
      <div><span style="color:#fff;letter-spacing:.12em;text-transform:uppercase;
        font-size:var(--fs-xs)">PID&nbsp;&nbsp;&nbsp;&nbsp;</span>
        <span>${p.pid || "—"}</span></div>
      <div><span style="color:#fff;letter-spacing:.12em;text-transform:uppercase;
        font-size:var(--fs-xs)">Listen&nbsp;&nbsp;</span>
        <span>${esc(p.addr || "0.0.0.0")}:${esc(p.port)}</span></div>
      ${p.service ? `<div><span style="color:#fff;letter-spacing:.12em;
        text-transform:uppercase;font-size:var(--fs-xs)">Service</span>
        <span style="color:var(--amber)">${esc(p.service)}.service</span></div>` : ""}
    </div>
    <div class="dpbtn-row">
      <button class="btn btn-muted btn-sm"
        onclick="dtCopy(this, () => ptOneText('${esc(p.port)}', '${esc(p.proto)}'))">⎘ Copy port details</button>
    </div>
    <div class="dpzone-lbl">Port Probes</div>
    <div class="dpbtn-row">
      ${p.proto==="tcp"
        ? `<button class="btn btn-blue btn-sm"
             onclick="ptProbeHttp('${p.port}')">⦿ HTTP Probe</button>
           <button class="btn btn-muted btn-sm"
             onclick="ptProbeTcp('${p.port}')">⦿ TCP Probe</button>`
        : `<button class="btn btn-muted btn-sm"
             onclick="ptProbeUdp('${p.port}')">⦿ UDP Probe</button>`}
    </div>
    ${p.service ? `
    <div class="dpzone-lbl">Service Actions</div>
    <div class="dpbtn-row">
      <button class="btn btn-blue  btn-sm"
        onclick="ptSvcAction('restart','${esc(p.service)}.service')">↺ Restart Service</button>
      <button class="btn btn-amber btn-sm"
        onclick="ptSvcAction('stop','${esc(p.service)}.service')">■ Stop Service</button>
      <button class="btn btn-purple btn-sm"
        onclick="ptViewJournal('${esc(p.service)}.service')">▤ Journal</button>
    </div>` : ""}
    <div id="dpanel-output" style="margin:.55rem .9rem;background:#0a1020;
      border:1px solid var(--border);border-radius:3px;min-height:60px;
      max-height:180px;overflow-y:auto;padding:.5rem .7rem;
      font-family:var(--sans);font-size:var(--fs-sm);color:#fff;line-height:1.65">
      <span class="dp-out-dim">Probe results appear here</span>
    </div>`;

  document.getElementById("dpanel-overlay").classList.add("open");
  document.getElementById("dpanel").classList.add("open");
}

function _ptOut(html) {
  const out = document.getElementById("dpanel-output");
  if (!out) return;
  out.innerHTML = html;
  out.scrollIntoView({block: "nearest", behavior: "smooth"});
}

async function _ptProbe(kind, port) {
  _ptOut(`<span class="dp-out-dim">Probing ${kind.toUpperCase()} :${esc(port)}…</span>`);
  const d = await api(`/api/ports/probe?type=${kind}&port=${encodeURIComponent(port)}`);
  if (!d) { _ptOut('<span class="dp-out-fail">Request failed</span>'); return; }
  _ptOut(`<span class="${d.ok ? "dp-out-ok" : "dp-out-fail"}">${esc(d.message || "done")}</span>`);
}

function ptProbeHttp(port) { return _ptProbe("http", port); }

function ptProbeTcp(port) { return _ptProbe("tcp", port); }

function ptProbeUdp(port) { return _ptProbe("udp", port); }

async function ptSvcAction(action, unit) {
  const d = await api("/api/svc", "POST", {action, unit});
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "OK" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) setTimeout(loadPorts, 800);
}

function ptViewJournal(unit) {
  
  closePanel();
  openJournalPopup(unit);
}

// ========================================================================
// TAB: DVSM -- shared card helpers
// ========================================================================
function dvsmCopySecret(btn, fid) { dvsmCopy(btn, _dvsmSecrets.get(fid) || ""); }

function dvsmReveal(eyeBtn, fid) {
  _toggleReveal(eyeBtn, fid, _dvsmRevealed, _dvsmSecrets);
}

function _dvsmRenderAccount(bodyId, badgeId, acct, cardKey) {
  _dvsmSetBadge(badgeId, acct.status);
  const body = document.getElementById(bodyId);
  if (!body) return;

  if (!acct.fields) {
    body.innerHTML = `<div class="dvsm-note err">&#x26A0; ${_esc(acct.error || "No data")}</div>`;
    return;
  }

  let rows = "";
  (acct.fields || []).forEach((f, i) => {
    const fid = "dvsm-fv-" + cardKey + "-" + i;
    let valTd, actTd;

    if (f.masked) {
      
      _dvsmRevealed.delete(fid);
      if (f.secret) {
        _dvsmSecrets.set(fid, f.secret);
        valTd = `<td class="dvsm-val-cell">` +
                `<span id="${fid}" class="dvsm-val masked">` +
                `&#x25CF;&#x25CF;&#x25CF;&#x25CF;&#x25CF;&#x25CF;&#x25CF;&#x25CF;</span></td>`;
        actTd = `<td class="dvsm-actions">` +
                `<button class="dvsm-eye" title="Reveal"` +
                ` onclick="dvsmReveal(this,'${fid}')">&#x1F441;</button>` +
                `<button class="dvsm-copy"` +
                ` onclick="dvsmCopySecret(this,'${fid}')">&#x2398;</button>` +
                `</td>`;
      } else {
        
        valTd = `<td class="dvsm-val-cell">` +
                `<span class="dvsm-val placeholder">${_esc(f.note || "not found")}</span></td>`;
        actTd = `<td class="dvsm-actions"></td>`;
      }
    } else {
      const raw = (f.value !== null && f.value !== undefined) ? String(f.value) : "—";
      const noteHtml = f.note
        ? `<span style="display:block;font-size:var(--fs-xs);color:#fff;margin-top:.1rem">` +
          `${_esc(f.note)}</span>`
        : "";
      valTd = `<td class="dvsm-val-cell">` +
              `<span class="dvsm-val${raw === "—" ? " placeholder" : ""}">` +
              `${_esc(raw)}</span>${noteHtml}</td>`;
      actTd = raw !== "—"
        ? `<td class="dvsm-actions">` +
          `<button class="dvsm-copy" data-copyval="${_esc(raw)}"` +
          ` onclick="dvsmCopyAttr(this)">&#x2398;</button></td>`
        : `<td class="dvsm-actions"></td>`;
    }
    rows += `<tr><td class="dvsm-lbl">${_esc(f.label)}</td>${valTd}${actTd}</tr>`;
  });

  let notesHtml = "";
  (acct.notes   || []).forEach(n => {
    notesHtml += `<div class="dvsm-note warn">&#x26A0; ${_esc(n)}</div>`;
  });
  (acct.missing || []).forEach(n => {
    notesHtml += `<div class="dvsm-note err">&#x2717; ${_esc(n)}</div>`;
  });
  if (acct.error) {
    notesHtml += `<div class="dvsm-note src">Source error: ${_esc(acct.error)}</div>`;
  }

  body.innerHTML = `<table class="dvsm-fields">${rows}</table>${notesHtml}`;
}

function _dvsmRenderCompat(bodyId, compat) {
  const body = document.getElementById(bodyId);
  if (!body) return;
  if (!compat || !compat.length) {
    body.innerHTML = `<div class="stub-panel" style="min-height:40px">No checks available</div>`;
    return;
  }

  let html = "";
  let curFile = null;
  compat.forEach(c => {
    const fileKey = (c.source || "").split(/[\s[]/)[0];
    if (fileKey !== curFile) {
      if (curFile !== null) html += `</table>`;
      curFile = fileKey;
      html += `<span class="dvsm-sec-lbl">${_esc(c.source)}</span>` +
              `<table class="dvsm-compat-tbl">`;
    }
    const sub = c.fix || (c.status === "info" && c.value ? c.value : null);
    html += _compatRowHtml(c.key, c.enables, c.status, sub);
  });
  if (curFile !== null) html += `</table>`;
  body.innerHTML = html;
}

// ========================================================================
// SHARED: DVSM + STFU + M17
// ========================================================================
function _dvsmBadgeClass(status) {
  return {pass: "dpbadge-state-active",
          fail: "dpbadge-state-failed",
          warn: "dpbadge-warn",
          info: "dpbadge-info"}[status] || "dpbadge-info";
}

function _dvsmSetBadge(id, status, text) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = (text || status || "—").toUpperCase();
  el.className   = "dpbadge " + _dvsmBadgeClass(status);
}

function _copyTextSync(text) {
  const tmp = document.createElement("textarea");
  tmp.value = text;
  tmp.style.position = "fixed";
  tmp.style.top = "0";
  tmp.style.left = "0";
  tmp.style.opacity = "0";
  tmp.style.fontSize = "16px";
  document.body.appendChild(tmp);
  tmp.focus();
  tmp.select();
  tmp.setSelectionRange(0, text.length);
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  document.body.removeChild(tmp);
  return ok;
}

function dvsmCopy(btn, value) {
  const text = String(value || "");
  const orig = btn.dataset.origLabel || btn.textContent;
  btn.dataset.origLabel = orig;
  const short = orig.trim().length <= 2;
  const done = (ok) => {
    btn.textContent = ok ? (short ? "✓" : "✓ Copied") : (short ? "✗" : "Copy failed");
    btn.classList.toggle("copied", ok);
    if (!ok) toast("Copy failed: select the text and copy it by hand", "err");
    clearTimeout(btn._copyTimer);
    btn._copyTimer = setTimeout(() => { btn.textContent = orig; btn.classList.remove("copied"); }, 1400);
  };
  if (!text) { done(false); return; }
  if (_copyTextSync(text)) { done(true); return; }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(() => done(true), () => done(false));
    return;
  }
  done(false);
}

function dvsmCopyAttr(btn) { dvsmCopy(btn, btn.getAttribute("data-copyval") || ""); }

// ---- desktop-layout text copies (v6.13.67.7) ----
// Built from the data, never from the screen, so a phone and a desktop
// copy exactly the same text.
function _dtStamp(title) {
  return [title, "sysmon v__VERSION__ · " + new Date().toLocaleString(), ""];
}
function _dtTable(head, rows) {
  const all = [head].concat(rows.map(r => r.map(c => c == null || c === "" ? "-" : String(c))));
  const w = head.map((_, i) => Math.max(...all.map(r => String(r[i]).length)));
  return all.map(r => r.map((c, i) => i === r.length - 1 ? c : String(c).padEnd(w[i])).join("  ").trimEnd());
}
function dtCopy(btn, fn) {
  let text = "";
  try { text = fn(); } catch (e) { text = ""; }
  if (!String(text).trim()) { toast("Nothing to copy yet", "err"); return; }
  dvsmCopy(btn, text);
}
function _ptConflict(p) {
  const c = (window._portConflicts || {})[`${p.proto}:${p.port}`];
  return c ? "DUP " + c.map(x => `${x.process}(${x.pid})`).join(", ") : "OK";
}
function _ptRows(list) {
  return list.map(p => [p.port, p.proto, p.process || "-", p.pid || "-", p.addr || "0.0.0.0",
                        p.service ? p.service + ".service" : "-", _ptConflict(p), p.cmd || "-"]);
}
const _PT_HEAD = ["PORT", "PROTO", "PROCESS", "PID", "LISTEN", "SERVICE", "CONFLICT", "COMMAND"];
function ptCopy(btn, everything) {
  dtCopy(btn, () => {
    const list = everything ? _ptAll : _ptShown();
    const filt = everything ? "all" : (_ptProto === "both" ? "all" : _ptProto.toUpperCase());
    return _dtStamp(`Open ports (${filt}) - ${list.length} listening`)
      .concat(_dtTable(_PT_HEAD, _ptRows(list))).join("\n");
  });
}
function ptOneText(port, proto) {
  const list = _ptAll.filter(p => String(p.port) === String(port) && p.proto === proto);
  return _dtStamp(`Port ${port}/${proto}`).concat(_dtTable(_PT_HEAD, _ptRows(list))).join("\n");
}
function _svcRow(svc) {
  return [(svc.unit || "").replace(/\.service$/, ""), svc.state || "-",
          svc.enabled === true ? "enabled" : svc.enabled === false ? "disabled" : (svc.enabled || "-"),
          svc.owner || "-", svc.mode || "-"];
}
function svcText() {
  const scope = _s3Scope + (_s3Filter ? `, filter "${_s3Filter}"` : "");
  return _dtStamp(`Services (${scope}) - ${_s3Items.length}`)
    .concat(_dtTable(["UNIT", "STATE", "ENABLED", "OWNER", "PERMS"], _s3Items.map(_svcRow))).join("\n");
}
function ovText() {
  const out = _dtStamp("Overview");
  _ovGroups.forEach(g => {
    out.push("[" + g.group + "]");
    const rows = (g.services || []).map(svc => {
      const r = _svcRow(svc);
      const port = svc.nr > 0 ? "NR:" + svc.nr
                 : (svc.port && svc.port !== "-" ? `:${svc.port}/${svc.proto || ""}` : "-");
      return [r[0], r[1], r[3], r[4], port];
    });
    out.push(..._dtTable(["UNIT", "STATE", "OWNER", "PERMS", "PORT"], rows), "");
  });
  return out.join("\n").trimEnd();
}
function _yn(v) { return v === true ? "yes" : v === false ? "no" : "-"; }
function _hwHealth(label, o) {
  const x = o || {};
  return `  ${label}: ${x.ok === true ? "OK" : x.ok === false ? "FAIL" : "not run"}${x.detail ? " - " + x.detail : ""}`;
}
function hwText() {
  if (!_hwData) return "";
  const out = _dtStamp("Hardware");
  const d = _hwData;
  if (_healthData) {
    out.push("[Node health]");
    _healthData.forEach(c => {
      out.push(`  ${c.title}: ${c.status.toUpperCase()} -- ${c.headline}`);
      (c.rows || []).forEach(r => out.push(`    ${r[0]}: ${r[1]}`));
      if (c.note) out.push(`    ${c.note}`);
    });
    out.push("");
  }
  out.push("[AMBE device]");
  const am = d.ambe || [];
  if (!am.length) out.push("  none detected");
  am.forEach(a => {
    out.push(`  ${a.label || "-"}  ${a.vid || "?"}:${a.pid || "?"}  ${(a.dev_nodes || []).join(" ") || "no node"}` +
             `  ${a.ambe_known ? "AMBE" : "generic serial"}${a.udev_symlink ? "  -> " + a.udev_symlink : ""}`);
    const L = a.layers || {};
    out.push(_hwHealth("Kernel recognized", L.l1), _hwHealth("Serial port accessible", L.l2),
             _hwHealth("Process holding port", L.l3), _hwHealth("Chip responding", L.l4));
  });
  out.push("", "[Audio device]");
  const au = (d.audio || []).filter(a => a.is_usb);
  if (!au.length) out.push("  no USB audio devices");
  au.forEach(a => {
    out.push(`  ${a.card_name || "-"}  hw:${a.card_index},0  ${a.vid || "?"}:${a.pid || "?"}`);
    const c = a.checks || {};
    out.push(_hwHealth("Kernel recognized", c.c1), _hwHealth("Device free", c.c2),
             `  DVSwitch compatible: ${_yn(a.dvswitch_ok)}`);
  });
  const p = d.power;
  out.push("", "[Power & thermal]");
  if (!p) out.push("  no data");
  else {
    const t = p.throttle || {};
    out.push(`  Power health: ${t.available ? (t.pwr_status || "-") : "vcgencmd unavailable"}  bitmask ${t.raw || "-"}`);
    if (p.core_volts != null) out.push(`  Core voltage: ${Number(p.core_volts).toFixed(4)}V`);
    if (p.cpu_temp != null) out.push(`  SoC temp: ${p.cpu_temp}C`);
    if (t.available) {
      const f = [["UV now", t.uv_now], ["Freq cap now", t.freq_cap_now], ["Throttled now", t.throttled_now],
                 ["Temp now", t.temp_now], ["UV since boot", t.uv_ever], ["Freq cap since boot", t.freq_cap_ever],
                 ["Throttled since boot", t.throttled_ever], ["Temp since boot", t.temp_ever]];
      out.push("  Flags set: " + (f.filter(x => x[1]).map(x => x[0]).join(", ") || "none"));
    }
  }
  const v = d.video;
  out.push("", "[Video & GPU memory]");
  if (!v || !v.available) out.push("  " + ((v && v.message) || "no data"));
  else {
    const lv = v.live || {};
    out.push(`  Video driver: ${lv.vc4_loaded ? "vc4 loaded" : "vc4 not loaded"}` +
             `  HDMI: ${(lv.hdmi || []).map(c => c.name + " " + c.status).join(", ") || "none listed"}`);
    out.push(`  GPU memory: ${lv.gpu_mb != null ? lv.gpu_mb + " MB" : "-"}  CMA reserved: ${lv.cma_mb != null ? lv.cma_mb + " MB" : "-"}`);
    out.push(`  Headless option: ${v.video_off ? "on" : "off"}  Low GPU memory option: ${v.gpumem_low ? "on" : "off"}` +
             `${v.video_pending || v.gpumem_pending ? "  (reboot required)" : ""}`);
  }
  const g = _hwDiagData || {};
  out.push("", "[USB bus]");
  const u = g.lsusb || {};
  if (!u.available) out.push("  " + (u.error || "lsusb not available"));
  else { (u.flat || []).forEach(l => out.push("  " + l)); if (u.tree) out.push("", u.tree); }
  out.push("", "[asl-find-sound]");
  const f = g.asl_find_sound || {};
  out.push(f.installed ? (f.output || "(no output)") : "  " + (f.error || "not installed"));
  out.push("", "[ALSA cards]");
  const a = g.alsa || {};
  if (!a.available) out.push("  " + (a.error || "aplay not available"));
  else { out.push("Playback:", a.playback || "", "Capture:", a.capture || ""); }
  return out.join("\n").trimEnd();
}


function _compatRowHtml(key, enables, status, sub) {
  const bc = _dvsmBadgeClass(status);
  const bt = _esc((status || "—").toUpperCase());
  let html = `<tr>` +
    `<td class="dvsm-ct-key">${_esc(key)}</td>` +
    `<td class="dvsm-ct-enables">${_esc(enables)}</td>` +
    `<td class="dvsm-ct-badge"><span class="dpbadge ${bc}">${bt}</span></td>` +
    `</tr>`;
  if (sub) {
    html += `<tr class="dvsm-ct-fix-row">` +
            `<td colspan="3" class="dvsm-ct-fix">&#x21B3; ${_esc(sub)}</td>` +
            `</tr>`;
  }
  return html;
}

// ========================================================================
// SHARED: small helpers used by two or more tabs
// ========================================================================
function renderRegChecks(checks, overallStatus, ids) {
  const body   = document.getElementById(ids.body);
  const meta   = document.getElementById(ids.meta);
  const status = document.getElementById(ids.status);
  if (!body) return;

  if (status) {
    const s = overallStatus || "info";
    status.className   = "reg-card-status " + s;
    status.textContent = s.toUpperCase();
  }

  if (!Array.isArray(checks) || !checks.length) {
    body.innerHTML = '<div class="stub-panel" style="min-height:60px">No checks available</div>';
    if (meta) meta.textContent = "—";
    return;
  }
  if (meta) {
    const fails = checks.filter(c => c.status === "fail").length;
    const warns = checks.filter(c => c.status === "warn").length;
    meta.textContent = fails ? `${fails} issue${fails === 1 ? "" : "s"}`
                      : warns ? `${warns} warning${warns === 1 ? "" : "s"}`
                      : "all clear";
  }
  const cb = document.createElement("div");
  cb.className = "ast-checks";
  checks.forEach(c => {
    const crow = document.createElement("div");
    crow.className = "ast-check-row";

    const title = document.createElement("span");
    title.className   = "ast-check-title";
    title.textContent = c.title;

    const val = document.createElement("span");
    val.className   = "ast-check-value";
    val.textContent = c.value || "";

    const badge = document.createElement("span");
    if      (c.status === "pass") { badge.className = "ast-check-pass"; badge.textContent = "[PASS]"; }
    else if (c.status === "fail") { badge.className = "ast-check-fail"; badge.textContent = "[FAIL]"; }
    else if (c.status === "warn") { badge.className = "ast-check-warn"; badge.textContent = "[WARN]"; }
    else if (c.status === "info") { badge.className = "ast-check-info"; badge.textContent = "[INFO]"; }
    else                          { badge.className = "ast-check-none"; badge.textContent = "[NONE]"; }

    crow.appendChild(title);
    crow.appendChild(val);
    crow.appendChild(badge);
    cb.appendChild(crow);

    if (c.note) {
      const nrow = document.createElement("div");
      nrow.className = "ast-check-note";
      if (c.url) {
        const a = document.createElement("a");
        a.href   = c.url;
        a.target = "_blank";
        a.textContent = c.note;
        nrow.appendChild(a);
      } else {
        nrow.textContent = c.note;
      }
      cb.appendChild(nrow);
    }
  });
  body.innerHTML = "";
  body.appendChild(cb);
}

function phEl(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}

function phBadge(text, cls) { return phEl("span", "reg-card-status " + (cls || "info"), text); }

function phKV(rows) {
  const d = phEl("div", "ph-kv");
  rows.forEach(r => {
    if (r[1] === null || r[1] === undefined || r[1] === "") return;
    d.appendChild(phEl("div", "k", r[0]));
    const v = phEl("div", "v");
    if (r[1] instanceof Node) v.appendChild(r[1]); else v.textContent = String(r[1]);
    d.appendChild(v);
  });
  return d;
}

function _renderCompatTable(bodyId, compat) {
  const body = document.getElementById(bodyId);
  if (!body) return;
  if (!compat || !compat.length) {
    body.innerHTML = `<div class="stub-panel" style="min-height:40px">No checks available</div>`;
    return;
  }
  let html = `<table class="dvsm-compat-tbl">`;
  compat.forEach(c => { html += _compatRowHtml(c.key, c.enables, c.status, c.fix); });
  html += `</table>`;
  body.innerHTML = html;
}

function _renderInstallTable(bodyId, badgeId, inst, spec) {
  const allOk  = inst.binary_ok && inst.service_installed && inst.service_active;
  const anyOk  = inst.binary_ok || inst.service_installed;
  const status = allOk ? "pass" : anyOk ? "warn" : "fail";
  _dvsmSetBadge(badgeId, status);

  const body = document.getElementById(bodyId);
  if (!body) return;

  const row = (key, enables, ok, fixMsg) =>
    _compatRowHtml(key, enables, ok ? "pass" : (fixMsg ? "warn" : "fail"),
                   ok ? null : fixMsg);

  let html = `<table class="dvsm-compat-tbl">`;
  html += row(
    inst.binary_path || spec.binDefault,
    spec.binLabel,
    inst.binary_ok,
    inst.binary_ok ? null : spec.binFix
  );
  html += row(
    inst.service_path || `${spec.unit}.service`,
    "systemd unit installed",
    inst.service_installed,
    inst.service_installed ? null : spec.unitFix
  );
  html += row(
    "Service active",
    `systemctl is-active ${spec.unit}`,
    inst.service_active,
    (!inst.service_active && inst.service_installed)
      ? `systemctl start ${spec.unit}`
      : (!inst.service_active ? "Install service first" : null)
  );
  html += `</table>`;
  body.innerHTML = html;
}

function _renderSampleCode(bodyId, rawText, commentRe, kvRe) {
  const body = document.getElementById(bodyId);
  if (!body) return;

  const highlighted = rawText
    .split("\n")
    .map(line => {
      if (commentRe.test(line))
        return `<span style="color:#fff">${_esc(line)}</span>`;
      const secM = line.match(/^(\[.+?\])(.*)/);
      if (secM)
        return `<span class="stfu-ini-section">${_esc(secM[1])}</span>` +
               `<span style="color:#fff">${_esc(secM[2])}</span>`;
      const kvM = line.match(kvRe);
      if (kvM) {
        const valPart = kvM[3].includes("<")
          ? `<span class="stfu-ini-ph">${_esc(kvM[3])}</span>`
          : `<span style="color:var(--text-bright)">${_esc(kvM[3])}</span>`;
        return `<span class="stfu-ini-key">${_esc(kvM[1])}</span>` +
               `<span style="color:#fff">=</span>` + valPart;
      }
      return _esc(line);
    })
    .join("\n");

  body.innerHTML = `<pre class="stfu-code">${highlighted}</pre>`;
}

function _toggleReveal(eyeBtn, fid, revealed, secrets) {
  const el  = document.getElementById(fid);
  if (!el) return;
  const now = !revealed.get(fid);
  revealed.set(fid, now);
  if (now) {
    el.textContent = secrets.get(fid) || "(empty)";
    el.classList.remove("masked");
    eyeBtn.classList.add("revealed");
    eyeBtn.title = "Hide";
  } else {
    el.textContent = "●●●●●●●●";
    el.classList.add("masked");
    eyeBtn.classList.remove("revealed");
    eyeBtn.title = "Reveal";
  }
}

</script>

</body>
</html>"""

_SVC_LEGEND_HTML = (
    '<div class="dot-legend">'
    '<span class="dot-legend-item"><span class="dot dot-on"></span>Active</span>'
    '<span class="dot-legend-item"><span class="dot dot-warn"></span>Stopped</span>'
    '<span class="dot-legend-item"><span class="dot dot-fail"></span>Failed / Masked</span>'
    '<span class="dot-legend-item"><span class="dot dot-unknown"></span>Unknown</span>'
    '<span class="dot-legend-item"><span class="dot dot-off"></span>Not Installed</span>'
    '</div>'
)
_HTML_SRC   = (_HTML.replace("__VERSION__", VERSION)
                    .replace("__SVC_LEGEND__", _SVC_LEGEND_HTML))
_HTML_BYTES = _HTML_SRC.encode("utf-8")
_HTML_GZIP  = gzip.compress(_HTML_BYTES, compresslevel=6)

_AUTH_ACCOUNT        = "root"
_SESSION_TTL_SEC     = 12 * 3600
_LOGIN_MAX_ATTEMPTS  = 5
_LOGIN_WINDOW_SEC    = 5 * 60
_LOGIN_LOCKOUT_SEC   = 15 * 60
_SESSION_COOKIE_NAME = "asl_dvs_session"
_SHARED_AUTH_DIR     = Path("/run/asl_dvs")
_SHARED_AUTH_FILE    = _SHARED_AUTH_DIR / "auth_session.json"
_shared_auth_proc_lock = threading.Lock()

def _read_shadow_hash(account: str):
    try:
        with open("/etc/shadow", "r") as fh:
            for line in fh:
                parts = line.rstrip("\n").split(":")
                if len(parts) >= 2 and parts[0] == account:
                    return parts[1]
    except Exception as exc:
        log.warning("_read_shadow_hash: %s", exc)
    return None

_libcrypt_handle = None

def _crypt_verify(password: str, stored_hash: str) -> bool:
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
                lib.crypt.restype  = ctypes.c_char_p
                lib.crypt.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
                found = lib
                break
            except (OSError, AttributeError):
                continue
        _libcrypt_handle = found if found is not None else False
        if _libcrypt_handle is False:
            log.warning("_crypt_verify: no usable libcrypt found on this system")
    if _libcrypt_handle is False:
        return False
    try:
        result = _libcrypt_handle.crypt(password.encode("utf-8", "surrogateescape"),
                                         stored_hash.encode("utf-8", "surrogateescape"))
    except Exception as exc:
        log.warning("_crypt_verify: crypt(3) call failed: %s", exc)
        return False
    if result is None:
        return False
    return hmac.compare_digest(result.decode("utf-8", "surrogateescape"), stored_hash)

def _verify_root_password(password: str) -> bool:
    if not password:
        return False
    try:
        import pam as _pam_mod
        return bool(_pam_mod.pam().authenticate(_AUTH_ACCOUNT, password, service="login"))
    except ImportError:
        pass
    except Exception as exc:
        log.warning("_verify_root_password: PAM check errored, trying shadow fallback: %s", exc)
    try:
        stored = _read_shadow_hash(_AUTH_ACCOUNT)
        if not stored or stored[0] in ("!", "*"):
            return False
        return _crypt_verify(password, stored)
    except Exception as exc:
        log.warning("_verify_root_password: shadow fallback failed: %s", exc)
        return False

def _shared_auth_mutate(mutator) -> dict:
    try:
        _SHARED_AUTH_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(_SHARED_AUTH_DIR, 0o700)
        except Exception:
            pass
        with _shared_auth_proc_lock:
            fd = os.open(str(_SHARED_AUTH_FILE), os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                try:
                    chunks = []
                    while True:
                        chunk = os.read(fd, 65536)
                        if not chunk:
                            break
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    try:
                        data = json.loads(raw) if raw else {}
                    except (json.JSONDecodeError, ValueError):
                        data = {}
                    if not isinstance(data, dict):
                        data = {}
                    data.setdefault("sessions", {})
                    data.setdefault("failures", {})
                    data.setdefault("locked",   {})
                    mutator(data)
                    out = json.dumps(data).encode()
                    os.lseek(fd, 0, os.SEEK_SET)
                    os.ftruncate(fd, 0)
                    os.write(fd, out)
                    os.fsync(fd)
                    return data
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
    except Exception as exc:
        log.warning("_shared_auth_mutate: %s", exc)
        data = {"sessions": {}, "failures": {}, "locked": {}}
        try:
            mutator(data)
        except Exception:
            pass
        return data

def _issue_session() -> str:
    token = secrets.token_hex(32)
    now   = time.time()
    def _mut(d):
        d["sessions"] = {t: exp for t, exp in d["sessions"].items() if exp > now}
        d["sessions"][token] = now + _SESSION_TTL_SEC
    _shared_auth_mutate(_mut)
    return token

def _check_session(token: str) -> bool:
    if not token:
        return False
    now = time.time()
    box = {"ok": False}
    def _mut(d):
        exp = d["sessions"].get(token)
        if exp is None or exp <= now:
            d["sessions"].pop(token, None)
            return
        d["sessions"][token] = now + _SESSION_TTL_SEC
        box["ok"] = True
    _shared_auth_mutate(_mut)
    return box["ok"]

def _revoke_session(token: str) -> None:
    def _mut(d):
        d["sessions"].pop(token, None)
    _shared_auth_mutate(_mut)

def _login_is_locked(ip: str):
    now = time.time()
    box = {"until": None}
    def _mut(d):
        until = d["locked"].get(ip)
        if until is None:
            return
        if now >= until:
            d["locked"].pop(ip, None)
            d["failures"].pop(ip, None)
            return
        box["until"] = until
    _shared_auth_mutate(_mut)
    return box["until"]

def _login_record_failure(ip: str) -> None:
    now = time.time()
    def _mut(d):
        hits = [t for t in d["failures"].get(ip, []) if now - t < _LOGIN_WINDOW_SEC]
        hits.append(now)
        d["failures"][ip] = hits
        if len(hits) >= _LOGIN_MAX_ATTEMPTS:
            d["locked"][ip] = now + _LOGIN_LOCKOUT_SEC
            log.warning("login: IP %s locked out for %ds after %d failed attempts",
                        ip, _LOGIN_LOCKOUT_SEC, len(hits))
    _shared_auth_mutate(_mut)

def _login_record_success(ip: str) -> None:
    def _mut(d):
        d["failures"].pop(ip, None)
        d["locked"].pop(ip, None)
    _shared_auth_mutate(_mut)

def _session_cookie_header(token: str, max_age: int) -> str:
    return f"{_SESSION_COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"

def _clear_session_cookie_header() -> str:
    return f"{_SESSION_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"

_PUBLIC_GET_PATHS  = {"/", "/api/ping", "/healthz"}

class _EarlyReturn(Exception):
    pass

_MAX_CONCURRENT_CONNS = 24
_MAX_CONNS_PER_IP = 12

class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._conn_sem = threading.BoundedSemaphore(_MAX_CONCURRENT_CONNS)
        self._per_ip_lock = threading.Lock()
        self._per_ip: dict = {}
        self._refused_logged_at = 0.0

    def _refused(self, why: str, client_address) -> None:
        now = time.monotonic()
        if now - self._refused_logged_at >= 60:
            self._refused_logged_at = now
            _log(f"WARN — {why}; refusing {client_address[0]} (logged at most once a minute)")

    def _release_ip(self, ip: str) -> None:
        with self._per_ip_lock:
            n = self._per_ip.get(ip, 1) - 1
            if n <= 0:
                self._per_ip.pop(ip, None)
            else:
                self._per_ip[ip] = n

    def verify_request(self, request, client_address) -> bool:
        ip = client_address[0]
        with self._per_ip_lock:
            if self._per_ip.get(ip, 0) >= _MAX_CONNS_PER_IP:
                self._refused(f"{_MAX_CONNS_PER_IP} connections already open from one address", client_address)
                return False
            self._per_ip[ip] = self._per_ip.get(ip, 0) + 1
        if not self._conn_sem.acquire(blocking=False):
            self._release_ip(ip)
            self._refused(f"{_MAX_CONCURRENT_CONNS} connections already open", client_address)
            return False
        return True

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._conn_sem.release()
            self._release_ip(client_address[0])

    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            return
        _log(f"WARN — unhandled server error from {client_address}: {exc}")

class Handler(BaseHTTPRequestHandler):

    timeout = 20

    def log_message(self, fmt, *args):
        pass

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(self.timeout)

    def _accepts_gzip(self) -> bool:
        return "gzip" in self.headers.get("Accept-Encoding", "")

    def send_json(self, data: dict, status: int = 200, extra_headers: dict = None) -> None:
        raw = json.dumps(data, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type",          "application/json")
        self.send_header("Cache-Control",          "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        if self._accepts_gzip() and len(raw) > 256:
            body = gzip.compress(raw, compresslevel=1)
            self.send_header("Content-Encoding", "gzip")
        else:
            body = raw
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_ping(self) -> None:
        raw = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type",                "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control",               "no-store")
        self.send_header("Content-Length",              str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_html(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type",          "text/html; charset=utf-8")
        self.send_header("Cache-Control",          "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if self._accepts_gzip():
            body = _HTML_GZIP
            self.send_header("Content-Encoding", "gzip")
        else:
            body = _HTML_BYTES
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        if length > 524_288:
            self.send_json({"ok": False, "message": "Request too large"}, 413)
            raise _EarlyReturn()
        return self.rfile.read(length)

    def _client_ip(self) -> str:
        try:
            return self.client_address[0]
        except Exception:
            return "unknown"

    def _session_token(self) -> str:
        header = self.headers.get("Cookie", "")
        for part in header.split(";"):
            part = part.strip()
            if part.startswith(_SESSION_COOKIE_NAME + "="):
                return part[len(_SESSION_COOKIE_NAME) + 1:]
        return ""

    def _require_auth(self) -> bool:
        if _check_session(self._session_token()):
            return True
        try:
            self.send_json({"ok": False, "message": "Authentication required"}, 401)
        except (BrokenPipeError, ConnectionResetError):
            pass
        return False

    def _require_json_content_type(self) -> bool:
        ctype = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if ctype != "application/json":
            try:
                self.send_json({"ok": False, "message": "Content-Type must be application/json"}, 415)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return False
        return True

    def _do_login(self) -> None:
        ip = self._client_ip()
        locked_until = _login_is_locked(ip)
        if locked_until is not None:
            wait = max(0, int(locked_until - time.time()))
            self.send_json({"ok": False,
                             "message": f"Too many failed attempts — try again in {wait}s"}, 429)
            return
        if not self._require_json_content_type():
            return
        try:
            data = json.loads(self._read_body())
        except _EarlyReturn:
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self.send_json({"ok": False, "message": f"Bad request: {exc}"}, 400)
            return
        password = str(data.get("password", "")) if isinstance(data, dict) else ""
        if _verify_root_password(password):
            _login_record_success(ip)
            token = _issue_session()
            _log(f"login: successful root-password login from {ip}")
            self.send_json({"ok": True}, 200,
                            extra_headers={"Set-Cookie": _session_cookie_header(token, _SESSION_TTL_SEC)})
        else:
            _login_record_failure(ip)
            _log(f"login: failed attempt from {ip}", stderr=True)
            self.send_json({"ok": False, "message": "Incorrect password"}, 401)

    def _do_logout(self) -> None:
        _revoke_session(self._session_token())
        self.send_json({"ok": True, "message": "Logged out"}, 200,
                        extra_headers={"Set-Cookie": _clear_session_cookie_header()})

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        handler = _GET_ROUTES.get(path)
        if not handler:
            self.send_response(404)
            self.end_headers()
            return
        if path not in _PUBLIC_GET_PATHS and not self._require_auth():
            return
        try:
            handler(self)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            _log(f"WARN — do_GET {path}: {exc}")
            try:
                self.send_json({"ok": False, "message": "Internal error"}, 500)
            except Exception:
                pass

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/login":
            try:
                self._do_login()
            except _EarlyReturn:
                pass
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                _log(f"WARN — do_POST /api/login: {exc}")
                try:
                    self.send_json({"ok": False, "message": "Internal error"}, 500)
                except Exception:
                    pass
            return
        if path == "/api/logout":
            try:
                if not self._require_auth():
                    return
                self._do_logout()
            except _EarlyReturn:
                pass
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                _log(f"WARN — do_POST /api/logout: {exc}")
                try:
                    self.send_json({"ok": False, "message": "Internal error"}, 500)
                except Exception:
                    pass
            return
        handler = _POST_ROUTES.get(path)
        if not handler:
            self.send_response(404)
            self.end_headers()
            return
        if not self._require_auth():
            return
        if not self._require_json_content_type():
            return
        try:
            raw  = self._read_body()
            data = json.loads(raw) if raw else {}
        except _EarlyReturn:
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self.send_json({"ok": False, "message": f"Bad JSON: {exc}"}, 400)
            return
        try:
            handler(self, data)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            _log(f"WARN — do_POST {path}: {exc}")
            try:
                self.send_json({"ok": False, "message": "Internal error"}, 500)
            except Exception:
                pass
_NET_JOB_LINE_KEEP   = 300

_net_job_lock = threading.Lock()
_net_job: dict = {
    "status": "idle", "action": "", "label": "", "cmd": "", "lines": [],
    "success": None, "returncode": None, "started_at": 0.0, "finished_at": 0.0,
    "finished_key": "",
}

def net_job_status() -> dict:
    with _net_job_lock:
        j = dict(_net_job)
    j["lines"] = j["lines"][-_NET_JOB_LINE_KEEP:]
    if j["status"] == "running" and j["started_at"]:
        j["elapsed"] = round(time.monotonic() - j["started_at"])
    elif j["finished_at"] and j["started_at"]:
        j["elapsed"] = round(j["finished_at"] - j["started_at"])
    else:
        j["elapsed"] = 0
    return {"ok": True, **j}

def _route_net_job_get(h: "Handler") -> None:
    h.send_json(net_job_status())

def _route_html(h: Handler) -> None:
    h.send_html()

def _route_status(h: Handler) -> None:
    snap   = get_state_snapshot()
    mem    = snap.get("memory") or {}
    load   = snap.get("load")   or {}
    cfg    = _cfg
    uptime_s = int(time.monotonic() - snap.get("start_time", 0))

    h.send_json({
        "ok":            True,
        "version":       VERSION,
        "hostname":      snap.get("hostname", ""),
        "kernel":        snap.get("kernel",   ""),
        "uptime":        snap.get("uptime",   ""),
        "uptime_s":      uptime_s,
        "load":          load,
        "memory":        mem,
        "swap":          snap.get("swap") or {},
        "cpu_temp":      snap.get("cpu_temp"),
        "pi_voltage":    snap.get("pi_voltage"),
        "throttle_state":snap.get("throttle_state"),
        "disk":          snap.get("disk") or {},
        "sd_health":     snap.get("sd_health"),
        "proc_count":    snap.get("proc_count"),
        "callsign":      cfg.get("identity", "callsign", fallback=""),
        "node":          cfg.get("identity", "node",     fallback=""),
        "label":         cfg.get("identity", "label",    fallback=""),
        "quick_tests":    snap.get("quick_tests", {}),
        "port_conflicts": snap.get("port_conflicts", {}),
        "needs_restart":  snap.get("needs_restart", False),
        "wifimon_shutdown": snap.get("wifimon_shutdown") or {"active": False},
        "reg_summary":    _reg_summary_for_page(),
    })

def _route_log(h: Handler) -> None:
    qs    = parse_qs(urlparse(h.path).query)
    try:
        since = int(qs.get("since", ["0"])[0])
    except ValueError:
        since = 0
    with _log_lock:
        buf   = list(_log_buf)
        total = _log_idx
    oldest = total - len(buf)
    start  = max(0, since - oldest)
    h.send_json({
        "lines":      buf[start:],
        "next_index": total,
    })

def _power_action(h: Handler, what: str, message: str, cmd: str) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "root required"}); return
    _log(f"{what} requested", stderr=True)
    h.send_json({"ok": True, "message": message})
    threading.Thread(
        target=lambda: (time.sleep(1), os.system(cmd)),
        daemon=True,
    ).start()

def _route_reboot(h: Handler, data: dict) -> None:
    _power_action(h, "REBOOT", "Rebooting…", "reboot")

def _route_shutdown(h: Handler, data: dict) -> None:
    _power_action(h, "SHUTDOWN", "Shutting down…", "shutdown -h now")

def _route_abinfo(h: Handler) -> None:
    data = _read_abinfo()
    if not data:
        h.send_json({"ok": False, "running": False,
                     "mode": "", "last_tune": "", "mute": "",
                     "rx_port": "", "tx_port": "", "version": "",
                     "callsign": "", "tg": "", "ts": ""})
        return
    tlv     = data.get("tlv",     {})
    digital = data.get("digital", {})
    ab_meta = data.get("ab",      {})
    h.send_json({
        "ok":        True,
        "running":   True,
        "mode":      tlv.get("ambe_mode",  ""),
        "last_tune": data.get("last_tune", ""),
        "mute":      data.get("mute",      ""),
        "rx_port":   tlv.get("rx_port",    ""),
        "tx_port":   tlv.get("tx_port",    ""),
        "version":   ab_meta.get("version",""),
        "callsign":  digital.get("call",   ""),
        "tg":        digital.get("tg",     ""),
        "ts":        digital.get("ts",     ""),
    })

_REGISTER_LOOSE_RE = re.compile(r'^\s*register\s*[=:]', re.IGNORECASE)

_PLACEHOLDER_NODES = frozenset({"1999", "1998"})

_PRIVATE_NODE_MAX  = 2000

_STATPOST_URL_RE   = re.compile(
    r'^https?://stats\.allstarlink\.org/uhandler\b', re.IGNORECASE
)

_NODE_LOOKUP_VALUES = frozenset({"dns", "file", "both"})

_DEFAULT_DNS_DOMAIN = "nodes.allstarlink.org"

def _scan_register_lines(content: str) -> dict:

    entries:   list = []
    malformed: list = []
    passwords: dict = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(";") or stripped.startswith("#"):
            continue
        m = _REGISTER_RE.match(line)
        if m:
            node, pwd = m.group(1).strip(), m.group(2).strip()
            entries.append((node, bool(pwd)))
            if pwd:
                passwords[node] = pwd
            continue
        if _REGISTER_LOOSE_RE.match(line):
            malformed.append(stripped)
    return {"entries": entries, "malformed": malformed, "passwords": passwords}

def _reg_scan_allmon3(content: str) -> "dict[str, dict]":

    nodes: "dict[str, dict]" = {}
    section = ""
    kv: "dict[str, str]" = {}

    def _flush(sec: str, kv: dict) -> None:
        if sec and sec.isdigit():
            nodes[sec] = dict(kv)

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        sm = _DVS_SECTION_RE.match(raw_line)
        if sm:
            _flush(section, kv)
            section, kv = sm.group(1).strip(), {}
            continue
        m = _DVS_KV_RE.match(raw_line)
        if m:
            kv[m.group(1)] = m.group(2).strip()
    _flush(section, kv)
    return nodes

def _reg_scan_rpt_conf(content: str) -> "tuple[dict, dict]":

    sections, node_sects = _rpt_scan(content)
    general_kv = next((kv for s, kv in sections.items()
                        if s.strip().lower() == "general"), {})
    return node_sects, general_kv

_REG_STATUS_RANK = {"fail": 3, "warn": 2, "info": 1, "none": 1, "pass": 0}

def _reg_overall_status(checks: list) -> str:
    if not checks:
        return "info"
    worst = max(checks, key=lambda c: _REG_STATUS_RANK.get(c.get("status"), 1))
    return worst.get("status") or "info"

def _reg_load_context() -> dict:
    http_content, http_err = read_asterisk_file("rpt_http_registrations.conf")
    iax_content,  iax_err  = read_asterisk_file("iax.conf")
    rpt_content,  rpt_err  = read_asterisk_file("rpt.conf")

    empty_scan = {"entries": [], "malformed": [], "passwords": {}}
    http_scan = _scan_register_lines(http_content) if not http_err else dict(empty_scan)
    iax_scan  = _scan_register_lines(iax_content)  if not iax_err  else dict(empty_scan)

    return {
        "http_content": http_content, "http_err": http_err, "http_scan": http_scan,
        "iax_content":  iax_content,  "iax_err":  iax_err,  "iax_scan":  iax_scan,
        "rpt_content":  rpt_content,  "rpt_err":  rpt_err,
    }

def _reg_node_password_checks(entries: list, label: str) -> list:
    checks = []
    for node, has_pwd in entries:
        node_ok = node.isdigit() and len(node) >= 4
        checks.append({
            "title":  f"{label} Node {node}",
            "value":  node if node_ok else "invalid",
            "status": "pass" if node_ok else "fail",
            "note":   None, "url": None,
        })
        checks.append({
            "title":  "Password", "value": None,
            "status": "pass" if has_pwd else "fail",
            "note":   _ASL_NOTE, "url": _ASL_URL,
        })
    return checks

def _reg_dual_check(http_active: bool, iax_active: bool) -> list:
    if http_active and iax_active:
        return [{
            "title":  "Dual registration",
            "value":  "HTTP and IAX both active",
            "status": "warn",
            "note":   ("Don't register with both — wastes server load for "
                       "no gain. Pick one, comment out the other."),
            "url":    "https://allstarlink.github.io/adv-topics/httpreg/",
        }]
    return [{
        "title":  "Dual registration",
        "value":  "single protocol only",
        "status": "pass",
        "note":   None, "url": None,
    }]

def _reg_syntax_checks(scan: dict, label: str) -> list:
    malformed = scan["malformed"]
    if malformed:
        return [{
            "title":  f"{label} register line syntax",
            "value":  malformed[0][:60],
            "status": "fail",
            "note":   ("Looks like a register line but doesn't match the "
                       "required register=> node:password@host syntax "
                       "(missing arrow is a common copy/paste mistake)."),
            "url":    None,
        }]
    return [{
        "title":  f"{label} register line syntax",
        "value":  "no malformed lines",
        "status": "pass",
        "note":   None, "url": None,
    }]

def _reg_placeholder_check(entries: list, label: str) -> list:
    if not entries:
        return []
    hits = [n for n, _ in entries if n in _PLACEHOLDER_NODES]
    if hits:
        return [{
            "title":  f"{label} placeholder node number",
            "value":  hits[0],
            "status": "fail",
            "note":   "Template default left unchanged — set your real assigned node number.",
            "url":    None,
        }]
    return [{
        "title":  f"{label} placeholder node number",
        "value":  "none found",
        "status": "pass",
        "note":   None, "url": None,
    }]

def _reg_module_checks(http_active: bool, iax_active: bool) -> list:
    if not http_active and not iax_active:
        return []
    http_mod = module_state("res_rpt_http_registrations.so")
    if http_active and http_mod == "noload":
        return [{
            "title":  "res_rpt_http_registrations.so",
            "value":  "noload",
            "status": "fail",
            "note":   "HTTP registration is configured but the module is set to noload in modules.conf.",
            "url":    None,
        }]
    if http_active:
        return [{
            "title":  "res_rpt_http_registrations.so",
            "value":  http_mod,
            "status": "pass" if http_mod in ("load", "require", "blank") else "warn",
            "note":   None, "url": None,
        }]
    if iax_active and http_mod in ("load", "require"):
        return [{
            "title":  "res_rpt_http_registrations.so",
            "value":  http_mod,
            "status": "warn",
            "note":   "Only IAX registration is configured, but the HTTP registration module is still loaded.",
            "url":    None,
        }]
    return [{
        "title":  "res_rpt_http_registrations.so",
        "value":  http_mod,
        "status": "pass",
        "note":   None, "url": None,
    }]

def _reg_node_coverage_checks(node_sects: dict, registered_nodes: set) -> list:
    checks = []
    for nid in sorted(node_sects.keys(), key=int):
        is_private = nid.isdigit() and int(nid) < _PRIVATE_NODE_MAX
        if is_private:
            checks.append({
                "title":  f"rpt.conf node {nid}",
                "value":  "private node — registration not required",
                "status": "pass",
                "note":   None, "url": None,
            })
        elif registered_nodes and nid not in registered_nodes:
            checks.append({
                "title":  f"rpt.conf node {nid}",
                "value":  "no matching registration entry",
                "status": "warn",
                "note":   ("Node exists in rpt.conf but isn't in either registration "
                           "file — check for a typo'd node number."),
                "url":    None,
            })
        else:
            checks.append({
                "title":  f"rpt.conf node {nid}",
                "value":  "has matching registration entry",
                "status": "pass",
                "note":   None, "url": None,
            })
    return checks

def _reg_lookup_settings_checks(general_kv: dict) -> list:
    checks = []
    method = general_kv.get("node_lookup_method", "").strip().lower()
    if method:
        checks.append({
            "title":  "node_lookup_method",
            "value":  method,
            "status": "pass" if method in _NODE_LOOKUP_VALUES else "warn",
            "note":   (None if method in _NODE_LOOKUP_VALUES
                       else f"Expected one of {', '.join(sorted(_NODE_LOOKUP_VALUES))}."),
            "url":    None,
        })
    domain = general_kv.get("dns_node_domain", "").strip()
    if domain and domain != _DEFAULT_DNS_DOMAIN:
        checks.append({
            "title":  "dns_node_domain",
            "value":  domain,
            "status": "info",
            "note":   f"Overridden from the default ({_DEFAULT_DNS_DOMAIN}) — confirm this is intentional.",
            "url":    None,
        })
    return checks

def _reg_statpost_checks(node_sects: dict, http_entries: list) -> list:
    checks = []
    for nid in sorted(node_sects.keys(), key=int):
        kv = node_sects[nid]
        statpost = kv.get("statpost_url", "").strip()
        if not statpost:
            continue
        url_ok = bool(_STATPOST_URL_RE.match(statpost))
        checks.append({
            "title":  f"statpost {nid}",
            "value":  statpost if url_ok else "unexpected URL",
            "status": "pass" if url_ok else "warn",
            "note":   None, "url": None,
        })
        has_reg_entry = any(n == nid and pwd for n, pwd in http_entries)
        checks.append({
            "title":  f"statpost {nid} credential",
            "value":  ("matches HTTP registration password" if has_reg_entry
                       else "no matching HTTP registration password"),
            "status": "pass" if has_reg_entry else "warn",
            "note":   (None if has_reg_entry else
                       ("statpost can 401 even on an otherwise healthy node if this "
                        "node/password pair drifts from rpt_http_registrations.conf — "
                        "this doesn't block registration itself.")),
            "url":    None,
        })
    return checks

def _reg_ami_checks(http_passwords: dict) -> list:
    checks = []

    allmon3_path = _ALLMON3_DIR / "allmon3.ini"
    allmon3_content, allmon3_err = read_path_file(allmon3_path) if allmon3_path.is_file() \
        else ("", f"File not found: {allmon3_path}")
    manager_content, manager_err = read_asterisk_file("manager.conf")

    if allmon3_err or manager_err:
        return checks

    allmon3_nodes = _reg_scan_allmon3(allmon3_content)
    manager_users = {s: kv for s, kv in _parse_sections(manager_content).items()
                      if s.strip().lower() != "general"}

    for nid in sorted(allmon3_nodes.keys(), key=lambda n: (not n.isdigit(), n)):
        am_user = allmon3_nodes[nid].get("user", "").strip()
        am_pass = allmon3_nodes[nid].get("pass", "").strip()
        if not am_user:
            continue

        mgr_kv = next((kv for s, kv in manager_users.items() if s.strip() == am_user), None)
        if mgr_kv is None:
            checks.append({
                "title":  f"AMI user [{nid}]",
                "value":  f"'{am_user}' not found in manager.conf",
                "status": "warn",
                "note":   "Allmon3 will fail to connect locally even though AllStarLink registration can still succeed.",
                "url":    None,
            })
        else:
            checks.append({
                "title":  f"AMI user [{nid}]",
                "value":  f"'{am_user}' found in manager.conf",
                "status": "pass",
                "note":   None, "url": None,
            })
            mgr_secret = mgr_kv.get("secret", "").strip()
            if am_pass and mgr_secret:
                if am_pass != mgr_secret:
                    checks.append({
                        "title":  f"AMI credential [{nid}]",
                        "value":  "allmon3.ini password != manager.conf secret",
                        "status": "warn",
                        "note":   f"[{am_user}] secret in manager.conf has drifted from the password in allmon3.ini's [{nid}] stanza.",
                        "url":    None,
                    })
                else:
                    checks.append({
                        "title":  f"AMI credential [{nid}]",
                        "value":  "allmon3.ini password matches manager.conf secret",
                        "status": "pass",
                        "note":   None, "url": None,
                    })

        reg_pwd = http_passwords.get(nid)
        if reg_pwd and am_pass:
            checks.append({
                "title":  f"Registration vs AMI password [{nid}]",
                "value":  "match" if reg_pwd == am_pass else "differ",
                "status": "pass" if reg_pwd == am_pass else "info",
                "note":   (None if reg_pwd == am_pass else
                           "AllStarLink registration and local AMI access are separate credentials — this is only worth a look if you intended them to match."),
                "url":    None,
            })
    return checks

_REG_LIVE_UNREG_NOTE = {
    "HTTP": ("Config says this node should be registered but the live "
             "state disagrees — check for a NAT/carrier issue (e.g. a "
             "hotspot connection that intercepts and redirects HTTP "
             "traffic) or a blocked outbound HTTPS path."),
    "IAX": ("Config says this node should be registered but the live "
            "state disagrees — check for a NAT/carrier issue or a "
            "blocked outbound UDP/4569 path (IAX2)."),
}

def _reg_live_checks(entries: list, label: str) -> list:
    checks = []
    snap = get_state_snapshot()
    reg_live = snap.get("reg_live")
    sm = snap.get("reg_summary")
    for_txt = (f" (for {_reg_age_text(time.time() - sm['since'])})"
               if sm and sm.get("state") != "ok" else "")
    if reg_live is None:
        checks.append({
            "title":  "Live registration state",
            "value":  "not yet polled",
            "status": "info",
            "note":   "First background poll hasn't run yet — refresh in a moment.",
            "url":    None,
        })
        return checks
    if not reg_live.get("ok"):
        checks.append({
            "title":  "Live registration state",
            "value":  (reg_live.get("error") or "unavailable") + for_txt,
            "status": "warn",
            "note":   "Couldn't reach the Asterisk CLI — the checks above are config-only until this clears.",
            "url":    None,
        })
        return checks

    live_nodes = reg_live.get("nodes", {})
    perceived = reg_live.get("perceived", {})
    configured_nodes = {n for n, _ in entries}
    for nid in sorted(configured_nodes, key=str):
        live_state = live_nodes.get(nid, "not shown")
        if live_state == "registered":
            checks.append({
                "title":  f"Live registration [{nid}]",
                "value":  "registered", "status": "pass",
                "note":   None, "url": None,
            })
            if perceived.get(nid):
                path = _reg_addr_path(perceived[nid])
                checks.append({
                    "title":  f"Registered as [{nid}]",
                    "value":  perceived[nid], "status": "pass",
                    "note":   ("The address and port the AllStarLink server sees this node at"
                               + (f": {path}." if path else ".")),
                    "url":    None,
                })
        elif live_state == "unregistered":
            checks.append({
                "title":  f"Live registration [{nid}]",
                "value":  "not registered" + for_txt,
                "status": "fail",
                "note":   _REG_LIVE_UNREG_NOTE.get(label, _REG_LIVE_UNREG_NOTE["HTTP"]),
                "url":    None,
            })
        else:
            checks.append({
                "title":  f"Live registration [{nid}]",
                "value":  live_state + for_txt,
                "status": "warn",
                "note":   ("Node is configured but didn't show up clearly in "
                           "`rpt show registrations` output — worth a manual look."),
                "url":    None,
            })
    return checks

def get_http_reg_status(ctx: dict = None) -> dict:
    ctx = ctx or _reg_load_context()
    checks: list = []

    http_scan, iax_scan = ctx["http_scan"], ctx["iax_scan"]
    http_entries, iax_entries = http_scan["entries"], iax_scan["entries"]
    http_active, iax_active = bool(http_entries), bool(iax_entries)

    if ctx["http_err"]:
        checks.append({
            "title": "rpt_http_registrations.conf", "value": ctx["http_err"],
            "status": "fail", "note": None, "url": None,
        })
    elif not http_active:
        checks.append({
            "title": "HTTP registration", "value": "not configured",
            "status": "fail", "note": None, "url": None,
        })
    else:
        checks.extend(_reg_node_password_checks(http_entries, "HTTP"))

    if http_active or iax_active:
        checks.extend(_reg_dual_check(http_active, iax_active))

    checks.extend(_reg_syntax_checks(http_scan, "HTTP"))
    checks.extend(_reg_placeholder_check(http_entries, "HTTP"))
    checks.extend(_reg_module_checks(http_active, iax_active))

    if ctx["rpt_err"]:
        checks.append({
            "title": "rpt.conf", "value": ctx["rpt_err"],
            "status": "fail", "note": None, "url": None,
        })
    else:
        node_sects, general_kv = _reg_scan_rpt_conf(ctx["rpt_content"])
        registered_nodes = {n for n, _ in (http_entries + iax_entries)}
        checks.extend(_reg_node_coverage_checks(node_sects, registered_nodes))
        checks.extend(_reg_lookup_settings_checks(general_kv))
        checks.extend(_reg_statpost_checks(node_sects, http_entries))
        checks.extend(_reg_ami_checks(http_scan["passwords"]))

    checks.extend(_reg_live_checks(http_entries, "HTTP"))

    if not checks:
        checks.append({
            "title": "HTTP Registration", "value": "nothing to check",
            "status": "info", "note": None, "url": None,
        })

    return {"ok": True, "checks": checks, "status": _reg_overall_status(checks)}

def get_iax_reg_status(ctx: dict = None) -> dict:
    ctx = ctx or _reg_load_context()
    checks: list = []

    http_scan, iax_scan = ctx["http_scan"], ctx["iax_scan"]
    http_entries, iax_entries = http_scan["entries"], iax_scan["entries"]
    http_active, iax_active = bool(http_entries), bool(iax_entries)

    if ctx["iax_err"]:
        checks.append({
            "title": "iax.conf", "value": ctx["iax_err"],
            "status": "fail", "note": None, "url": None,
        })
    elif not iax_active:
        checks.append({
            "title": "IAX registration", "value": "not configured",
            "status": "fail", "note": None, "url": None,
        })
    else:
        checks.extend(_reg_node_password_checks(iax_entries, "IAX"))

    if http_active or iax_active:
        checks.extend(_reg_dual_check(http_active, iax_active))

    checks.extend(_reg_syntax_checks(iax_scan, "IAX"))
    checks.extend(_reg_placeholder_check(iax_entries, "IAX"))

    if ctx["rpt_err"]:
        checks.append({
            "title": "rpt.conf", "value": ctx["rpt_err"],
            "status": "fail", "note": None, "url": None,
        })
    else:
        node_sects, general_kv = _reg_scan_rpt_conf(ctx["rpt_content"])
        registered_nodes = {n for n, _ in (http_entries + iax_entries)}
        checks.extend(_reg_node_coverage_checks(node_sects, registered_nodes))
        checks.extend(_reg_lookup_settings_checks(general_kv))

    checks.extend(_reg_live_checks(iax_entries, "IAX"))

    if not checks:
        checks.append({
            "title": "IAX Registration", "value": "nothing to check",
            "status": "info", "note": None, "url": None,
        })

    return {"ok": True, "checks": checks, "status": _reg_overall_status(checks)}

def _route_reg_http_get(h: Handler) -> None:
    h.send_json(get_http_reg_status())

def _route_reg_iax_get(h: Handler) -> None:
    h.send_json(get_iax_reg_status())

def _reg_age_text(sec: float) -> str:
    sec = max(0, int(sec))
    if sec < 60:
        return f"{sec} s"
    if sec < 3600:
        return f"{sec // 60} min"
    return f"{sec // 3600} h {sec % 3600 // 60:02d} min"

def _reg_http_configured() -> bool:
    content, err = read_asterisk_file("rpt_http_registrations.conf")
    return not err and bool(_scan_register_lines(content)["entries"])

def _reg_live_summary(rl: dict, prev: "dict | None") -> dict:
    nodes = dict(rl.get("nodes") or {})
    if not rl.get("ok"):
        state = "down"
    elif not nodes:
        state = "wait" if _reg_http_configured() else "none"
    elif "unregistered" in nodes.values():
        state = "fail"
    elif all(v == "registered" for v in nodes.values()):
        state = "ok"
    else:
        state = "wait"
    now = time.time()
    since = prev["since"] if prev and prev.get("state") == state else now
    return {"state": state, "since": since, "checked": now,
            "nodes": nodes, "perceived": dict(rl.get("perceived") or {}), "error": rl.get("error")}

def _reg_summary_for_page() -> "dict | None":
    sm = get_state_snapshot().get("reg_summary")
    if not sm:
        return None
    now = time.time()
    out = dict(sm)
    out["age_s"] = int(now - sm["since"])
    out["checked_age_s"] = int(now - sm["checked"])
    out["since_text"] = time.strftime("%H:%M", time.localtime(sm["since"]))
    return out

def _route_overview(h: Handler) -> None:
    qt_results  = get_state_snapshot().get("quick_tests", {})
    batch_units = [e["unit"] for e in _pinned if "unit" in e]
    details_map = get_services_details(batch_units)
    groups      = []
    current     = None

    for entry in _pinned:
        if "group" in entry:
            current = {"group": entry["group"], "services": []}
            groups.append(current)
            continue
        if current is None:

            current = {"group": "Services", "services": []}
            groups.append(current)

        unit   = entry["unit"]
        detail = details_map.get(unit) or get_service_detail(unit)
        if detail.get("error"):
            log.debug("_route_overview: pinned unit %r — %s",
                       unit, detail["error"])
        installed = detail["installed"]
        state     = detail["state"]
        nr        = detail["nrestarts"]

        port  = entry.get("port",  "-")
        proto = entry.get("proto", "-")

        own       = _resolve_owner(detail)
        unit_info = _stat_mode_info(detail.get("fragment_path", ""))
        bin_info  = _stat_mode_info(detail.get("exec_path", ""))
        perm, perm_reasons = _perm_verdict(unit_info, bin_info)

        current["services"].append({
            "unit":      unit,
            "desc":      entry.get("desc", ""),
            "state":     state,
            "enabled":   detail["enabled"],
            "port":      port  if port  not in ("parse", "") else "-",
            "proto":     proto if proto not in ("parse", "") else "-",
            "nr":        nr,
            "qt":        qt_results.get(unit, "na"),
            "installed": installed,

            "owner":         own["owner"],
            "owner_source":  own["source"],
            "owner_is_root": own["is_root"],
            "owner_exempt":  unit in _ROOT_EXEMPT_UNITS,
            "owner_config":  detail.get("user_cfg", ""),
            "owner_group":   detail.get("group_cfg", ""),

            "mode":          unit_info["mode"],
            "mode_octal":    unit_info["octal"],
            "unit_path":     unit_info["path"],
            "unit_owner":    (f"{unit_info['owner']}:{unit_info['group']}"
                               if unit_info["exists"] else ""),
            "bin_mode":      bin_info["mode"],
            "bin_owner":     (f"{bin_info['owner']}:{bin_info['group']}"
                               if bin_info["exists"] else ""),
            "bin_path":      bin_info["path"],
            "perm_verdict":  perm if installed else "",
            "perm_reasons":  perm_reasons,
        })

    h.send_json({"ok": True, "groups": groups})

def get_service_pid(unit: str) -> int:
    if not _validate_unit(unit):
        return 0
    raw = _run(
        ["systemctl", "show", "-p", "MainPID", "--value", unit],
        timeout=5,
    )
    try:
        return max(0, int(raw.strip()))
    except (ValueError, TypeError):
        return 0

def find_unit_file(unit: str) -> "dict | None":
    if not _validate_unit(unit):
        return None

    search = [
        Path("/etc/systemd/system")  / unit,
        Path("/lib/systemd/system")  / unit,
        Path("/usr/lib/systemd/system") / unit,
        Path("/run/systemd/system")  / unit,
    ]
    write_path = Path("/etc/systemd/system") / unit

    for p in search:
        if p.is_file():
            promoted = (p != write_path and not write_path.exists())
            return {
                "path":      str(write_path),
                "read_path": str(p),
                "promoted":  promoted,
                "writable":  os.geteuid() == 0,
            }
    return None

def _route_services(h: Handler) -> None:
    qs    = parse_qs(urlparse(h.path).query)
    scope = qs.get("scope",  ["active"])[0]
    filt  = qs.get("filter", [""])[0]
    scope = scope if scope in ("active", "all") else "active"

    items = get_all_services(scope, filt, exclude=None)
    h.send_json({"ok": True, "items": items, "total": len(items)})

def _route_service_detail(h: Handler) -> None:
    qs    = parse_qs(urlparse(h.path).query)
    unit  = qs.get("unit",  [""])[0].strip()
    view  = qs.get("view",  ["none"])[0].strip()
    lines = qs.get("lines", ["50"])[0].strip()

    if not _validate_unit(unit):
        h.send_json({"ok": False, "message": f"Invalid unit: {unit!r}"}, 400)
        return

    detail = get_service_detail(unit)
    output = ""

    if view == "status":
        raw = _run(
            ["systemctl", "status", "--no-pager", "-l", unit],
            timeout=8,
        )
        output = raw

    elif view == "journal":
        try:
            n = max(10, min(int(lines), 500))
        except (ValueError, TypeError):
            n = 60
        raw = _run(
            ["journalctl", "-u", unit, f"-n{n}", "--no-pager"],
            timeout=8,
        )
        output = raw

    own       = _resolve_owner(detail)
    unit_info = _stat_mode_info(detail.get("fragment_path", ""))
    bin_info  = _stat_mode_info(detail.get("exec_path", ""))
    perm, perm_reasons = _perm_verdict(unit_info, bin_info)

    h.send_json({
        "ok": True, "output": output, "view": view, **detail,
        "owner":         own["owner"],
        "owner_source":  own["source"],
        "owner_is_root": own["is_root"],
        "owner_exempt":  unit in _ROOT_EXEMPT_UNITS,
        "unit_file":     unit_info,
        "exec_file":     bin_info,
        "perm_verdict":  perm,
        "perm_reasons":  perm_reasons,
    })

def _route_unit_file_get(h: Handler) -> None:
    qs   = parse_qs(urlparse(h.path).query)
    unit = qs.get("unit", [""])[0].strip()

    if not _validate_unit(unit):
        h.send_json({"ok": False, "message": f"Invalid unit: {unit!r}"}, 400)
        return

    info = find_unit_file(unit)
    if info is None:
        h.send_json({"ok": False,
                     "message": f"Unit file not found for {unit}"}, 404)
        return

    try:
        content = Path(info["read_path"]).read_text(errors="replace")
        if len(content) > 65536:
            content = content[:65536] + "\n# [truncated — file exceeds 64 KB]"
    except Exception as exc:
        h.send_json({"ok": False, "message": f"Cannot read file: {exc}"}, 500)
        return

    h.send_json({
        "ok":       True,
        "unit":     unit,
        "path":     info["path"],
        "read_path":info["read_path"],
        "content":  content,
        "promoted": info["promoted"],
        "writable": info["writable"],
    })

def _route_unit_file_post(h: Handler, data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "root required"}); return

    unit    = str(data.get("unit",    "")).strip()
    content = str(data.get("content", ""))

    if not _validate_unit(unit):
        h.send_json({"ok": False, "message": f"Invalid unit: {unit!r}"}, 400)
        return

    if not content.strip():
        h.send_json({"ok": False, "message": "Content must not be empty"}, 400)
        return

    write_path = Path("/etc/systemd/system") / unit
    tmp_path   = write_path.with_suffix(write_path.suffix + ".tmp")

    try:
        write_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(write_path, content)  
    except Exception as exc:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception as e:
            log.debug("_route_unit_file_post: %s", e)
            pass
        h.send_json({"ok": False, "message": f"Write failed: {exc}"}, 500)
        return

    r = subprocess.run(
        ["systemctl", "daemon-reload"],
        capture_output=True, text=True, timeout=15,
    )
    reload_ok = r.returncode == 0
    _log(f"unit_file saved: {write_path}  daemon-reload={'OK' if reload_ok else 'FAILED'}",
         stderr=not reload_ok)

    h.send_json({
        "ok":        True,
        "message":   f"Saved {write_path.name}" + ("" if reload_ok else " (daemon-reload failed)"),
        "path":      str(write_path),
        "reload_ok": reload_ok,
    })

_SVC_SIMPLE_ACTIONS = ("start", "stop", "reset_failed",
                       "enable", "disable", "reload", "mask", "unmask")

def _svc_simple_action(h: Handler, action: str, unit: str) -> None:
    if not _validate_unit(unit):
        h.send_json({"ok": False, "message": f"Invalid unit name: {unit!r}"}, 400)
        return
    subcmd = {
        "reset_failed": "reset-failed",
    }.get(action, action)
    r = subprocess.run(
        ["systemctl", subcmd, unit],
        capture_output=True, text=True, timeout=15,
    )
    ok  = r.returncode == 0
    msg = f"{action} {unit}: {'OK' if ok else r.stderr.strip() or 'failed'}"
    _log(msg, stderr=not ok)
    h.send_json({"ok": ok, "message": msg})

_RESTART_STOP_POLL_TIMEOUT  = 15

_RESTART_KILL_POLL_TIMEOUT  = 5

_RESTART_START_POLL_TIMEOUT = 10

_RESTART_POLL_INTERVAL      = 0.5

def _svc_get_active_substate(unit: str) -> "tuple[str, str]":
    raw = _run(["systemctl", "show", "-p", "ActiveState,SubState", unit], timeout=5)
    values = {}
    for line in raw.splitlines():
        if "=" in line:
            key, _, val = line.partition("=")
            values[key] = val.strip()
    return values.get("ActiveState", ""), values.get("SubState", "")

def _svc_wait_for_state(unit: str, want_active: bool,
                         timeout: float, interval: float = _RESTART_POLL_INTERVAL) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        active, _sub = _svc_get_active_substate(unit)
        pid = get_service_pid(unit)
        if want_active:
            if active == "active" and pid > 1:
                return True
        else:
            if active in ("inactive", "failed") and pid <= 1:
                return True
        time.sleep(interval)
    return False

def _svc_restart(h: Handler, unit: str) -> None:
    if not _validate_unit(unit):
        h.send_json({"ok": False, "message": f"Invalid unit name: {unit!r}"}, 400)
        return

    def _do_restart(u: str) -> None:
        t0 = time.monotonic()
        _log(f"restart {u}: sending SIGTERM via systemctl stop")
        r_stop = subprocess.run(
            ["systemctl", "stop", u],
            capture_output=True, text=True, timeout=30,
        )
        if r_stop.returncode != 0:
            _log(f"restart {u}: stop command failed — {r_stop.stderr.strip()}", stderr=True)

        stopped   = _svc_wait_for_state(u, want_active=False, timeout=_RESTART_STOP_POLL_TIMEOUT)
        escalated = False

        if not stopped:
            pid = get_service_pid(u)
            if pid > 1:
                _log(f"restart {u}: still running after {_RESTART_STOP_POLL_TIMEOUT}s — "
                     f"escalating to SIGKILL on PID {pid}", stderr=True)
                try:
                    os.kill(pid, signal.SIGKILL)
                    escalated = True
                except ProcessLookupError:
                    pass
            stopped = _svc_wait_for_state(u, want_active=False, timeout=_RESTART_KILL_POLL_TIMEOUT)

        stop_elapsed = time.monotonic() - t0
        _log(f"restart {u}: stop phase {'confirmed' if stopped else 'timed out'} "
             f"after {stop_elapsed:.1f}s" + (" (SIGKILL escalation used)" if escalated else ""),
             stderr=not stopped)

        t1 = time.monotonic()
        r_start = subprocess.run(
            ["systemctl", "start", u],
            capture_output=True, text=True, timeout=30,
        )
        if r_start.returncode != 0:
            _log(f"restart {u}: start command failed — {r_start.stderr.strip()}", stderr=True)

        started       = _svc_wait_for_state(u, want_active=True, timeout=_RESTART_START_POLL_TIMEOUT)
        start_elapsed = time.monotonic() - t1

        ok  = stopped and started
        msg = (
            f"restart {u}: stop {'OK' if stopped else 'TIMED OUT'} "
            f"({stop_elapsed:.1f}s{', SIGKILL escalation' if escalated else ''}) -> "
            f"start {'OK' if started else 'TIMED OUT/FAILED'} ({start_elapsed:.1f}s)"
        )
        _log(msg, stderr=not ok)

        try:
            _update_state(port_conflicts=check_port_duplicates())
        except Exception as exc:
            _log(f"bg_poll: port_conflicts post-restart error — {exc}", stderr=True)

    threading.Thread(
        target=_do_restart, args=(unit,),
        daemon=True, name=f"restart-{unit}",
    ).start()

    h.send_json({
        "ok":      True,
        "message": f"Restarting {unit} (graceful stop → verify → start → verify)…",
        "async":   True,
    })

def _svc_kill_pid(h: Handler, unit: str) -> None:
    if not _validate_unit(unit):
        h.send_json({"ok": False, "message": f"Invalid unit name: {unit!r}"}, 400)
        return
    pid = get_service_pid(unit)
    if pid <= 1:
        h.send_json({
            "ok":      False,
            "message": f"{unit}: no live PID (service may already be stopped)",
        })
        return
    try:
        os.kill(pid, signal.SIGKILL)
        msg = f"SIGKILL sent to PID {pid} ({unit})"
        _log(msg, stderr=True)
        h.send_json({"ok": True, "message": msg, "pid": pid})
    except ProcessLookupError:
        h.send_json({"ok": False, "message": f"PID {pid} already gone"})
    except PermissionError:
        h.send_json({"ok": False, "message": f"Permission denied killing PID {pid}"})

def _svc_reload_daemon(h: Handler) -> None:
    r = subprocess.run(
        ["systemctl", "daemon-reload"],
        capture_output=True, text=True, timeout=15,
    )
    ok  = r.returncode == 0
    msg = f"daemon-reload: {'OK' if ok else r.stderr.strip() or 'failed'}"
    _log(msg, stderr=not ok)
    h.send_json({"ok": ok, "message": msg})

def _svc_global_action(h: Handler, action: str) -> None:

    if action in ("emergency_restart", "stop_all"):
        units = [e["unit"] for e in _pinned if "unit" in e and e["unit"] != "sysmon.service"]
    else:
        units = [e["unit"] for e in _pinned if "unit" in e]
    results = []

    if action in ("stop_all", "emergency_restart"):
        for u in units:
            if not _validate_unit(u):
                continue
            r = subprocess.run(["systemctl", "stop", u],
                               capture_output=True, text=True, timeout=15)
            results.append({"unit": u, "ok": r.returncode == 0})

    if action in ("restart_all", "emergency_restart"):
        subcmd = "start" if action == "emergency_restart" else "restart"
        for u in units:
            if not _validate_unit(u):
                continue
            r = subprocess.run(["systemctl", subcmd, u],
                               capture_output=True, text=True, timeout=15)
            results.append({"unit": u, "ok": r.returncode == 0})

    ok  = all(r["ok"] for r in results) if results else True
    msg = f"{action}: {sum(r['ok'] for r in results)}/{len(results)} units OK"
    _log(msg, stderr=not ok)
    h.send_json({"ok": ok, "message": msg, "results": results})

def _route_svc(h: Handler, data: dict) -> None:
    action = str(data.get("action", "")).strip()
    unit   = str(data.get("unit",   "")).strip()
    _log(f"POST /api/svc action={action!r} unit={unit!r}")

    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "root required"}); return

    if action in _SVC_SIMPLE_ACTIONS:
        _svc_simple_action(h, action, unit)
    elif action == "restart":
        _svc_restart(h, unit)
    elif action == "kill_pid":
        _svc_kill_pid(h, unit)
    elif action == "reload_daemon":
        _svc_reload_daemon(h)
    elif action in ("stop_all", "restart_all", "emergency_restart"):
        _svc_global_action(h, action)
    else:

        h.send_json({
            "ok":      False,
            "message": f"Action '{action}' not yet implemented",
        }, 501)

def _pid_cmdline(pid) -> str:
    if not pid:
        return ""
    try:
        with open(f"/proc/{int(pid)}/cmdline", "rb") as fh:
            raw = fh.read(2048)
    except (OSError, ValueError):
        return ""
    return " ".join(raw.decode("utf-8", "replace").split("\0")).strip()[:300]

def get_open_ports(proto_filter: str = "both") -> list:
    raw = _ss_tlnpu_fetch()
    if not raw:
        log.debug("get_open_ports: `ss -tlnpu` returned no output "
                   "(binary missing, timeout, or permission issue)")
        return []

    results = []
    seen    = set()

    parsed = _parse_ss_entries(raw)
    if not parsed:
        log.debug(
            "get_open_ports: `ss -tlnpu` returned %d line(s) but none "
            "parsed into an entry — raw head: %r",
            len(raw.splitlines()), raw.splitlines()[:3],
        )

    for e in parsed:
        if proto_filter != "both" and e["proto"] != proto_filter:
            continue

        key = (e["proto"], e["port"])
        if key in seen:
            continue
        seen.add(key)

        results.append({
            "port":    e["port"],
            "proto":   e["proto"],
            "addr":    e["addr"],
            "pid":     e["pid"],
            "process": e["process"],
            "cmd":     _pid_cmdline(e["pid"]),
            "service": "",
        })

    results.sort(key=lambda x: int(x["port"]))
    return results

def label_ports(ports: list, pinned: list) -> list:

    idx: dict = {}
    for entry in pinned:
        if "group" in entry:
            continue
        port = entry.get("port", "-")
        if port in ("-", "parse", "", None):
            continue
        if not str(port).isdigit():
            continue
        unit_short = entry.get("unit", "").replace(".service", "")
        idx[str(port)] = unit_short

    for p in ports:
        p["service"] = idx.get(p["port"], "")

    return ports

def _route_ports(h: Handler) -> None:
    qs    = parse_qs(urlparse(h.path).query)
    proto = qs.get("proto", ["both"])[0].strip().lower()
    if proto not in ("both", "tcp", "udp"):
        proto = "both"

    ports = get_open_ports(proto)
    label_ports(ports, _pinned)
    h.send_json({"ok": True, "ports": ports})

def _probe_targets(port: str, proto: str) -> "list[tuple[int, str]]":
    targets: "list[tuple[int, str]]" = []
    for e in _parse_ss_entries(_ss_tlnpu_fetch()):
        if e["port"] != port or e["proto"] != proto:
            continue
        addr = e["addr"].strip("[]")
        host, _, scope = addr.partition("%")
        if host in ("", "*", "0.0.0.0"):
            t = (_socket.AF_INET, "127.0.0.1")
        elif host == "::":
            t = (_socket.AF_INET6, "::1")
        elif ":" in host:
            t = (_socket.AF_INET6, f"{host}%{scope}" if scope and host.lower().startswith("fe80") else host)
        else:
            t = (_socket.AF_INET, host)
        if t not in targets:
            targets.append(t)
    for t in ((_socket.AF_INET, "127.0.0.1"), (_socket.AF_INET6, "::1")):
        if t not in targets:
            targets.append(t)
    return targets

def _probe_host_label(fam: int, host: str) -> str:
    return f"[{host}]" if fam == _socket.AF_INET6 else host

def _probe_tcp(targets, port: int) -> "tuple[bool, str, tuple | None]":
    tried, first_err = [], ""
    for fam, host in targets:
        try:
            with _socket.socket(fam, _socket.SOCK_STREAM) as s:
                s.settimeout(3)
                s.connect((host, port))
            return True, "", (fam, host)
        except OSError as e:
            if e.errno == 97:
                continue
            tried.append(_probe_host_label(fam, host))
            if not first_err:
                first_err = e.strerror or str(e)[:80] or type(e).__name__
    return False, (f"not accepting connections on {', '.join(tried) or 'any address'}"
                   f" ({first_err or 'no listener'})"), None

def _probe_http(fam: int, host: str, port: int) -> "tuple[bool, str]":
    import http.client as _http
    import ssl as _ssl
    hp = _probe_host_label(fam, host)
    first_err = ""
    for scheme in ("http", "https"):
        try:
            if scheme == "http":
                conn = _http.HTTPConnection(hp.strip("[]") if fam == _socket.AF_INET else host,
                                            port, timeout=4)
            else:
                ctx = _ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = _ssl.CERT_NONE
                conn = _http.HTTPSConnection(host, port, timeout=4, context=ctx)
            conn.request("GET", "/", headers={"Host": f"{hp}:{port}"})
            code = conn.getresponse().status
            conn.close()
            return True, f"{scheme.upper()} {code} from {hp}:{port}"
        except Exception as e:
            if not first_err:
                first_err = str(e)[:80] or type(e).__name__
    return False, f"No HTTP or HTTPS reply from {hp}:{port} ({first_err})"

def _probe_udp(targets, port: int) -> "tuple[bool, str]":
    fam, host = targets[0]
    hp = _probe_host_label(fam, host)
    try:
        with _socket.socket(fam, _socket.SOCK_DGRAM) as s:
            s.settimeout(1.5)
            s.connect((host, port))
            s.send(b"\n")
            try:
                s.recv(512)
                return True, f"UDP {hp}:{port} open (it replied)"
            except _socket.timeout:
                return True, f"UDP {hp}:{port} open or filtered (no reply, no rejection)"
    except ConnectionRefusedError:
        return False, f"UDP {hp}:{port} closed (port unreachable)"
    except Exception as e:
        return False, f"UDP {hp}:{port} — {str(e)[:80]}"

def _route_ports_probe(h: Handler) -> None:
    qs   = parse_qs(urlparse(h.path).query)
    kind = qs.get("type", ["tcp"])[0].strip().lower()
    port_str = qs.get("port", [""])[0].strip()

    if not port_str.isdigit() or not 0 < int(port_str) < 65536:
        h.send_json({"ok": False, "message": f"Invalid port: {port_str!r}"}, 400)
        return
    port = int(port_str)

    if kind in ("http", "tcp"):
        ok, err, hit = _probe_tcp(_probe_targets(port_str, "tcp"), port)
        if not ok:
            h.send_json({"ok": False, "message": f"TCP :{port} — {err}"})
            return
        if kind == "tcp":
            h.send_json({"ok": True, "message":
                         f"TCP {_probe_host_label(*hit)}:{port} accepting connections"})
            return
        ok, msg = _probe_http(hit[0], hit[1], port)
        h.send_json({"ok": ok, "message": msg})
        return

    if kind == "udp":
        ok, msg = _probe_udp(_probe_targets(port_str, "udp"), port)
        h.send_json({"ok": ok, "message": msg})
        return

    h.send_json({"ok": False, "message": f"Unknown probe type: {kind!r}"}, 400)

def get_journal_service_list(pinned: list) -> list:
    pinned_units = []
    seen         = set()

    batch_units  = [e["unit"] for e in pinned if "unit" in e]
    details_map  = get_services_details(batch_units)

    for entry in pinned:
        if "group" in entry:
            continue
        unit   = entry["unit"]
        detail = details_map.get(unit) or get_service_detail(unit)
        if detail.get("error"):
            log.debug("get_journal_service_list: skipping pinned unit "
                       "%r — %s", unit, detail["error"])
        if not detail["installed"]:
            continue
        pinned_units.append({
            "unit":    unit,
            "desc":    entry.get("desc", ""),
            "state":   detail["state"],
            "enabled": detail["enabled"],
        })
        seen.add(unit)

    active_extra = get_all_services("active", "", exclude=seen)
    extra = [{"unit": it["unit"], "desc": "", "state": it["state"],
              "enabled": it["enabled"]} for it in active_extra]

    return pinned_units + extra

def fetch_journal(unit: str, lines: int = 100) -> "tuple[str, str]":
    if not _validate_unit(unit):
        return "", "invalid unit name"
    lines = max(10, min(lines, 2000))
    try:
        r = subprocess.run(
            ["journalctl", "-u", unit, f"-n{lines}", "--no-pager"],
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        return "", "journalctl not found on this system"
    except subprocess.TimeoutExpired:
        return "", "journalctl timed out"
    except Exception as e:
        log.debug("fetch_journal: %s", e)
        return "", f"journalctl failed: {e}"

    stdout = r.stdout.strip()
    stderr = r.stderr.strip()

    if r.returncode != 0 and stderr:
        return "", stderr
    return stdout, ""

def _route_journal_list(h: Handler) -> None:
    services = get_journal_service_list(_pinned)
    h.send_json({"ok": True, "services": services})

def _route_journal_fetch(h: Handler) -> None:
    qs    = parse_qs(urlparse(h.path).query)
    unit  = qs.get("unit",  [""])[0].strip()
    lines = qs.get("lines", ["200"])[0].strip()

    if not _validate_unit(unit):
        h.send_json({"ok": False, "message": f"Invalid unit: {unit!r}"}, 400)
        return

    try:
        n = max(10, min(int(lines), 2000))
    except (ValueError, TypeError):
        n = 200

    output, error = fetch_journal(unit, n)
    if error:
        h.send_json({"ok": False, "message": f"Journal fetch failed: {error}"})
        return
    h.send_json({"ok": True, "unit": unit, "lines": n, "output": output})

_DVLOG_ROOT        = Path("/var/log")
_DVLOG_IRCDDB_DIR  = Path("/var/log/ircddbgateway")
_DVLOG_DAYS        = 7
_DVLOG_READ_MAX    = 2_000_000
_DVLOG_COUNT_MAX   = 20_000_000
_DVLOG_AGENT_LINES = 50
_DVLOG_DATED_RE    = re.compile(r"-(\d{4}-\d{2}-\d{2})\.log$")
_DVLOG_ROOT_RE     = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")

_DVLOG_INI_PROGRAMS = (
    ("mmdvm", "MMDVM_Bridge", "mmdvm_bridge.service",
     (Path("/opt/MMDVM_Bridge/MMDVM_Bridge.ini"), Path("/etc/MMDVM_Bridge/MMDVM_Bridge.ini"),
      Path("/etc/dvswitch/MMDVM_Bridge.ini"))),
    ("ysf", "YSFGateway", "ysfgateway.service",
     (Path("/opt/YSFGateway/YSFGateway.ini"), Path("/etc/YSFGateway/YSFGateway.ini"),
      Path("/etc/dvswitch/YSFGateway.ini"))),
    ("p25", "P25Gateway", "p25gateway.service",
     (Path("/opt/P25Gateway/P25Gateway.ini"), Path("/etc/P25Gateway/P25Gateway.ini"),
      Path("/etc/dvswitch/P25Gateway.ini"))),
    ("nxdn", "NXDNGateway", "nxdngateway.service",
     (Path("/opt/NXDNGateway/NXDNGateway.ini"), Path("/etc/NXDNGateway/NXDNGateway.ini"),
      Path("/etc/dvswitch/NXDNGateway.ini"))),
    ("m17", "USRP2M17", "usrp2m17.service", tuple(_M17_INI_CANDIDATES)),
)

_DVLOG_JOURNAL_UNITS = (
    ("analog_bridge.service",  "Analog_Bridge"),
    ("stfu.service",           "STFU"),
    ("netcheck.service",       "netcheck"),
    ("ircddbgatewayd.service", "ircDDBGateway service"),
)

def _dvlog_under_root(path: Path) -> bool:
    try:
        real = Path(os.path.realpath(path))
    except OSError:
        return False
    root = os.path.realpath(_DVLOG_ROOT)
    return str(real).startswith(root + os.sep) and real.is_file()

def _dvlog_file_entry(src_id: str, label: str, group: str, path: Path) -> "dict | None":
    if not _dvlog_under_root(path):
        return None
    try:
        st = path.stat()
    except OSError:
        return None
    return {"id": src_id, "kind": "file", "group": group, "label": label,
            "path": str(path), "size": st.st_size, "mtime": int(st.st_mtime), "tz": "UTC"}

def _dvlog_dated_files(folder: Path, root: str) -> "list[Path]":
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    dated = sorted((n for n in names
                    if n.startswith(root + "-") and _DVLOG_DATED_RE.search(n)
                    and len(n) == len(root) + 15), reverse=True)
    out = [folder / n for n in dated[:_DVLOG_DAYS]]
    if (root + ".log") in names:
        out.append(folder / (root + ".log"))
    return out

def _dvlog_unit_installed(unit: str) -> bool:
    for d in ("/etc/systemd/system", "/lib/systemd/system", "/usr/lib/systemd/system"):
        if os.path.exists(os.path.join(d, unit)):
            return True
    return False

def _dvlog_ini_log_settings(candidates) -> "dict | None":
    for cand in candidates:
        content, err = read_path_file(cand)
        if err:
            continue
        sect = _dvs_parse_sections(content).get("LOG", {})
        return {"ini": str(cand),
                "file_level": sect.get("FileLevel", "").strip(),
                "file_path":  sect.get("FilePath", "").strip(),
                "file_root":  sect.get("FileRoot", "").strip()}
    return None

def dvlog_sources() -> "list[dict]":
    out: "list[dict]" = []
    if _DVLOG_IRCDDB_DIR.is_dir():
        for p in _dvlog_dated_files(_DVLOG_IRCDDB_DIR, "ircDDBGateway"):
            m = _DVLOG_DATED_RE.search(p.name)
            sid = "ircddb:" + (m.group(1) if m else "plain")
            e = _dvlog_file_entry(sid, p.name, "ircDDBGateway", p)
            if e:
                out.append(e)
        for name in ("Headers", "Links", "STARnet"):
            e = _dvlog_file_entry("ircddb:" + name, name + ".log", "ircDDBGateway",
                                  _DVLOG_IRCDDB_DIR / (name + ".log"))
            if e:
                out.append(e)
    for key, prog, unit, cands in _DVLOG_INI_PROGRAMS:
        cfg = _dvlog_ini_log_settings(cands)
        if cfg is None:
            continue
        files: "list[dict]" = []
        root = cfg["file_root"] or prog
        folder = cfg["file_path"]
        if folder and _DVLOG_ROOT_RE.match(root):
            for p in _dvlog_dated_files(Path(folder), root):
                m = _DVLOG_DATED_RE.search(p.name)
                e = _dvlog_file_entry(f"{key}:" + (m.group(1) if m else "plain"),
                                      p.name, prog, p)
                if e:
                    files.append(e)
        off = cfg["file_level"] == "0"
        note = ""
        if off:
            note = "file logging off (FileLevel=0 in " + cfg["ini"] + ")"
        elif not folder:
            note = "no [Log] FilePath in " + cfg["ini"]
        elif not files:
            note = "no log files found in " + folder
        out.extend(files)
        if (off or not files) and _dvlog_unit_installed(unit):
            out.append({"id": "journal:" + unit, "kind": "journal", "group": prog,
                        "label": unit + " (journal)", "unit": unit, "tz": "local",
                        "note": note})
        elif note:
            out.append({"id": "", "kind": "none", "group": prog, "label": prog,
                        "note": note})
    for unit, label in _DVLOG_JOURNAL_UNITS:
        if _dvlog_unit_installed(unit):
            out.append({"id": "journal:" + unit, "kind": "journal", "group": label,
                        "label": unit + " (journal)", "unit": unit, "tz": "local"})
    return out

def _dvlog_find(src_id: str) -> "dict | None":
    if not src_id or len(src_id) > 80:
        return None
    for e in dvlog_sources():
        if e.get("id") == src_id:
            return e
    return None

def _dvlog_tail(path: Path, lines: int, max_bytes: int = 0) -> "tuple[str, bool]":
    max_bytes = max_bytes or _DVLOG_READ_MAX
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            want = (lines + 1) if lines > 0 else None
            buf = b""
            pos = size
            while pos > 0 and len(buf) < max_bytes:
                step = min(65536, pos, max_bytes - len(buf))
                pos -= step
                f.seek(pos)
                buf = f.read(step) + buf
                if want is not None and buf.count(b"\n") >= want:
                    break
    except OSError as e:
        return f"[could not read {path}: {e}]", False
    cut = pos > 0
    text = buf.decode("utf-8", errors="replace")
    rows = text.splitlines()
    if cut and rows:
        rows = rows[1:]
    if lines > 0 and len(rows) > lines:
        rows = rows[-lines:]
        cut = True
    return "\n".join(rows), cut

def _dvlog_count_lines(path: Path) -> int:
    try:
        if path.stat().st_size > _DVLOG_COUNT_MAX:
            return -1
        n = 0
        last = b"\n"
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                n += chunk.count(b"\n")
                last = chunk[-1:]
        return n + (0 if last == b"\n" else 1)
    except OSError:
        return -1

def dvlog_read(src_id: str, lines: int) -> dict:
    e = _dvlog_find(src_id)
    if e is None or e["kind"] == "none":
        return {"ok": False, "message": "Unknown log"}
    if e["kind"] == "journal":
        n = 2000 if lines <= 0 else max(10, min(lines, 2000))
        text, err = fetch_journal(e["unit"], n)
        if err:
            return {"ok": False, "message": f"Journal fetch failed: {err}"}
        return {"ok": True, "id": src_id, "label": e["label"], "tz": e["tz"],
                "text": text, "truncated": False, "total": -1}
    text, cut = _dvlog_tail(Path(e["path"]), lines)
    return {"ok": True, "id": src_id, "label": e["label"], "tz": e["tz"],
            "path": e["path"], "text": text, "truncated": cut,
            "total": _dvlog_count_lines(Path(e["path"]))}

def _dvlog_boot_warnings(lines: int) -> "tuple[str, str]":
    try:
        r = subprocess.run(["journalctl", "-b", "-p", "warning", f"-n{lines}", "--no-pager"],
                           capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        return "", "journalctl not found on this system"
    except subprocess.TimeoutExpired:
        return "", "journalctl timed out"
    except Exception as e:
        return "", f"journalctl failed: {e}"
    if r.returncode != 0 and r.stderr.strip():
        return "", r.stderr.strip()
    return r.stdout.strip(), ""

def dvlog_agent_bundle(lines: int = _DVLOG_AGENT_LINES) -> dict:
    srcs = dvlog_sources()
    picked: "list[dict]" = []
    newest_seen: "set[str]" = set()
    for e in srcs:
        if e["kind"] == "file":
            dated = bool(_DVLOG_DATED_RE.search(e["label"]))
            if dated:
                if e["group"] in newest_seen:
                    continue
                newest_seen.add(e["group"])
            picked.append(e)
        elif e["kind"] == "journal":
            picked.append(e)
    now = datetime.now()
    parts = [f"== ASL-DVS DV gateway logs · {get_hostname()} · "
             f"{now.strftime('%Y-%m-%d %H:%M:%S')} local · last {lines} lines of each =="]
    empty: "list[str]" = []
    blocks = 0
    for e in picked:
        if e["kind"] == "file":
            if e.get("size", 0) == 0:
                empty.append(e["label"])
                continue
            text, _cut = _dvlog_tail(Path(e["path"]), lines)
            total = _dvlog_count_lines(Path(e["path"]))
            shown = len(text.splitlines())
            of = f"{total:,}" if total >= 0 else "many"
            head = f"== {e['path']} (UTC) · last {shown} of {of} lines =="
        else:
            text, err = fetch_journal(e["unit"], lines)
            if err:
                text = f"[journal fetch failed: {err}]"
            if not text.strip() or text.strip() == "-- No entries --":
                empty.append(e["label"])
                continue
            head = f"== journal: {e['unit']} (local time) · last {lines} lines =="
        parts.append("")
        parts.append(head)
        parts.append(text)
        blocks += 1
    text, err = _dvlog_boot_warnings(lines)
    parts.append("")
    parts.append(f"== journal: this boot, warnings and worse (local time) · last {lines} lines ==")
    parts.append(text if not err else f"[journal fetch failed: {err}]")
    blocks += 1
    for e in srcs:
        if e["kind"] == "none":
            empty.append(f"{e['group']}: {e['note']}")
    if empty:
        parts.append("")
        parts.append("== empty or not logging: " + "; ".join(empty) + " ==")
    out = "\n".join(parts) + "\n"
    return {"ok": True, "text": out, "bytes": len(out.encode("utf-8")), "blocks": blocks,
            "lines": lines}

def _route_logs_list(h: Handler) -> None:
    h.send_json({"ok": True, "sources": dvlog_sources()})

def _route_logs_read(h: Handler) -> None:
    qs = parse_qs(urlparse(h.path).query)
    src_id = qs.get("id", [""])[0].strip()
    raw = qs.get("lines", ["200"])[0].strip().lower()
    if raw == "all":
        n = 0
    else:
        try:
            n = max(10, min(int(raw), 100000))
        except ValueError:
            n = 200
    d = dvlog_read(src_id, n)
    h.send_json(d, 200 if d.get("ok") else 404)

def _route_logs_agent(h: Handler) -> None:
    h.send_json(dvlog_agent_bundle())

def parse_rpt_conf(content: str) -> list:

    sections, node_sects = _rpt_scan(content)

    callsign = _rpt_first_callsign(node_sects)

    def _node_sort(nid: str) -> tuple:
        n = int(nid)
        return (1 if n < 2000 else 0, n)

    ordered = sorted(node_sects.keys(), key=_node_sort)

    checks: list = []

    callsign_ok = bool(callsign) and callsign.upper() not in _RPT_DEF_CALLSIGNS
    checks.append({
        "title":  "Callsign",
        "value":  callsign if callsign else "not set",
        "status": "pass" if callsign_ok else "fail",
        "note":   None, "url": None,
    })

    if not ordered:
        checks.append({"title": "Node", "value": "not configured",
                       "status": "fail", "note": None, "url": None})

    for nid in ordered:
        kv   = node_sects[nid]
        rxch = kv.get("rxchannel", "").strip()
        um   = _USRP_RX_RE.search(rxch)

        checks.append({"title": "Node", "value": nid,
                       "status": "pass", "note": None, "url": None})

        checks.append({"title": "RX Channel", "value": rxch if rxch else "not set",
                       "status": "info", "note": None, "url": None})

        if um:
            rx_port = um.group(2)
            tx_port = um.group(3)
            checks.append({"title": "RX Port", "value": rx_port,
                           "status": "info", "note": None, "url": None})
            checks.append({
                "title":  "TX Port",
                "value":  tx_port,
                "status": "info",
                "note":   (f"Analog_Bridge [USRP] must listen on rxPort={rx_port} "
                           f"and send on txPort={tx_port}"),
                "url":    None,
            })

    return checks

def parse_manager_conf(content: str) -> list:
    sections = _parse_sections(content)
    checks: list = []
    users = [s for s in sections if s.lower() != "general"]

    if not users:
        checks.append({"title": "User",     "value": "none configured",
                       "status": "fail",    "note": None})
        checks.append({"title": "Password", "value": None,
                       "status": "fail",    "note": None})
        return checks

    for user in users:
        kv     = sections[user]
        secret = kv.get("secret", "").strip()
        checks.append({"title": "User",     "value": user,
                       "status": "pass",    "note": None})
        checks.append({"title": "Password", "value": None,
                       "status": "pass" if secret else "fail",
                       "note": None})
    return checks

def parse_echolink_conf(content: str) -> list:
    sections = _parse_sections(content)

    kv: dict = {}
    for sname in sections:
        sv = sections[sname]
        if "call" in sv or "node" in sv:
            kv = sv
            break
    if not kv:
        kv = sections.get("general", {})

    call    = kv.get("call",    "").strip()
    pwd     = kv.get("pwd",     "").strip()
    node    = kv.get("node",    "").strip()
    astnode = kv.get("astnode", "").strip()

    return [
        {
            "title":  "Callsign",
            "value":  call if call else "not set",
            "status": "pass" if call else "fail",
            "note":   None, "url": None,
        },
        {
            "title":  "Password",
            "value":  None,
            "status": "pass" if pwd else "fail",
            "note":   None, "url": None,
        },
        {
            "title":  "Echo Node",
            "value":  node if node else "not set",
            "status": "pass" if node else "fail",
            "note":   None, "url": None,
        },
        {
            "title":  "ASL Node",
            "value":  astnode if astnode else "not set",
            "status": "pass" if astnode else "fail",
            "note":   None, "url": None,
        },
    ]

def parse_rpt_http_registrations(content: str) -> list:
    entries = []
    for line in content.splitlines():
        m = _REGISTER_RE.match(line)
        if not m:
            continue
        entries.append((m.group(1).strip(), bool(m.group(2).strip())))

    if not entries:
        return [{
            "title":  "Registration",
            "value":  "none configured",
            "status": "fail",
            "note":   None,
            "url":    None,
        }]

    checks = []
    for node, has_pwd in entries:
        node_ok = node.isdigit() and len(node) >= 4
        checks.append({
            "title":  f"Node {node}",
            "value":  node if node_ok else "invalid",
            "status": "pass" if node_ok else "fail",
            "note":   None,
            "url":    None,
        })
        checks.append({
            "title":  "Password",
            "value":  None,
            "status": "pass" if has_pwd else "fail",
            "note":   _ASL_NOTE,
            "url":    _ASL_URL,
        })
    return checks

def parse_savenode_conf(content: str) -> list:

    pairs: list = []
    current_node = ""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        m = _SAVENODE_KV_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if key == "NODE":
            current_node = val
        elif key == "PASSWORD" and current_node:
            pairs.append((current_node, bool(val)))
            current_node = ""

    if current_node:
        pairs.append((current_node, False))

    if not pairs:
        return [
            {"title": "Node",     "value": "none configured",
             "status": "fail",    "note": None, "url": None},
            {"title": "Password", "value": None,
             "status": "fail",    "note": _ASL_NOTE, "url": _ASL_URL},
        ]

    checks = []
    for node, has_pwd in pairs:
        checks.append({
            "title":  "Node",
            "value":  node,
            "status": "pass" if node else "fail",
            "note":   None, "url": None,
        })
        checks.append({
            "title":  "Password",
            "value":  None,
            "status": "pass" if has_pwd else "fail",
            "note":   _ASL_NOTE, "url": _ASL_URL,
        })
    return checks

_AUTOLOAD_RE = re.compile(r'^\s*autoload\s*[=:]\s*(\S+)', re.IGNORECASE)

def parse_modules_conf(content: str) -> list:
    loaded:   list = []
    required: list = []
    noloaded: list = []
    autoload       = False

    for line in content.splitlines():
        ml = _LOAD_RE.match(line)
        if ml:

            directive = (ml.group(1) or ml.group(3) or "").lower()
            name      = (ml.group(2) or ml.group(4) or "").strip()
            if name:
                if directive == "require":
                    required.append(name)
                else:
                    loaded.append(name)
            continue
        mn = _NOLOAD_RE.match(line)
        if mn:
            name = (mn.group(1) or mn.group(2) or "").strip()
            if name:
                noloaded.append(name)
            continue
        ma = _AUTOLOAD_RE.match(line)
        if ma:
            autoload = ma.group(1).lower() in ("yes", "true", "1")

    checks: list = []

    for mod in sorted(m for m in set(loaded)   if m.lower().startswith("chan_")):
        checks.append({"title": mod, "value": "load",
                       "status": "info", "note": None, "url": None})
    for mod in sorted(m for m in set(required) if m.lower().startswith("chan_")):
        checks.append({"title": mod, "value": "require",
                       "status": "info", "note": None, "url": None})
    for mod in sorted(m for m in set(noloaded) if m.lower().startswith("chan_")):
        checks.append({"title": mod, "value": "noload",
                       "status": "none", "note": None, "url": None})

    if not checks:

        checks.append({
            "title":  "autoload",
            "value":  "yes — all channels load automatically" if autoload
                      else "no chan_* entries found",
            "status": "info",
            "note":   None, "url": None,
        })

    return checks

_COLLAPSIBLE_CHECKS = {"modules.conf"}

def parse_extensions_conf(content: str) -> list:
    sections = _parse_sections(content)
    kv       = sections.get("globals", {})

    homenpa = (kv.get("HOMENPA","") or kv.get("homenpa","")).strip()
    node    = (kv.get("NODE","")    or kv.get("node","")).strip()

    npa_ok   = bool(homenpa) and homenpa != "999"
    node_ok  = bool(node) and node.isdigit() and int(node) >= 1000

    return [
        {
            "title":  "Area Code",
            "value":  homenpa if homenpa else "not set",
            "status": "pass" if npa_ok  else "fail",
            "note":   None, "url": None,
        },
        {
            "title":  "Node",
            "value":  node if node else "not set",
            "status": "pass" if node_ok else "fail",
            "note":   None, "url": None,
        },
    ]

_FILE_PARSERS: "dict[str, object]" = {
    "rpt.conf":                    parse_rpt_conf,
    "manager.conf":                parse_manager_conf,
    "echolink.conf":               parse_echolink_conf,
    "rpt_http_registrations.conf": parse_rpt_http_registrations,
    "savenode.conf":               parse_savenode_conf,
    "modules.conf":                parse_modules_conf,
    "extensions.conf":             parse_extensions_conf,
}

def list_asterisk_files(include_hidden: bool = False) -> list:
    hidden = set() if include_hidden else _get_hidden_files()
    try:
        return sorted(
            f.name for f in _AST_DIR.iterdir()
            if f.is_file()
            and f.suffix == ".conf"
            and not f.name.startswith(".")
            and f.name not in hidden
        )
    except (FileNotFoundError, PermissionError):
        return []

def write_asterisk_file(filename: str, content: str) -> "tuple[bool, str]":
    if not validate_asterisk_filename(filename):
        return False, f"Invalid filename: {filename!r}"
    return write_path_file(_AST_DIR / filename, content)

_DVSWITCH_FILES: "list[Path]" = [

    Path("/opt/Analog_Bridge/Analog_Bridge.ini"),
    Path("/etc/Analog_Bridge/Analog_Bridge.ini"),

    Path("/opt/Analog_Reflector/Analog_Reflector.ini"),
    Path("/etc/Analog_Reflector/Analog_Reflector.ini"),

    Path("/opt/MMDVM_Bridge/DVSwitch.ini"),
    Path("/etc/MMDVM_Bridge/DVSwitch.ini"),
    Path("/opt/MMDVM_Bridge/MMDVM_Bridge.ini"),
    Path("/etc/dvswitch/DVSwitch.ini"),
    Path("/etc/dvswitch/Analog_Bridge.ini"),
    Path("/etc/dvswitch/MMDVM_Bridge.ini"),

    Path("/var/lib/dvswitch/dvs/var.txt"),

    Path("/etc/ircddbgateway"),
]

_ALLMON3_DIR   = Path("/etc/allmon3")

_ALLMON3_FILES: "list[Path]" = [
    _ALLMON3_DIR / "allmon3.ini",
    _ALLMON3_DIR / "web.ini",
    _ALLMON3_DIR / "users",
    _ALLMON3_DIR / "menu.ini",
    _ALLMON3_DIR / "custom.css",
]

_ALLMON3_READONLY = {"users"}

_AB_DEF_RPT_ID     = "123456789"

_MB_DEF_CALLSIGN   = "N0CALL"

_RPT_DEF_CALLSIGNS = frozenset({"N0CALL", "NOTSET", "NONE", ""})

_DVS_MODE_SECTIONS = ("DMR", "DSTAR", "NXDN", "P25", "YSF", "ASL", "STFU")

_DVS_SECTION_LABELS = {
    "DMR":   "DMR network",
    "DSTAR": "D-STAR gateway",
    "NXDN":  "NXDN gateway",
    "P25":   "P25 gateway",
    "YSF":   "YSF/FCS gateway",
    "ASL":   "AllStarLink USRP",
    "STFU":  "BrandMeister ODMRT",
}

_MB_MODE_MAP = (
    ("DMR",           "DMR NETWORK",           "DMR"),
    ("SYSTEM FUSION", "SYSTEM FUSION NETWORK", "YSF"),
    ("P25",           "P25 NETWORK",           "P25"),
    ("NXDN",          "NXDN NETWORK",          "NXDN"),
    ("D-STAR",        "D-STAR NETWORK",        "D-Star"),
)

_MB_ADDR_KEYS: "dict[str, tuple]" = {
    "DMR NETWORK":           ("Address",),
    "SYSTEM FUSION NETWORK": ("GatewayAddress", "Address"),
    "P25 NETWORK":           ("GatewayAddress", "Address"),
    "NXDN NETWORK":          ("GatewayAddress", "Address"),
    "D-STAR NETWORK":        ("GatewayAddress", "Address"),
}

_KNOWN_AMBE_MODES = frozenset({"DMR", "DSTAR", "NXDN", "P25", "YSFN", "YSFW"})

def parse_analog_bridge(content: str) -> list:
    sections = _dvs_parse_sections(content)
    general  = sections.get("GENERAL",    {})
    ambe     = sections.get("AMBE_AUDIO", {})
    usrp     = sections.get("USRP",       {})

    fallback = general.get("decoderFallBack", "").strip().lower()

    dmr_id = ambe.get("gatewayDmrId", "").strip()
    rep_id = ambe.get("repeaterID",   "").strip()

    ambe_mode  = ambe.get("ambeMode",  "").strip()
    tx_tg      = ambe.get("txTg",      "").strip()
    tx_ts      = ambe.get("txTs",      "").strip()
    color_code = ambe.get("colorCode", "").strip()

    rx_port = usrp.get("rxPort", "").strip()
    tx_port = usrp.get("txPort", "").strip()

    dmr_id_ok = bool(dmr_id) and dmr_id != _AB_DEF_DMR_ID
    rep_id_ok  = bool(rep_id) and rep_id != _AB_DEF_RPT_ID
    mode_ok    = ambe_mode.upper() in _KNOWN_AMBE_MODES if ambe_mode else False
    ts_ok      = tx_ts in ("1", "2", "")

    checks = [

        {
            "title":  "DMR ID",
            "value":  dmr_id if dmr_id else "not set",
            "status": "pass" if dmr_id_ok else "fail",
            "notes":  None,
        },
        {
            "title":  "Repeater ID",
            "value":  rep_id if rep_id else "not set",
            "status": "pass" if rep_id_ok else "fail",
            "notes":  None,
        },

        {
            "title":  "AMBE Mode",
            "value":  ambe_mode if ambe_mode else "not set",
            "status": "pass" if mode_ok else "fail",
            "notes":  (f"Known modes: {', '.join(sorted(_KNOWN_AMBE_MODES))}"
                       if not mode_ok else None),
        },
        {
            "title":  "TX Talkgroup",
            "value":  tx_tg if tx_tg else "not set",
            "status": "info",
            "notes":  None,
        },
        {
            "title":  "TX Slot",
            "value":  tx_ts if tx_ts else "not set",
            "status": "info" if ts_ok else "fail",
            "notes":  "Expected 1 or 2" if not ts_ok else None,
        },
        {
            "title":  "Color Code",
            "value":  color_code if color_code else "not set",
            "status": "info",
            "notes":  None,
        },
        {
            "title":  "SW AMBE Fallback",
            "value":  fallback if fallback else "not set",
            "status": "info",
            "notes":  ("Software AMBE decoding enabled — hardware dongle not required"
                       if fallback == "true" else None),
        },
    ]

    if rx_port:
        checks.append({
            "title":  "RX Port",
            "value":  rx_port,
            "status": "info",
            "notes": [
                f"Port {rx_port} — AllStar sends RX audio out to this port",
                "rxPort — Analog_Bridge listens for RX audio from AllStar",
            ],
        })
    if tx_port:
        checks.append({
            "title":  "TX Port",
            "value":  tx_port,
            "status": "info",
            "notes": [
                f"Port {tx_port} — AllStar listens for TX audio on this port",
                "txPort — Analog_Bridge sends TX audio out to this port",
            ],
        })
    if rx_port or tx_port:
        rpt = _dvsm_read_rpt_conf()
        nodes = [n for n in rpt.get("nodes", []) if n.get("usrp_rx") == rx_port] if rpt.get("raw_ok") else []
        good = [n for n in nodes if n.get("usrp_tx") == tx_port]
        want = f"rxchannel = USRP/127.0.0.1:{rx_port or '?'}:{tx_port or '?'}"
        if not rpt.get("raw_ok"):
            st, val, notes = "warn", "rpt.conf unreadable", [rpt.get("error") or "Check /etc/asterisk/rpt.conf"]
        elif good:
            st, val, notes = "pass", "node " + ", ".join(n["id"] for n in good), [want]
        elif nodes:
            st = "fail"
            val = "node " + ", ".join(f"{n['id']} ({n.get('rxchannel', '')})" for n in nodes)
            notes = [f"Asterisk listens on {nodes[0].get('usrp_tx') or '?'}, but txPort sends to {tx_port or '?'}",
                     "Make txPort and the last port of the rxchannel line the same"]
        else:
            st, val = "fail", "no rpt.conf node"
            notes = [f"No rpt.conf node has {want}", "Audio between AllStar and Analog_Bridge cannot flow"]
        checks.append({"title": "USRP pair with rpt.conf", "value": val, "status": st, "notes": notes})

    return checks

def parse_analog_reflector(content: str) -> list:
    sections = _dvs_parse_sections(content)
    general  = sections.get("GENERAL", {})
    usrp     = sections.get("USRP",    {})

    callsign  = general.get("callsign", "").strip()
    node_id   = general.get("id",       "").strip()
    log_level = general.get("logLevel", "").strip()
    address   = usrp.get("address", "").strip()
    port      = usrp.get("port",    "").strip()

    cs_ok = bool(callsign) and callsign.upper() not in _RPT_DEF_CALLSIGNS
    id_ok = bool(node_id)  and node_id != _AB_DEF_DMR_ID

    checks = [
        {
            "title":  "Callsign",
            "value":  callsign if callsign else "not set",
            "status": "pass" if cs_ok else "fail",
            "notes":  None,
        },
        {
            "title":  "Node ID",
            "value":  node_id if node_id else "not set",
            "status": "pass" if id_ok else "fail",
            "notes":  "Default placeholder — set your DMR ID" if not id_ok else None,
        },
    ]
    if log_level:
        checks.append({
            "title":  "Log Level",
            "value":  log_level,
            "status": "info",
            "notes":  None,
        })
    if address:
        checks.append({
            "title":  "Listen Address",
            "value":  address,
            "status": "info",
            "notes":  None,
        })
    if port:
        checks.append({
            "title":  "USRP Port",
            "value":  port,
            "status": "info",
            "notes":  f"Port {port} — USRP clients connect here",
        })

    return checks

def parse_dvswitch_ini(content: str) -> list:
    sections = _dvs_parse_sections(content)
    checks: list = []

    for mode in _DVS_MODE_SECTIONS:
        sec = sections.get(mode)
        if not sec:
            continue

        checks.append({
            "title":  f"[{mode}]",
            "value":  _DVS_SECTION_LABELS.get(mode, ""),
            "status": "info",
            "notes":  None,
        })

        addr    = sec.get("address",  "").strip()
        tx_port = sec.get("txPort",   "").strip()
        rx_port = sec.get("rxPort",   "").strip()

        if addr:
            checks.append({"title": "Address", "value": addr,
                           "status": "info",   "notes": None})
        if tx_port:
            checks.append({"title": "TX Port", "value": tx_port,
                           "status": "info",   "notes": None})
        if rx_port:
            checks.append({"title": "RX Port", "value": rx_port,
                           "status": "info",   "notes": None})

        if mode == "STFU":
            server   = sec.get("BMAddress",   "").strip()
            password = sec.get("BMPassword",  "").strip()
            dmr_id   = sec.get("UserID",      "").strip()
            start_tg = sec.get("StartTG",     "").strip()
            ta       = sec.get("TalkerAlias", "").strip()

            server_ok = bool(server) and server != _DVS_DEF_SERVER
            dmr_id_ok = bool(dmr_id) and dmr_id != _DVS_DEF_DMR_ID

            checks.append({"title": "BM Server", "value": server if server else "not set",
                           "status": "pass" if server_ok else "fail", "notes": None})
            checks.append({"title": "Password",  "value": None,
                           "status": "pass" if password else "fail", "notes": None})
            checks.append({"title": "DMR ID",    "value": dmr_id if dmr_id else "not set",
                           "status": "pass" if dmr_id_ok else "fail", "notes": None})
            if start_tg:
                checks.append({"title": "Start TG",    "value": start_tg,
                               "status": "info", "notes": None})
            if ta:
                checks.append({"title": "Talker Alias", "value": ta,
                               "status": "info", "notes": None})

    if not checks:
        checks.append({"title": "Sections", "value": "No mode sections found",
                       "status": "fail",    "notes": None})
    return checks

def parse_mmdvm_bridge(content: str) -> list:
    sections = _dvs_parse_sections(content)
    general  = sections.get("GENERAL", {})

    callsign = general.get("Callsign", "").strip()
    dmr_id   = general.get("Id",       "").strip()

    callsign_ok = (bool(callsign)
                   and callsign.upper() not in _RPT_DEF_CALLSIGNS
                   and callsign.upper() != _MB_DEF_CALLSIGN)
    dmr_id_ok   = bool(dmr_id) and dmr_id != _MB_DEF_DMR_ID

    checks: list = []

    if not general:
        checks.append({"title": "Callsign", "value": "General section not found",
                       "status": "fail",    "notes": None})
        checks.append({"title": "DMR ID",   "value": "General section not found",
                       "status": "fail",    "notes": None})
        return checks

    checks.append({
        "title":  "Callsign",
        "value":  callsign if callsign else "not set",
        "status": "pass" if callsign_ok else "fail",
        "notes":  None,
    })
    checks.append({
        "title":  "DMR ID",
        "value":  dmr_id if dmr_id else "not set",
        "status": "pass" if dmr_id_ok else "fail",
        "notes":  None,
    })

    info_sec = sections.get("INFO", {})
    location = info_sec.get("Location",    "").strip()
    desc_val = info_sec.get("Description", "").strip()
    if location:
        checks.append({"title": "Location",    "value": location,
                       "status": "info",       "notes": None})
    if desc_val:
        checks.append({"title": "Description", "value": desc_val,
                       "status": "info",       "notes": None})

    checks.append({"title": "[Enabled Modes]", "value": "",
                   "status": "info",           "notes": None})
    found_any = False

    for sec_key, net_key, label in _MB_MODE_MAP:
        sec = sections.get(sec_key.upper(), {})
        net = sections.get(net_key.upper(), {})
        if sec.get("Enable", "0").strip() != "1":
            continue
        if net.get("Enable", "0").strip() != "1":
            continue
        found_any = True
        addr = ""
        for akey in _MB_ADDR_KEYS.get(net_key, ("Address",)):
            addr = net.get(akey, "").strip()
            if addr:
                break
        checks.append({
            "title":  label,
            "value":  addr if addr else "enabled (no address)",
            "status": "info",
            "notes":  None,
        })

    if not found_any:
        checks.append({
            "title":  "Modes",
            "value":  "none enabled",
            "status": "fail",
            "notes":  "Set Enable=1 in at least one mode section",
        })

    return checks

_DVSTXT_PREFIX_RE = re.compile(
    r'^(bm|tgif|dmrplus|other[12])'
    r'_(name|address|port)='
    r'(.*)$',
    re.IGNORECASE,
)

_DVSTXT_PWD_RE = re.compile(r'[^=]*password', re.IGNORECASE)

def parse_dvswitch_var_txt(content: str) -> list:
    nets: "dict[str, dict]" = {}

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        key_part = line.split('=', 1)[0] if '=' in line else ''
        if _DVSTXT_PWD_RE.search(key_part):
            continue

        m = _DVSTXT_PREFIX_RE.match(line)
        if not m:
            continue
        prefix, key, val = m.group(1).lower(), m.group(2).lower(), m.group(3).strip()
        if prefix not in nets:
            nets[prefix] = {}
        nets[prefix][key] = val

    _ORDER = ("bm", "tgif", "dmrplus", "other1", "other2")
    checks: list = []

    for prefix in _ORDER:
        nd = nets.get(prefix)
        if not nd:
            continue
        name    = nd.get("name",    "").strip()
        address = nd.get("address", "").strip()
        port    = nd.get("port",    "").strip()
        if not name and not address:
            continue
        addr_display = (f"{address}:{port}" if address and port
                        else address or "no address")
        checks.append({
            "title":  name or prefix.upper(),
            "value":  addr_display,
            "status": "pass" if address else "fail",
            "notes":  "Address not configured" if not address else None,
        })

    if not checks:
        checks.append({"title": "Networks", "value": "No networks configured",
                       "status": "fail",    "notes": None})
    return checks

_DVS_FILE_PARSERS: "dict[str, object]" = {
    "Analog_Bridge.ini":      parse_analog_bridge,
    "Analog_Reflector.ini":   parse_analog_reflector,
    "DVSwitch.ini":           parse_dvswitch_ini,
    "MMDVM_Bridge.ini":       parse_mmdvm_bridge,
    "var.txt":                parse_dvswitch_var_txt,
}

def parse_allmon3_ini(content: str) -> list:
    checks: list = []
    section = ""
    kv: "dict[str, str]" = {}

    def _flush(sec: str, kv: dict) -> None:
        if not sec or not sec.isdigit():
            return
        host = kv.get("host", "").strip()
        user = kv.get("user", "").strip()
        pw   = kv.get("pass", "").strip()
        checks.append({
            "title":  f"[{sec}]",
            "value":  host or "no host set",
            "status": "info",
            "notes":  None,
        })
        checks.append({
            "title":  "AMI User",
            "value":  user if user else "not set",
            "status": "pass" if user else "fail",
            "notes":  None,
        })
        checks.append({
            "title":  "AMI Pass",
            "value":  None,
            "status": "pass" if pw else "fail",
            "notes":  None,
        })

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        sm = _DVS_SECTION_RE.match(raw_line)
        if sm:
            _flush(section, kv)
            section, kv = sm.group(1).strip(), {}
            continue
        m = _DVS_KV_RE.match(raw_line)
        if m:
            kv[m.group(1)] = m.group(2).strip()
    _flush(section, kv)

    if not checks:
        checks.append({
            "title":  "Nodes",
            "value":  "No node stanzas found",
            "status": "fail",
            "notes":  None,
        })
    return checks

def parse_allmon3_web(content: str) -> list:
    sections = _dvs_parse_sections(content)
    web      = sections.get("WEB", {})
    checks: list = []

    if not web and not sections:
        checks.append({
            "title":  "Web",
            "value":  "No sections found",
            "status": "fail",
            "notes":  None,
        })
        return checks

    checks.append({
        "title":  "[web]",
        "value":  "",
        "status": "info",
        "notes":  None,
    })

    port = web.get("port", "").strip()
    if port:
        checks.append({
            "title":  "Port",
            "value":  port,
            "status": "info",
            "notes":  None,
        })

    bind = (web.get("bind_addr") or web.get("host") or "").strip()
    if bind:
        checks.append({
            "title":  "Bind Address",
            "value":  bind,
            "status": "info",
            "notes":  None,
        })

    for sec_label in ("syscmds", "node-overrides", "voter-titles"):
        if sec_label.upper().replace("-", "") in {k.replace("-", "") for k in sections}:
            checks.append({
                "title":  f"[{sec_label}]",
                "value":  "present",
                "status": "info",
                "notes":  None,
            })

    return checks

def parse_allmon3_users(content: str) -> list:
    count = sum(
        1 for line in content.splitlines()
        if line.strip() and not line.strip().startswith("#")
    )
    return [{
        "title":  "Accounts",
        "value":  f"{count} user{'s' if count != 1 else ''} defined",
        "status": "pass" if count > 0 else "fail",
        "notes":  None,
    }]

_ALLMON3_FILE_PARSERS: "dict[str, object]" = {
    "allmon3.ini": parse_allmon3_ini,
    "web.ini":     parse_allmon3_web,
    "users":       parse_allmon3_users,
}

def _route_asterisk_list(h: Handler) -> None:
    qs          = parse_qs(urlparse(h.path).query)
    include_all = qs.get("all", [""])[0] == "1"
    debug       = qs.get("debug", [""])[0] == "1"
    hidden_set  = _get_hidden_files()

    all_files = list_asterisk_files(include_hidden=True)
    files = []
    for f in all_files:
        if not include_all and f in hidden_set:
            continue
        content, err = read_asterisk_file(f)
        parser = _FILE_PARSERS.get(f)
        entry = {
            "name":        f,
            "hidden":      f in hidden_set,
            "checks":      parser(content) if (parser and not err) else [],
            "collapsible": f in _COLLAPSIBLE_CHECKS,
            "port_lines":  extract_port_lines(content),
            "read_error":  err,
        }
        if debug:
            entry["lines_sample"] = content.splitlines()[:40]
        files.append(entry)

    h.send_json({
        "ok":    True,
        "files": files,
        "dir":   str(_AST_DIR),
    })

def _route_asterisk_get(h: Handler) -> None:
    qs   = parse_qs(urlparse(h.path).query)
    name = qs.get("name", [""])[0].strip()

    if not validate_asterisk_filename(name):
        h.send_json({"ok": False, "message": f"Invalid filename: {name!r}"}, 400)
        return

    content, err = read_asterisk_file(name)
    if err:
        status = 404 if "not found" in err else 500
        h.send_json({"ok": False, "message": err}, status)
        return

    h.send_json({
        "ok":       True,
        "name":     name,
        "path":     str(_AST_DIR / name),
        "content":  content,
        "writable": os.geteuid() == 0,
    })

def _route_asterisk_post(h: Handler, data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "root required"}); return

    name    = str(data.get("name",    "")).strip()
    content = str(data.get("content", ""))

    if not validate_asterisk_filename(name):
        h.send_json({"ok": False, "message": f"Invalid filename: {name!r}"}, 400)
        return

    ok, msg = write_asterisk_file(name, content)
    _log(msg, stderr=not ok)
    h.send_json({
        "ok":      ok,
        "message": msg,
        "path":    str(_AST_DIR / name),
    }, 200 if ok else 500)

_PATHFILE_DVS = {
    "files":    _DVSWITCH_FILES,
    "parsers":  _DVS_FILE_PARSERS,
    "readonly": None,
}

_PATHFILE_ALLMON3 = {
    "files":    _ALLMON3_FILES,
    "parsers":  _ALLMON3_FILE_PARSERS,
    "readonly": _ALLMON3_READONLY,
    "ro_msg":   "is read-only — use allmon3-passwd to manage users",
}

def _route_dvswitch_list(h: Handler) -> None:
    _pathfile_list(h, _PATHFILE_DVS)

def _route_dvswitch_get(h: Handler) -> None:
    _pathfile_get(h, _PATHFILE_DVS)

def _route_dvswitch_post(h: Handler, data: dict) -> None:
    _pathfile_post(h, data, _PATHFILE_DVS)

def _route_allmon3_list(h: Handler) -> None:
    _pathfile_list(h, _PATHFILE_ALLMON3)

def _route_allmon3_get(h: Handler) -> None:
    _pathfile_get(h, _PATHFILE_ALLMON3)

def _route_allmon3_post(h: Handler, data: dict) -> None:
    _pathfile_post(h, data, _PATHFILE_ALLMON3)

_PHONE_SECTIONS: list = []

def _phone_section(sid: str, title: str):
    def deco(fn):
        _PHONE_SECTIONS.append((sid, title, fn))
        return fn
    return deco

def _ph_goto_targets(plan: dict, ctx_name: str) -> "tuple[set, list]":
    found, prefixes = set(), []
    for e in plan.get(ctx_name, []):
        for st in e["steps"]:
            for m in re.finditer(r"Goto(?:If)?\(.*?\b([\w\-${}]+),[^,()?]*,[^,()?]*\)", st["raw"]):
                t = m.group(1)
                if "${" in t:
                    prefixes.append(t.split("${")[0])
                else:
                    found.add(t)
    return found, prefixes

def _ph_func_codes(secs: list, stanza: str) -> dict:
    res = {"autopatch": None, "hangup": [], "patch_on": "", "patch_off": "", "ptt": ""}
    for s in secs:
        if s["name"] != stanza:
            continue
        for k, v, *_ in s["kv"]:
            code, low = k.strip(), v.strip().lower()
            if low.startswith("autopatchup"):
                res["autopatch"] = {"code": code, "options": _ph_parse_autopatch(v)}
            elif low.startswith("autopatchdn"):
                res["hangup"].append({"code": code, "kind": "autopatchdn"})
            elif low.startswith("cmd,") and "hangup" in low:
                res["hangup"].append({"code": code, "kind": "script",
                                      "path": v.split(",", 1)[1].strip().split()[0]})
            elif re.match(r"cop\s*,\s*9\s*$", low):
                res["patch_on"] = code
            elif re.match(r"cop\s*,\s*10\s*$", low):
                res["patch_off"] = code
            elif re.match(r"cop\s*,\s*6\s*$", low):
                res["ptt"] = code
    return res

_PH_SIMPLEX_KEYS = ("voxtimeout", "voxrecover", "simplexpatchdelay", "simplexphonedelay")

@_phone_section("node", "Autopatch node")
def _phone_sec_node(ctx: dict) -> dict:
    secs = ctx["conf"]["rpt.conf"]
    if "rpt.conf" not in ctx["files"]:
        return {"found": False, "note": "rpt.conf not found", "nodes": []}
    listed = {}
    for s in secs:
        if s["name"] == "nodes":
            for k, v, *_ in s["kv"]:
                listed[k.strip()] = v.strip()
    dash_node = ctx["dash"]["phone_node"]
    nodes = []
    for name in dict.fromkeys(s["name"] for s in secs):
        if not name.isdigit():
            continue
        if any(s["name"] == name and s["is_template"] for s in secs):
            continue
        kv, managed, fname = _ph_resolve(secs, name)
        fstanza = kv.get("functions", "functions")
        stanzas = [kv.get(k, fstanza) for k in ("functions", "phone_functions", "link_functions")]
        codes = None
        for st_name in dict.fromkeys(stanzas):
            c = _ph_func_codes(secs, st_name)
            if c["autopatch"]:
                codes, fstanza = c, st_name
                break
        pnodes = ctx["dash"].get("phone_nodes") or {}
        is_pb = name == dash_node or name in pnodes
        if codes is None and not is_pb:
            continue
        codes = codes or _ph_func_codes(secs, fstanza)
        duplex = kv.get("duplex", "2").split()[0] if kv.get("duplex") else "2"
        rx = kv.get("rxchannel", "").split()[0] if kv.get("rxchannel") else ""
        entry = {
            "node": name,
            "role": (f"phone node for {pnodes[name]}" if name in pnodes else
                     "phone bridge" if name == dash_node else
                     "autopatch on a radio node" if rx and "pseudo" not in rx.lower() else
                     "autopatch node"),
            "is_phone_bridge": is_pb,
            "in_nodes_list": name in listed,
            "nodes_line": listed.get(name, ""),
            "rxchannel": rx,
            "duplex": duplex,
            "mode": "simplex (VOX)" if duplex in ("0", "1") else "full duplex",
            "context": kv.get("context", "").split()[0] if kv.get("context") else "",
            "callerid": kv.get("callerid", ""),
            "functions": fstanza,
            "autopatch": codes["autopatch"],
            "hangup": codes["hangup"],
            "patch_on": codes["patch_on"], "patch_off": codes["patch_off"], "ptt": codes["ptt"],
            "simplex": {k: kv[k].split()[0] for k in _PH_SIMPLEX_KEYS if kv.get(k)},
            "managed_by": "dashboard" if managed else "hand-made",
            "file": fname,
        }
        nodes.append(entry)
    return {"found": bool(nodes), "nodes": nodes,
            "note": "" if nodes else "No node has an autopatch code (autopatchup) in its function list",
            "dashboard_phone_node": dash_node}

@_phone_section("networks", "Phone networks")
def _phone_sec_networks(ctx: dict) -> dict:
    targets = ctx["dial_targets"]
    names = ctx["dash"]["names"]
    nets = []
    iax_secs = ctx["conf"]["iax.conf"]
    regs = []
    for s in iax_secs:
        for k, v, *_ in s["kv"]:
            if k.strip().lower() == "register":
                r = _ph_parse_iax_reg(v)
                if r:
                    regs.append(r)
    by_name: dict = {}
    for s in iax_secs:
        if not s["name"] or s["is_template"] or s["name"].lower() == "general":
            continue
        by_name.setdefault(s["name"], []).append(s)
    for name, group in by_name.items():
        kv = _ph_last(group)
        if kv.get("type", "").lower() not in ("peer", "friend", "user"):
            continue
        if not (name.startswith("dvs") or ("iax2", name) in targets):
            continue
        user = kv.get("username", "") or name
        reg = next((r for r in regs if r["user"] == user), None)
        nets.append({
            "id": name, "name": names.get(name, name), "type": "iax2",
            "type_label": "IAX2", "host": kv.get("host", reg["host"] if reg else ""),
            "port": kv.get("port", reg["port"] if reg else ""), "username": user,
            "context": kv.get("context", ""), "registers": bool(reg),
            "has_secret": bool(kv.get("secret") or kv.get("auth")),
            "source": _ph_source(name, any(g["managed"] for g in group)),
            "file": group[0]["file"], "caller_id": ""})
    psecs = ctx["conf"]["pjsip.conf"]
    typed: dict = {}
    for s in psecs:
        if s["name"] and not s["is_template"]:
            t = _ph_last([s]).get("type", "").lower()
            typed.setdefault(t, []).append(s)
    def find(t, name):
        return [s for s in typed.get(t, []) if s["name"] == name]
    transports = []
    for s in typed.get("transport", []):
        kv = _ph_last([s])
        transports.append({"name": s["name"], "protocol": kv.get("protocol", ""), "bind": kv.get("bind", ""),
                           "local_net": ", ".join(v for k, v, *_ in s["kv"] if k.strip().lower() == "local_net"),
                           "external_signaling": kv.get("external_signaling_address", ""),
                           "external_media": kv.get("external_media_address", ""),
                           "source": _ph_source(s["name"], s["managed"])})
    for ep in typed.get("endpoint", []):
        name = ep["name"]
        if not (name.startswith("dvs") or ("pjsip", name) in targets):
            continue
        kv = _ph_last([ep])
        host, port = "", ""
        for aor_name in [a.strip() for a in kv.get("aors", name).split(",") if a.strip()]:
            aor = find("aor", aor_name)
            if aor:
                contact = _ph_last(aor).get("contact", "")
                if contact:
                    host, port = _ph_uri_host(contact)
                    break
        out_auth = kv.get("outbound_auth", "")
        user = ""
        if out_auth:
            au = find("auth", out_auth)
            user = _ph_last(au).get("username", "") if au else ""
        reg = None
        for r in typed.get("registration", []):
            if out_auth and _ph_last([r]).get("outbound_auth", "") == out_auth:
                reg = r
                break
        idn = [i for i in typed.get("identify", []) if _ph_last([i]).get("endpoint", "") == name]
        match = _ph_last(idn).get("match", "") if idn else ""
        cid = re.sub(r"[^0-9+]", "", kv.get("callerid", ""))
        dtype = next((d["type"] for d in ctx["dash"]["networks"] if d["id"] == name), "")
        nets.append({
            "id": name, "name": names.get(name, name),
            "type": "sip" if (out_auth or reg) else "sip_ip",
            "type_label": _PH_EXT_LBL.get(dtype) or ("SIP with login" if (out_auth or reg) else "SIP by IP address"),
            "host": host or (_ph_uri_host(_ph_last([reg]).get("server_uri", ""))[0] if reg else ""),
            "port": port, "username": user, "context": kv.get("context", ""),
            "registers": reg is not None, "reg_name": reg["name"] if reg else "",
            "has_secret": bool(out_auth and find("auth", out_auth)
                                                              and _ph_last(find("auth", out_auth)).get("password")),
            "match": match, "caller_id": cid,
            "source": _ph_source(name, ep["managed"]), "file": ep["file"]})
    return {"found": bool(nets), "networks": nets, "transports": transports,
            "active": ctx["dash"]["active"],
            "note": "" if nets else "No SIP or IAX2 provider is dialed by the dialplan yet"}

_PH_EXT_LBL = {"hoip": "Hams Over IP", "awire": "AmateurWire"}

_PH_FORMATS = {"${EXTEN:1}": "10 digits", "${EXTEN}": "11 digits as dialed", "+${EXTEN}": "+1 and 10 digits"}

def _ph_first_dial(entries: list) -> str:
    for e in entries:
        for st in e["steps"]:
            if st["app"].lower() == "dial":
                return st["args"].split(",")[0].strip()
    return ""

def _ph_lines(entries: list, limit: int = 40) -> "tuple[list, bool]":
    lines = []
    for e in entries:
        steps = " ; ".join(_ph_mask(st["raw"]) for st in e["steps"][:3])
        more = " ; …" if len(e["steps"]) > 3 else ""
        lines.append(f"{e['pattern']}  →  {steps}{more}")
    return lines[:limit], len(lines) > limit

def _ph_outgoing(plan: dict, cname: str) -> dict:
    entries = plan.get(cname, [])
    out = {"context": cname, "kind": "generic", "network": "", "lines": [], "truncated": False,
           "dials": []}
    m = re.match(r"^dvs-net-(.+?)(-r)?$", cname)
    if m and not m.group(2):
        nid = m.group(1)
        routed = plan.get(f"dvs-net-{nid}-r", [])
        ext_only = any(e["pattern"] == "_X." and _ph_first_dial([e]) for e in entries)
        main = [e for e in entries if e["pattern"] == "_X."] if ext_only else []
        dial = _ph_first_dial(routed or main or entries)
        fmt = "as dialed"
        if not ext_only:
            fm = re.search(r"(\+?\$\{EXTEN(?::1)?\})", dial)
            fmt = _PH_FORMATS.get(fm.group(1), "") if fm else ""
        out.update({
            "kind": "dashboard", "network": nid,
            "dialing": "extensions" if ext_only else "phone numbers",
            "e911": any(e["pattern"] == "911" and _ph_first_dial([e]) for e in entries),
            "international": any(e["pattern"].startswith("_011") and _ph_first_dial([e]) for e in entries),
            "number_format": fmt,
            "dials": [dial] if dial else [],
            "blocked": [e["pattern"] for e in routed
                        if e["steps"] and "dvs-invalid" in e["steps"][0]["raw"]],
            "dial": dial})
    elif not (cname.startswith("dvs-net-") and cname.endswith("-r")):
        out["lines"], out["truncated"] = _ph_lines(entries)
        out["dials"] = sorted({_ph_first_dial([e]) for e in entries if _ph_first_dial([e])})
    return out

def _ph_incoming(plan: dict, net: dict) -> dict:
    cname = net.get("context", "")
    entries = plan.get(cname, [])
    res = {"network": net["id"], "context": cname, "defined": bool(entries), "mode": "none",
           "trusted_last4": [], "connects_node": "", "busy_when_tab_closed": False, "lines": []}
    if not cname:
        res["mode"] = "no context set on the provider account"
        return res
    if not entries:
        res["mode"] = "context missing from the dialplan"
        return res
    steps = [st for e in entries for st in e["steps"]]
    apps = [st["app"].lower() for st in steps]
    trusted = []
    for st in steps:
        for d in re.findall(r'CALLERID\(num\)(?::-\d+)?\}?"?\s*=\s*"\+?(\d{4,15})"', st["raw"]):
            trusted.append(d[-4:])
    node = ""
    for st in steps:
        if st["app"].lower() == "rpt":
            node = re.split(r"[,|]", st["args"])[0].strip()
            break
    if "read" in apps:
        res["mode"] = "asks for a PIN"
    elif "rpt" in apps and trusted:
        res["mode"] = "only trusted numbers (no PIN)"
    elif "rpt" in apps:
        res["mode"] = "connects straight to the node (no PIN)"
    elif apps and all(a in ("hangup", "noop") for a in apps):
        res["mode"] = "hangs up"
    else:
        res["mode"] = "custom"
    res["trusted_last4"] = list(dict.fromkeys(trusted))
    res["connects_node"] = node
    res["busy_when_tab_closed"] = any("dvsphone/open" in st["raw"] for st in steps)
    if res["mode"] in ("custom", "connects straight to the node (no PIN)", "only trusted numbers (no PIN)"):
        res["lines"], _t = _ph_lines(entries, 20)
    return res

@_phone_section("dialing", "Dialing rules")
def _phone_sec_dialing(ctx: dict) -> dict:
    plan = ctx["dialplan"]
    if "extensions.conf" not in ctx["files"]:
        return {"found": False, "note": "extensions.conf not found", "outgoing": [], "incoming": []}
    start = set()
    for nd in _phone_sec_node(ctx)["nodes"]:
        if nd["autopatch"] and nd["autopatch"]["options"].get("context"):
            start.add(nd["autopatch"]["options"]["context"])
        if nd["context"]:
            start.add(nd["context"])
    seen, queue, order = set(), sorted(start), []
    while queue and len(order) < 60:
        c = queue.pop(0)
        if c in seen:
            continue
        seen.add(c)
        order.append(c)
        found, prefixes = _ph_goto_targets(plan, c)
        for t in sorted(found):
            if t not in seen:
                queue.append(t)
        for p in prefixes:
            queue.extend(sorted(x for x in plan if x.startswith(p) and x not in seen))
    outgoing = [_ph_outgoing(plan, c) for c in order
                if c in plan and c != "dvs-invalid" and not re.match(r"^dvs-net-.+-r$", c)]
    missing = sorted(c for c in start if c not in plan)
    nets = _phone_sec_networks(ctx)["networks"]
    incoming = [_ph_incoming(plan, n) for n in nets]
    return {"found": bool(outgoing), "outgoing": outgoing, "incoming": incoming,
            "missing_contexts": missing, "start_contexts": sorted(start),
            "note": "" if outgoing else "No dialing context is reachable from an autopatch code"}

_PH_RANK = {"idle": 0, "dialing": 1, "incoming": 2, "in_call": 3}

def _ph_peer_of(channel: str) -> str:
    name = channel.split("/", 1)[1] if "/" in channel else channel
    return name.rsplit("-", 1)[0]

def _ph_last4(v: str) -> str:
    d = re.sub(r"\D", "", v or "")
    return d[-4:] if len(d) >= 4 else ""

def _ph_reg_states(nets: list) -> list:
    iax_txt = pj_txt = ""
    if any(n["type"] == "iax2" and n["registers"] for n in nets):
        iax_txt = _ph_cli("iax2 show registry")
    if any(n["type"] != "iax2" and n["registers"] for n in nets):
        pj_txt = _ph_cli("pjsip show registrations")
    out = []
    for n in nets:
        rec = {"id": n["id"], "name": n["name"], "registered": None, "state": "no login needed"}
        if n["registers"] and n["type"] == "iax2":
            line = next((l for l in iax_txt.splitlines()
                         if re.search(r"(^|\s)" + re.escape(n["username"]) + r"(\s|$)", l)), "")
            m = re.search(r"\s\d+\s+([A-Za-z][A-Za-z. ]*?)\s*$", line)
            rec["state"] = m.group(1) if m else "not listed"
            rec["registered"] = bool(m) and rec["state"].lower().startswith("registered")
        elif n["registers"]:
            line = next((l for l in pj_txt.splitlines()
                         if n.get("reg_name") and l.strip().startswith(n["reg_name"] + "/")), "")
            parts = re.split(r"\s{2,}", line.strip()) if line else []
            rec["state"] = parts[2] if len(parts) >= 3 else "not listed"
            rec["registered"] = rec["state"].lower().startswith("registered")
        out.append(rec)
    return out

@_phone_section("live", "Live status")
def _phone_sec_live(ctx: dict) -> dict:
    if not _ph_ast_running():
        return {"found": False, "running": False, "note": "Asterisk isn't running", "calls": [],
                "registrations": [], "state": "idle"}
    nets = _phone_sec_networks(ctx)["networks"]
    ids = {n["id"]: n for n in nets}
    calls, state, who = [], "idle", ""
    for line in _ph_cli("core show channels concise", 5).splitlines():
        p = line.split("!")
        if len(p) < 8 or "/" not in p[0]:
            continue
        peer = _ph_peer_of(p[0])
        if peer not in ids and not peer.startswith("dvs"):
            continue
        net = ids.get(peer)
        incoming = p[5].lower() != "appdial" and (
            p[1].startswith("dvs-in-") or bool(net and net["context"] and p[1] == net["context"]))
        who_ = _ph_last4(p[7]) if incoming else ""
        if incoming:
            cur = "in_call" if (p[4] == "Up" and p[5].lower() == "rpt") else "incoming"
        else:
            cur = "in_call" if p[4] == "Up" else "dialing"
        secs = int(p[11]) if len(p) > 11 and p[11].isdigit() else 0
        calls.append({"channel": p[0], "network": peer, "network_name": net["name"] if net else peer,
                      "direction": "incoming" if incoming else "outgoing", "state": cur,
                      "channel_state": p[4], "app": p[5], "seconds": secs,
                      "who_last4": who_})
        if _PH_RANK[cur] > _PH_RANK[state]:
            state, who = cur, who_
    flags = {}
    for line in _ph_cli("database show dvsphone", 4).splitlines():
        m = re.match(r"^/dvsphone/(\w+)\s*:\s*(.*)$", line.strip())
        if m:
            flags[m.group(1)] = m.group(2).strip()[:40]
    phone_node, main_node = ctx["dash"]["live_phone_node"], ctx["dash"]["asl_node"]
    pnodes = ctx["dash"].get("phone_nodes") or {}
    linked = None
    others: list = []
    if phone_node and main_node:
        out = _ph_cli(f"rpt show variables {main_node}", 4)
        m = re.search(r"RPT_LINKS\s*=\s*(.+)", out, re.I)
        toks = []
        if m:
            raw = m.group(1).strip()
            if "," in raw:
                raw = raw[raw.index(",") + 1:]
            toks = [t[1:] if t[:1] in "TR" and t[1:].isdigit() else t for t in re.split(r"[,\s]+", raw) if t]
        linked = phone_node in toks if m else None
        others = [x for x in toks if x in pnodes and x != phone_node]
    return {"found": True, "running": True, "state": state, "who_last4": who, "calls": calls,
            "registrations": _ph_reg_states(nets), "flags": flags,
            "phone_node": {"node": phone_node, "main_node": main_node, "linked": linked,
                           "network": pnodes.get(phone_node, ""), "others_linked": others}}

_PH_CONFS = ("rpt.conf", "extensions.conf", "iax.conf", "pjsip.conf", "modules.conf")

def _ph_check(cid: str, title: str, status: str, value: str, note: str = "") -> dict:
    return {"id": cid, "title": title, "status": status, "value": value, "note": note or None, "url": None}

_PH_NEEDED_MODS = re.compile(r"^(chan_pjsip|chan_iax2|res_pjsip\w*|res_pjproject|res_rtp_asterisk|res_sorcery\w*|"
                             r"func_pjsip_endpoint|func_sorcery|bridge_\w+|chan_bridge_media|app_read|app_senddtmf|"
                             r"app_chanspy|app_playback|format_pcm)\.so$")

def _ph_sip_required(nets: list) -> list:
    sip = [n for n in nets if n["type"] != "iax2"]
    need = ["chan_pjsip.so", "res_pjsip.so", "res_pjsip_session.so", "res_pjsip_sdp_rtp.so",
            "res_pjproject.so", "res_rtp_asterisk.so"]
    if any(n["type"] == "sip_ip" or n.get("match") for n in sip):
        need.append("res_pjsip_endpoint_identifier_ip.so")
    if any(n["type"] == "sip" for n in sip):
        need.append("res_pjsip_outbound_authenticator_digest.so")
    if any(n["registers"] for n in sip):
        need.append("res_pjsip_outbound_registration.so")
    return need

def _ph_modules_conf_check(ctx: dict, nets: list):
    try:
        text = (ctx["dir"] / "modules.conf").read_text(errors="replace")
    except OSError:
        return None
    sip = any(n["type"] != "iax2" for n in nets)
    section, block_sec, blocked, found_block = "", "", [], False
    card_off, in_card = [], False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith(_PM_BEGIN_PFX):
            in_card = True
            continue
        if line.startswith(_PM_END_PFX):
            in_card = False
            continue
        if in_card:
            m = re.match(r"^noload\s*=>?\s*(\S+)", _PH_CMT_RE.sub("", line).strip(), re.I)
            if m:
                card_off.append(m.group(1))
            continue
        if line.startswith(_PH_BEGIN):
            block_sec, found_block = section, True
            continue
        if line.startswith(_PH_END):
            continue
        line = _PH_CMT_RE.sub("", line).strip()
        m = re.match(r"^\[([^\]]+)\]", line)
        if m:
            section = m.group(1).strip().lower()
            continue
        m = re.match(r"^noload\s*=>?\s*(\S+)", line, re.I)
        if m and _PH_NEEDED_MODS.match(m.group(1)):
            name = m.group(1)
            pj = name.startswith(("chan_pjsip", "res_pjsip", "res_pjproject", "res_rtp_asterisk",
                                  "res_sorcery", "func_pjsip", "func_sorcery"))
            if pj and not sip:
                continue
            blocked.append(name)
    if blocked:
        return _ph_check("noload", "modules.conf", "warn", "noload " + ", ".join(sorted(set(blocked))[:6]),
                         "A noload line can keep a module the phone setup needs from loading -- remove it")
    if card_off and not blocked:
        return _ph_check("noload", "modules.conf", "info", "turned off on the Autopatch modules card: "
                         + ", ".join(sorted(set(card_off))[:6]))
    if found_block and block_sec != "modules":
        where = f"[{block_sec}]" if block_sec else "no stanza at all"
        return _ph_check("noload", "modules.conf", "warn", f"phone module lines are in {where}, not [modules]",
                         "ASL3's SIP guide puts them in the [modules] stanza, just above [global]")
    if found_block:
        return _ph_check("noload", "modules.conf", "ok", "phone module lines are in [modules]; no noload in the way")
    return None

def _phone_health_nodes(C, ctx, dash_node, nodes, pnodes):
    want = [(nd_, f"Phone node {nd_} ({nm})") for nd_, nm in pnodes.items()]
    if dash_node and not want:
        want = [(dash_node, f"Phone bridge {dash_node}")]
    for i_, (pn_, title) in enumerate(want):
        cid = "node" if i_ == 0 else f"node{i_ + 1}"
        nd = next((n for n in nodes if n["node"] == pn_), None)
        if nd is None:
            C.append(_ph_check(cid, title, "fail", "not set up in rpt.conf",
                               "Dashboard Edit page → Phone → Save Phone writes it"))
        else:
            gaps = [t for ok_, t in ((nd["in_nodes_list"], "not in [nodes]"),
                                     (bool(nd["autopatch"]), "no autopatch code"),
                                     (bool(nd["hangup"]), "no hang-up code")) if not ok_]
            C.append(_ph_check(cid, title, "fail" if gaps else "ok",
                               ", ".join(gaps) if gaps else "set up (" + nd["mode"] + ")"))
    if not want and not nodes:
        C.append(_ph_check("node", "Autopatch", "info", "no autopatch code in rpt.conf"))
    elif not want:
        C.append(_ph_check("node", "Autopatch node", "ok", ", ".join(n["node"] for n in nodes)))
    for n in nodes:
        defs = [x for x in ctx["conf"]["rpt.conf"] if x["name"] == n["node"] and not x["is_template"]]
        if len({x["managed"] for x in defs}) > 1:
            C.append(_ph_check("dupnode", f"Node {n['node']}", "fail", "defined twice in rpt.conf",
                               "One copy was written by hand and one by the dashboard; remove the hand-made one"))

def _phone_health_files(C, ctx, dial_sec):
    for c in dial_sec.get("missing_contexts", []):
        C.append(_ph_check("ctx", f"Dialing context {c}", "fail", "not in extensions.conf",
                           "The autopatch code points at a context that doesn't exist"))
    plan = ctx["dialplan"]
    iax_names = {x["name"] for x in ctx["conf"]["iax.conf"] if x["name"]}
    pj_names = {x["name"] for x in ctx["conf"]["pjsip.conf"] if x["name"]}
    dangling = sorted(f"{t.upper()}/{p}" for t, p in ctx["dial_targets"]
                      if (t == "iax2" and p not in iax_names) or (t == "pjsip" and p not in pj_names))
    if dangling:
        C.append(_ph_check("dangling", "Providers the dialplan dials", "fail", ", ".join(dangling) + " not defined",
                           "extensions.conf dials an account that iax.conf / pjsip.conf doesn't have"))
    elif ctx["dial_targets"]:
        C.append(_ph_check("dangling", "Providers the dialplan dials", "ok", "all defined"))
    disk = sorted(p.name for p in ctx["dir"].glob("dvs_phone_*.conf")) if ctx["dir"].is_dir() else []
    loose = [f for f in disk if f not in ctx["files"]]
    absent = [f for f in ctx["missing"] if f.startswith("dvs_phone_")]
    if loose:
        C.append(_ph_check("includes", "Dashboard phone files", "fail", ", ".join(loose) + " not included",
                           "The file exists but nothing includes it -- Save Phone on the dashboard Edit page (v9.2.1 or later) removes it; delete a file you made yourself by hand"))
    elif absent:
        C.append(_ph_check("includes", "Dashboard phone files", "warn", ", ".join(absent) + " missing",
                           "An #tryinclude points at a file that isn't there (Asterisk skips it silently)"))
    elif disk:
        C.append(_ph_check("includes", "Dashboard phone files", "ok", f"{len(disk)} files, all included"))
    bad = []
    for f in _PH_CONFS:
        try:
            txt = (ctx["dir"] / f).read_text(errors="replace")
        except OSError:
            continue
        if txt.count(_PH_BEGIN) != txt.count(_PH_END):
            bad.append(f)
    if bad:
        C.append(_ph_check("markers", "Dashboard marker blocks", "fail", "unbalanced in " + ", ".join(bad),
                           "A '>>> dvs-phone' or '<<< dvs-phone' line was deleted; the dashboard can't update that file safely"))
    elif any(g["managed"] for t in ctx["conf"].values() for g in t):
        C.append(_ph_check("markers", "Dashboard marker blocks", "ok", "balanced"))
    return plan

def _phone_health_live(C, ctx, dial_sec, nets, nodes, running):
    if running:
        if any(n["type"] != "iax2" for n in nets):
            listing = "\n".join(_ph_cli(f"module show like {p}") for p in
                                ("chan_pjsip", "res_pjsip", "res_pjproject", "res_rtp_asterisk"))
            need = _ph_sip_required(nets)
            missing = [mod for mod in need if not _ph_module_running(listing, mod)]
            C.append(_ph_check("pjsip", "SIP modules", "fail" if missing else "ok",
                               ("not running: " + ", ".join(missing[:4]) + (" …" if len(missing) > 4 else ""))
                               if missing else f"all {len(need)} running",
                               "Restart Asterisk once (dashboard Edit page → tick 'Restart Asterisk if needed' → Save Phone)"
                               if missing else ""))
        if any(n["type"] == "iax2" for n in nets):
            loaded = _ph_module_running(_ph_cli("module show like chan_iax2"), "chan_iax2.so")
            C.append(_ph_check("iax2", "IAX2 module", "ok" if loaded else "fail",
                               "running" if loaded else "chan_iax2 is not running"))
        listing = "\n".join(_ph_cli(f"module show like {p}") for p in ("bridge_", "chan_bridge_media", "app_read"))
        need = ["bridge_softmix.so", "bridge_simple.so", "chan_bridge_media.so"]
        if any(i["mode"] == "asks for a PIN" for i in dial_sec.get("incoming", [])):
            need.append("app_read.so")
        missing = [mod for mod in need if not _ph_module_running(listing, mod)]
        C.append(_ph_check("bridges", "Call modules", "fail" if missing else "ok",
                           ("not running: " + ", ".join(missing)) if missing else "bridge modules running",
                           "Save Phone on the dashboard's Edit page loads them" if missing else ""))
        tone = _ph_module_running(_ph_cli("module show like app_senddtmf"), "app_senddtmf.so")
        C.append(_ph_check("tones", "Tone module", "ok" if tone else "warn",
                           "running" if tone else "app_senddtmf is not running",
                           "" if tone else "The dashboard's *99, # and keypad buttons need it -- Save Phone "
                                           "on the dashboard's Edit page (v9.3.0 or later) loads it"))
        if ctx["dash"].get("tone_path") == "sound":
            listing = "\n".join(_ph_cli(f"module show like {p}") for p in ("app_chanspy", "app_playback", "format_pcm"))
            gone = [m for m in ("app_chanspy.so", "app_playback.so", "format_pcm.so")
                    if not _ph_module_running(listing, m)]
            C.append(_ph_check("tonesound", "Tones as sound", "warn" if gone else "ok",
                               ("not running: " + ", ".join(gone)) if gone else "player modules running",
                               "The dashboard's keypad is set to send tones as sound -- Save Phone on the "
                               "dashboard's Edit page (v9.3.16 or later) loads these" if gone else ""))
        tcodes = sorted({k.strip() for x in ctx["conf"]["rpt.conf"] for k, v, *_ in x["kv"]
                         if "dvs_phone_tonecode" in v and k.strip().isdigit()})
        if tcodes:
            C.append(_ph_check("radiocodes", "Radio tone codes", "info", ", ".join("*" + c for c in tcodes) + " set up",
                               "During a call: *980 sends *, *981 #, *982 *99"))
        for n in nodes:
            up = "RPT_" in _ph_cli(f"rpt show variables {n['node']}", 4).upper()
            C.append(_ph_check("nodeup", f"Node {n['node']} in app_rpt", "ok" if up else "fail",
                               "running" if up else "not running",
                               "" if up else "rpt.conf has it but app_rpt hasn't loaded it: run 'module reload app_rpt' "
                                             "in the Asterisk console, or restart Asterisk"))

def _phone_health_routes(C, ctx, dial_sec, nets, nodes, plan, running):
    check = _ph_modules_conf_check(ctx, nets)
    if check:
        C.append(check)
    scripts: dict = {}
    for n in nodes:
        for h in n["hangup"]:
            if h["kind"] == "script":
                scripts.setdefault(h["path"], ("Hang-up script", set(), "can't hang up phone calls"))[1].add("*" + h["code"])
    for x in ctx["conf"]["rpt.conf"]:
        for k, v, *_ in x["kv"]:
            if "dvs_phone_tonecode" in v and v.strip().lower().startswith("cmd,") and k.strip().isdigit():
                p = v.split(",", 1)[1].strip().split()[0]
                scripts.setdefault(p, ("Radio tone script", set(), "send nothing into the call"))[1].add("*" + k.strip())
    for exts in plan.values():
        for e in exts:
            for st in e["steps"]:
                m = re.match(r"\s*(/\S*dvs_phone_dialreq)\b", st["args"]) if st["app"].lower() == "system" else None
                if m:
                    scripts.setdefault(m.group(1), ("Radio dial script", {"*61"}, "does nothing"))
    for path, (title, codes, broken) in sorted(scripts.items()):
        used = ", ".join(sorted(codes))
        p = Path(path)
        try:
            st = p.stat()
            exe = os.access(p, os.X_OK)
            worldw = bool(st.st_mode & 0o002)
        except OSError:
            C.append(_ph_check("script", title, "fail", f"{path} missing",
                               f"Without it {used} {broken} -- Save Phone on the dashboard's Edit page writes it"))
            continue
        problem = "not executable" if not exe else ("world-writable" if worldw else "")
        C.append(_ph_check("script", title, "fail" if problem else "ok",
                           f"{path} {problem}".strip() if problem else f"present and runnable ({used})"))
    for n in nets:
        if n["type"] != "sip_ip" and not n["has_secret"]:
            C.append(_ph_check("secret", f"{n['name']}", "fail", "no password set",
                               "The account has no secret / password line"))
    if running and nets:
        for r in _ph_reg_states(nets):
            if r["registered"] is None:
                continue
            C.append(_ph_check("reg", f"{r['name']} sign-in", "ok" if r["registered"] else "fail", r["state"],
                               "" if r["registered"] else "Check the username, password and server on the Edit page"))
    if any(n["type"] != "iax2" for n in nets):
        port = _ph_sip_port(ctx)
        fc = _ph_fw_check("firewall", "Pi firewall (SIP)", _ph_fw_cover(_ph_fw_ctx(ctx), port, port),
                          f"UDP {port}", _ph_fw_fix(ctx, f"UDP {port}"))
        if not fc["note"]:
            fc["note"] = (f"If incoming calls don't arrive, forward UDP {port} on your router to the Pi "
                          f"(signing in usually keeps it open without that)")
        C.append(fc)
    for o in dial_sec.get("outgoing", []):
        if o["kind"] == "dashboard" and o.get("e911"):
            C.append(_ph_check("e911", f"911 on {ctx['dash']['names'].get(o['network'], o['network'])}", "info",
                               "911 is allowed", "Only safe if E911 is set up with that provider"))
    for o in dial_sec.get("outgoing", []):
        if o["kind"] != "generic":
            continue
        for e in plan.get(o["context"], []):
            if e["pattern"] in ("_X.", "_.", "_X!", "_.!") and any(st["app"].lower() == "dial" for st in e["steps"]):
                C.append(_ph_check("openpat", f"Context {o['context']}", "warn", f"pattern {e['pattern']} dials any number",
                                   "Anything the radio user dials goes to the provider -- limit it to real number shapes"))
                break
    for i in dial_sec.get("incoming", []):
        if i["mode"].startswith("connects straight"):
            C.append(_ph_check("nopin", f"Incoming on {ctx['dash']['names'].get(i['network'], i['network'])}", "warn", "no PIN",
                               "Anyone who dials the number can talk on the air" +
                               (" while the dashboard Phone tab is open" if i["busy_when_tab_closed"] else "")))
    if running:
        flags = {}
        for line in _ph_cli("database show dvsphone", 4).splitlines():
            m = re.match(r"^/dvsphone/(\w+)\s*:\s*(.*)$", line.strip())
            if m:
                flags[m.group(1)] = m.group(2).strip()
        if flags.get("patch") == "0":
            C.append(_ph_check("patch", "Phone patch", "warn", "off", "Dialing is blocked until the dashboard turns it on"))

@_phone_section("health", "Health checks")
def _phone_sec_health(ctx: dict) -> dict:
    C: list = []
    running = _ph_ast_running()
    C.append(_ph_check("asterisk", "Asterisk", "ok" if running else "fail",
                       "running" if running else "not running",
                       "" if running else "Start it: systemctl start asterisk"))
    nodes_sec = _phone_sec_node(ctx)
    nets_sec = _phone_sec_networks(ctx)
    dial_sec = _phone_sec_dialing(ctx)
    nets, nodes = nets_sec["networks"], nodes_sec["nodes"]
    dash_node = ctx["dash"]["phone_node"]
    pnodes = ctx["dash"].get("phone_nodes") or {}
    _phone_health_nodes(C, ctx, dash_node, nodes, pnodes)
    plan = _phone_health_files(C, ctx, dial_sec)
    _phone_health_live(C, ctx, dial_sec, nets, nodes, running)
    _phone_health_routes(C, ctx, dial_sec, nets, nodes, plan, running)
    counts = {k: sum(1 for c in C if c["status"] == k) for k in ("ok", "warn", "fail", "info")}
    return {"found": True, "checks": C, "counts": counts}

_PH_LOG_FILES = [Path("/var/log/asterisk/full"), Path("/var/log/asterisk/messages")]

_PH_LOG_TAIL = 2_000_000

_PH_CALLS_MAX = 20

_PH_TS_ISO = re.compile(r"^(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d:\d\d)")

_PH_TS_AST = re.compile(r"^\[(\w{3} +\d+ \d\d:\d\d:\d\d)\]")

_PH_EXEC_RE = re.compile(r"Executing \[([^@\]]*)@([^:\]]+):(\d+)\]\s+(\w+)\((.*)\)")

def _ph_now():
    return datetime.now()

def _ph_parse_ts(ts: str):
    try:
        if re.match(r"^\d{4}-\d\d-\d\d", ts):
            return datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
        now = _ph_now()
        d = datetime.strptime(f"{now.year} {re.sub(r'[ ]+', ' ', ts.strip())}", "%Y %b %d %H:%M:%S")
        if d.timestamp() > now.timestamp() + 86400:
            d = d.replace(year=now.year - 1)
        return d
    except (ValueError, OverflowError):
        return None

def _ph_tail(path: Path) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - _PH_LOG_TAIL))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""

def _ph_call_events(text: str, nets: dict, in_ctx: dict) -> "tuple[list, int]":
    events, verbose = [], 0
    for line in text.splitlines():
        m = _PH_EXEC_RE.search(line)
        if not m:
            continue
        verbose += 1
        ts = ""
        t = _PH_TS_ISO.match(line)
        if t:
            ts = f"{t.group(1)} {t.group(2)}"
        else:
            t = _PH_TS_AST.match(line)
            ts = t.group(1) if t else ""
        exten, cname, prio, app, args = m.groups()
        if app.lower() == "dial":
            quoted = re.findall(r'"([^"]*)"', args)
            tm = re.search(r"(IAX2|PJSIP)/([^,\")\s]+)", quoted[1] if len(quoted) >= 2 else args)
            if not tm:
                continue
            peer = re.sub(r"-\d+$", "", tm.group(2).split("/")[0].split("@")[-1])
            if peer in nets or peer.startswith("dvs"):
                events.append({"time": ts, "_dt": _ph_parse_ts(ts), "direction": "outgoing",
                               "network": peer, "network_name": nets.get(peer, peer),
                               "last4": _ph_last4(exten)})
        elif prio == "1" and (cname.startswith("dvs-in-") or cname in in_ctx):
            who = re.search(r"incoming call from (\S+?)[\")]", args)
            peer = in_ctx.get(cname) or cname[len("dvs-in-"):]
            events.append({"time": ts, "_dt": _ph_parse_ts(ts), "direction": "incoming", "network": peer,
                           "network_name": nets.get(peer, peer),
                           "last4": _ph_last4(who.group(1)) if who else ""})
    return events, verbose

@_phone_section("calls", "Recent call attempts")
def _phone_sec_calls(ctx: dict) -> dict:
    nets_list = _phone_sec_networks(ctx)["networks"]
    nets = {n["id"]: n["name"] for n in nets_list}
    in_ctx = {n["context"]: n["id"] for n in nets_list if n["context"]}
    sources, events, verbose_total = [], [], 0
    cutoff = datetime.fromtimestamp(_ph_now().timestamp() - 86400)
    def recent(ev):
        return [e for e in ev if e["_dt"] is None or e["_dt"] >= cutoff]
    for p in _PH_LOG_FILES:
        txt = _ph_tail(p)
        if txt:
            ev, v = _ph_call_events(txt, nets, in_ctx)
            sources.append(str(p))
            verbose_total += v
            events = recent(ev)
            if events:
                break
    if not events:
        txt = _run(["journalctl", "-u", "asterisk", "--since", "24 hours ago", "-n", "30000",
                    "--no-pager", "-o", "short-iso"], timeout=15)
        if txt:
            ev, v = _ph_call_events(txt, nets, in_ctx)
            sources.append("journal")
            verbose_total += v
            events = recent(ev)
    if not verbose_total:
        return {"found": False, "available": False, "calls": [], "sources": sources,
                "note": ("Asterisk isn't logging call detail here. Call history needs the 'Executing' lines "
                         "in /var/log/asterisk/full (logger.conf: full => notice,warning,error,verbose) "
                         "or in the journal.")}
    events = events[-_PH_CALLS_MAX:][::-1]
    unstamped = any(e["_dt"] is None for e in events)
    for e in events:
        e.pop("_dt", None)
    note = ("" if events else "No phone call attempts in the last 24 hours")
    if unstamped:
        note = "Some log lines have a time format sysmon can't read, so the 24-hour limit couldn't be applied to them"
    return {"found": True, "available": True, "calls": events, "sources": sources, "note": note,
            "kind": "attempts"}

_PH_HOIP_DOMAIN   = "hamsoverip.com"

_PH_HOIP_PREMIUM  = "premium.hamsoverip.com"

_PH_HOIP_STANDARD = ("pbx-us1.hamsoverip.com",)

_PH_HOIP_LOGIN    = "https://premium.hamsoverip.com/user/login.php"

_PH_HOIP_PORT     = "5160"

_PH_HOIP_VM       = "*97"

_PH_DASH_VM_ALIAS = "0097"

_PH_HOST_RE       = re.compile(r"^[A-Za-z0-9.\-]{1,253}$")

_PH_RTP_DEFAULT   = (5000, 31000)

_PH_PROBE_TTL     = 20

_PH_PROBE_CACHE: dict = {}

_PH_PROBE_LOCK    = threading.Lock()

_PH_NAT_OPTS = (("direct_media", "yes", "no"), ("rtp_symmetric", "no", "yes"),
                ("force_rport", "yes", "yes"), ("rewrite_contact", "no", "yes"))

_PH_DASH_KEYS = ("callsign", "extension", "host", "port", "transport", "login_url", "voicemail_access")

def _ph_yes(v: str) -> bool:
    return str(v).strip().lower() in ("yes", "y", "true", "1", "on")

def _ph_uri_parts(uri: str) -> dict:
    u = re.sub(r"^<?sips?:", "", uri.strip()).rstrip(">")
    u = u.split(";")[0]
    user, at, rest = u.rpartition("@")
    h, _c, p = rest.partition(":")
    return {"user": user if at else "", "host": h.lower(), "port": p}

def _ph_is_hoip(host: str) -> bool:
    h = host.lower()
    return h == _PH_HOIP_DOMAIN or h.endswith("." + _PH_HOIP_DOMAIN)

def _ph_resolve_host(host: str, timeout: float = 4.0) -> list:
    if not _PH_HOST_RE.match(host or ""):
        return []
    out: list = []
    def work():
        try:
            for *_x, sa in _socket.getaddrinfo(host, None, _socket.AF_INET, _socket.SOCK_DGRAM):
                if sa[0] not in out:
                    out.append(sa[0])
        except OSError:
            pass
    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(timeout)
    return list(out)

def _ph_sip_ping(host: str, ip: str, port: int, timeout: float = 2.0, tries: int = 2) -> dict:
    key = (ip, port)
    with _PH_PROBE_LOCK:
        hit = _PH_PROBE_CACHE.get(key)
        if hit and time.time() - hit[0] < _PH_PROBE_TTL:
            return dict(hit[1], cached=True)
    res = {"answered": False, "status": "", "ms": None, "error": ""}
    s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    try:
        s.settimeout(timeout)
        s.connect((ip, port))
        lip, lport = s.getsockname()[:2]
        msg = (f"OPTIONS sip:{host}:{port} SIP/2.0\r\n"
               f"Via: SIP/2.0/UDP {lip}:{lport};branch=z9hG4bK{secrets.token_hex(8)};rport\r\n"
               "Max-Forwards: 70\r\n"
               f"From: <sip:sysmon@{lip}>;tag={secrets.token_hex(4)}\r\n"
               f"To: <sip:{host}:{port}>\r\n"
               f"Call-ID: {secrets.token_hex(10)}@{lip}\r\n"
               "CSeq: 1 OPTIONS\r\n"
               f"User-Agent: ASL-DVS sysmon {VERSION}\r\n"
               "Accept: application/sdp\r\n"
               "Content-Length: 0\r\n\r\n").encode()
        for _n in range(tries):
            t0 = time.monotonic()
            s.send(msg)
            try:
                data = s.recv(4096)
            except (_socket.timeout, TimeoutError):
                continue
            first = data.split(b"\r\n", 1)[0].decode("ascii", "replace")
            m = re.match(r"^SIP/2\.0\s+(\d{3})\s*(.*)$", first)
            if m:
                res.update(answered=True, status=f"{m.group(1)} {m.group(2)}".strip()[:60],
                           ms=int((time.monotonic() - t0) * 1000))
                break
    except OSError as e:
        res["error"] = str(e)[:80]
    finally:
        s.close()
    with _PH_PROBE_LOCK:
        _PH_PROBE_CACHE[key] = (time.time(), res)
    return dict(res, cached=False)

def _ph_rtp_range(ctx: dict, running: bool) -> "tuple[int, int, str]":
    if running:
        out = _ph_cli("rtp show settings", 4)
        a = re.search(r"Port start:\s*(\d+)", out)
        b = re.search(r"Port end:\s*(\d+)", out)
        if a and b:
            return int(a.group(1)), int(b.group(1)), "Asterisk (running)"
    try:
        text = (ctx["dir"] / "rtp.conf").read_text(errors="replace")
    except OSError:
        return _PH_RTP_DEFAULT[0], _PH_RTP_DEFAULT[1], "Asterisk default (no rtp.conf)"
    kv = {}
    for raw in text.splitlines():
        m = re.match(r"^\s*(rtpstart|rtpend)\s*=\s*(\d+)", _PH_CMT_RE.sub("", raw))
        if m:
            kv[m.group(1)] = int(m.group(2))
    return (kv.get("rtpstart", _PH_RTP_DEFAULT[0]), kv.get("rtpend", _PH_RTP_DEFAULT[1]), "rtp.conf")

def _ph_ports_txt(pairs: list) -> str:
    t = [f"{a}" if a == b else f"{a}-{b}" for a, b in pairs[:3]]
    return ", ".join(t) + (" …" if len(pairs) > 3 else "")

def _ph_fw_ctx(ctx: dict) -> dict:
    if "_fw_udp" not in ctx:
        ctx["_fw_udp"] = _ph_fw_udp_rules()
    return ctx["_fw_udp"]

def _ph_fw_fix(ctx: dict, what: str) -> str:
    if "_fw_backend" not in ctx:
        ctx["_fw_backend"] = get_firewall_backend()
    be = ctx["_fw_backend"]
    ports = what.split()[-1]
    if be == "firewalld":
        return (f"Open {what} in Cockpit → Networking → Firewall, or: "
                f"sudo firewall-cmd --permanent --add-port={ports}/udp && sudo firewall-cmd --reload")
    if be == "nft":
        return f"Open {what} in /etc/nftables.conf, then: sudo systemctl reload nftables"
    if be == "ufw":
        return f"Open {what}: sudo ufw allow {ports.replace('-', ':')}/udp"
    return f"Open {what} in the Pi's firewall"

def _ph_fw_check(cid: str, title: str, cov: dict, what: str, fix: str) -> dict:
    st = cov["state"]
    if st == "open":
        return _ph_check(cid, title, "ok", f"{what} open")
    if st == "nofilter":
        return _ph_check(cid, title, "info", f"{what} not blocked ({cov['why']})")
    if st == "unknown":
        return _ph_check(cid, title, "info", f"can't tell for {what}", f"{cov['why']} -- check it by hand")
    if st == "partial":
        return _ph_check(cid, title, "warn", f"{what} partly open",
                         "Still shut: " + _ph_ports_txt(cov["gaps"]) + ". " + fix)
    return _ph_check(cid, title, "warn", f"{what} not open", fix)

def _ph_udp_listener(port: int) -> "tuple[str, str]":
    if not shutil.which("ss"):
        return "unknown", ""
    out = _run(["ss", "-Hulnp"], timeout=4)
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4 or not parts[3].endswith(f":{port}"):
            continue
        m = re.search(r'users:\(\("([^"]+)"', line)
        name = m.group(1) if m else ""
        return ("asterisk" if name.startswith("asterisk") else "other"), name
    return "none", ""

def _ph_hoip_dash(eid: str) -> dict:
    try:
        doc = json.loads(_PH_PHONE_JSON.read_text())
    except (OSError, ValueError):
        return {}
    nets = doc.get("networks", []) if isinstance(doc, dict) else []
    nets = [n for n in nets if isinstance(n, dict)]
    pick = next((n for n in nets if str(n.get("id", "")) == eid), None)
    if pick is None:
        pick = next((n for n in nets if _ph_is_hoip(str(n.get("host", "")))), None)
    if not pick:
        return {}
    out = {k: str(pick[k]).strip()[:64] for k in _PH_DASH_KEYS if pick.get(k) not in (None, "")}
    url = out.get("login_url", "")
    if url and not re.match(r"^https://([A-Za-z0-9\-]+\.)*hamsoverip\.com/[\w./?=&%-]*$", url):
        out.pop("login_url")
    return out

def _ph_hoip_accounts(ctx: dict) -> list:
    typed = _ph_pjsip_typed(ctx)
    def find(t, name):
        return [s for s in typed.get(t, []) if s["name"] == name]
    accts = []
    for ep in typed.get("endpoint", []):
        name = ep["name"]
        kv = _ph_last([ep])
        out_auth = kv.get("outbound_auth", "")
        aors = [a for n in (x.strip() for x in kv.get("aors", name).split(",")) if n for a in find("aor", n)]
        regs = [r for r in typed.get("registration", [])
                if (out_auth and _ph_last([r]).get("outbound_auth", "") == out_auth)
                or _ph_last([r]).get("endpoint", "") == name]
        uris = []
        for r in regs:
            rk = _ph_last([r])
            uris += [(f"registration {r['name']} server_uri", rk.get("server_uri", "")),
                     (f"registration {r['name']} client_uri", rk.get("client_uri", ""))]
            if rk.get("outbound_proxy"):
                uris.append((f"registration {r['name']} outbound_proxy", rk["outbound_proxy"]))
        for a in aors:
            for k, v, *_ in a["kv"]:
                if k.strip().lower() == "contact":
                    uris.append((f"aor {a['name']} contact", v))
        if kv.get("outbound_proxy"):
            uris.append((f"endpoint {name} outbound_proxy", kv["outbound_proxy"]))
        uris = [(w, u.strip()) for w, u in uris if u.strip()]
        hosts = [_ph_uri_parts(u)["host"] for _w, u in uris]
        if not any(_ph_is_hoip(h) for h in hosts):
            continue
        idn = [i for i in typed.get("identify", []) if _ph_last([i]).get("endpoint", "") == name]
        matches = [v.strip() for i in idn for k, v, *_ in i["kv"] if k.strip().lower() == "match"]
        matches = [m.strip() for v in matches for m in v.split(",") if m.strip()]
        auth = find("auth", out_auth) if out_auth else []
        akv = _ph_last(auth) if auth else {}
        accts.append({"endpoint": ep, "kv": kv, "regs": regs, "aors": aors, "uris": uris,
                      "matches": matches, "auth_name": out_auth, "auth": akv,
                      "has_password": bool(akv.get("password")), "typed": typed})
    return accts

def _ph_hoip_server_ports(C, dash, hosts, main):
    hoip_hosts = sorted({p["host"] for _w, p in hosts if _ph_is_hoip(p["host"])})
    dhost = dash.get("host", "").lower()
    if dhost and dhost != main:
        C.append(_ph_check("server", "Right server", "fail", f"settings use {main}, dashboard has {dhost}",
                           "Save Phone again on the dashboard's Edit page so both agree"))
    elif len(hoip_hosts) > 1:
        C.append(_ph_check("server", "Right server", "warn", "mixed: " + ", ".join(hoip_hosts),
                           "Every line of the account should use the same HOIP server"))
    elif main in _PH_HOIP_STANDARD:
        C.append(_ph_check("server", "Right server", "info", f"{main} (standard-account server)",
                           f"Premium accounts use {_PH_HOIP_PREMIUM} -- check your welcome email"))
    else:
        C.append(_ph_check("server", "Right server", "ok", main))
    want = dash.get("port", "") if dash.get("port", "").isdigit() else \
           (_PH_HOIP_PORT if main == _PH_HOIP_PREMIUM else "")
    ports = [(w, p["port"] or "5060") for w, p in hosts if _ph_is_hoip(p["host"]) and "client_uri" not in w]
    if want:
        wrong = [f"{w} ({pt})" for w, pt in ports if pt != want]
        C.append(_ph_check("port", f"Port {want} everywhere", "fail" if wrong else "ok",
                           f"wrong on {len(wrong)} line{'' if len(wrong) == 1 else 's'}" if wrong
                           else f"server and contact lines all use :{want}",
                           ("Wrong: " + "; ".join(wrong[:3]) + f". Add :{want} after the server name -- "
                            "with no port, Asterisk uses 5060") if wrong else ""))
    else:
        used = sorted({pt for _w, pt in ports})
        C.append(_ph_check("port", "Same port everywhere", "ok" if len(used) == 1 else "warn",
                           ", ".join(used), "" if len(used) == 1 else "The account's lines don't agree on the port"))
    return ports, want

def _ph_hoip_transport_auth(C, a, dash, ips, kv, main, ports, typed, want):
    tname = kv.get("transport", "") or next((_ph_last([r]).get("transport", "") for r in a["regs"]
                                             if _ph_last([r]).get("transport", "")), "")
    tr = _ph_transport_for(typed, tname)
    want_t = dash.get("transport", "udp").lower() or "udp"
    if tr is None:
        C.append(_ph_check("transport", "Transport", "fail",
                           f"transport {tname} not defined" if tname else "no UDP transport in pjsip.conf",
                           "The account can't send anything without a transport"))
    else:
        proto = _ph_last([tr]).get("protocol", "udp").lower()
        C.append(_ph_check("transport", "Transport", "ok" if proto == want_t else "warn",
                           f"{tr['name']} ({proto.upper()}, Pi port {_ph_bind_port(tr)})"
                           + ("" if tname else " -- picked automatically"),
                           "" if proto == want_t else f"HOIP gave {want_t.upper()}; this transport is {proto.upper()}"))
    user = a["auth"].get("username", "")
    cu = next((_ph_uri_parts(u)["user"] for w, u in a["uris"] if "client_uri" in w), "")
    names = {"SIP username (auth)": user, "Registration user": cu, "Dashboard extension": dash.get("extension", "")}
    vals = {v for v in names.values() if v}
    if not vals:
        C.append(_ph_check("names", "Login names", "fail", "no username set", "The auth stanza needs username="))
    else:
        C.append(_ph_check("names", "Login names", "ok" if len(vals) == 1 else "fail",
                           next(iter(vals)) if len(vals) == 1 else
                           "; ".join(f"{k} {v}" for k, v in names.items() if v),
                           "" if len(vals) == 1 else "Username, Authentication ID and extension should all be the same"))
    C.append(_ph_check("secret", "SIP password", "ok" if a["has_password"] else "fail",
                       "set (not shown)" if a["has_password"] else "not set",
                       "" if a["has_password"] else "The auth stanza needs password="))
    ping_port = int(want or next((pt for w, pt in ports if "server_uri" in w), "5060"))
    if ips:
        pr = _ph_sip_ping(main, ips[0], ping_port)
        if pr["answered"]:
            C.append(_ph_check("probe", "Server answers", "ok",
                               f"replied {pr['status']} in {pr['ms']} ms (UDP {ping_port})"
                               + (" · cached" if pr.get("cached") else "")))
        else:
            C.append(_ph_check("probe", "Server answers", "warn",
                               f"no reply on UDP {ping_port}" + (f" ({pr['error']})" if pr["error"] else ""),
                               "Some servers ignore this test. If 'Signed in' is OK, you can ignore this"))
    return tr, user

def _ph_hoip_signin(C, a, ips, kv, main, name, running, user):
    reg = a["regs"][0] if a["regs"] else None
    smode, spick = _ph_signin_choice()
    if reg is None and smode == "picked" and name != spick:
        C.append(_ph_check("reg", "Signed in", "info", "signed out by choice",
                           "The dashboard signs in only the network picked on its Phone tab"
                           + (f" ({spick})" if spick else "") + ". Pick this one there to move the sign-in"))
    elif reg is None:
        C.append(_ph_check("reg", "Signed in", "fail", "no registration stanza",
                           "Without it HOIP doesn't know where to send your incoming calls"))
    elif not running:
        C.append(_ph_check("reg", "Signed in", "fail", "Asterisk isn't running"))
    else:
        r = _ph_reg_states([{"id": name, "name": name, "type": "sip", "registers": True,
                             "reg_name": reg["name"], "username": user}])[0]
        exp = _ph_last([reg]).get("expiration", "3600")
        mins = int(exp) // 60 if exp.isdigit() else 0
        C.append(_ph_check("reg", "Signed in", "ok" if r["registered"] else "fail", r["state"],
                           (f"Sign-in renews about every {mins} min" if mins else "") if r["registered"] else
                           "Rejected usually means the username or password is wrong; check the port too"))
    if not a["matches"]:
        C.append(_ph_check("match", "Incoming calls accepted", "fail", "no identify match",
                           f"Add an identify stanza with match={main} so calls from HOIP reach this account"))
    else:
        import ipaddress
        nets_ok, by_name = [], False
        for m in a["matches"]:
            try:
                nets_ok.append(ipaddress.ip_network(m, strict=False))
            except ValueError:
                if m.lower() == main or _ph_is_hoip(m):
                    by_name = True
        inside = [ip for ip in ips if any(ipaddress.ip_address(ip) in n for n in nets_ok)]
        if by_name:
            C.append(_ph_check("match", "Incoming calls accepted", "ok", "matched by server name",
                               "Asterisk looks the name up when it loads; restart it if HOIP moves servers"))
        elif ips and len(inside) == len(ips):
            C.append(_ph_check("match", "Incoming calls accepted", "ok", "server address is in the list"))
        elif ips:
            C.append(_ph_check("match", "Incoming calls accepted", "fail",
                               f"{main} is at {', '.join(ips[:3])}, not in the list",
                               f"Use match={main} so the list follows the server"))
        else:
            C.append(_ph_check("match", "Incoming calls accepted", "info", ", ".join(a["matches"][:3]),
                               "Can't compare -- the server name didn't look up"))
    missing = [f"{o}={w}" for o, d, w in _PH_NAT_OPTS if (kv.get(o, d).strip().lower() in ("yes", "true", "1", "on")) != _ph_yes(w)]
    C.append(_ph_check("nat", "Behind-router settings", "ok" if not missing else "warn",
                       f"all {len(_PH_NAT_OPTS)} set" if not missing else f"{len(_PH_NAT_OPTS) - len(missing)} of {len(_PH_NAT_OPTS)} set",
                       "" if not missing else "Set on the account: " + ", ".join(missing)))

def _ph_hoip_network_vm(C, ctx, dash, name, running, tr):
    if tr is not None:
        tkv = _ph_last([tr])
        lnet = ", ".join(v for k, v, *_ in tr["kv"] if k.strip().lower() == "local_net")
        ext = tkv.get("external_media_address", "") or tkv.get("external_signaling_address", "")
        if ext and not lnet:
            C.append(_ph_check("localnet", "Home network range", "warn", "external address set, local_net missing",
                               "With an external address, local_net must list your home range or local calls break"))
        elif lnet:
            import ipaddress
            single = []
            for part in lnet.split(","):
                try:
                    nw = ipaddress.ip_network(part.strip(), strict=False)
                except ValueError:
                    continue
                if nw.num_addresses == 1 and not nw.network_address.is_loopback:
                    single.append(str(nw))
            if single:
                try:
                    guess = str(ipaddress.ip_network(single[0].split("/")[0] + "/24", strict=False))
                except ValueError:
                    guess = "your home range, for example 192.168.1.0/24"
                C.append(_ph_check("localnet", "Home network range", "warn",
                                   f"{', '.join(single)} is a single address",
                                   f"That covers only one device. Use your whole home network, for example {guess} "
                                   f"(dashboard Edit page → Phone → Home network)"))
            else:
                C.append(_ph_check("localnet", "Home network range", "ok", lnet))
        else:
            C.append(_ph_check("localnet", "Home network range", "info", "not set",
                               "Usually fine when the Pi signs in to HOIP. Set it (and an external address) if audio goes one way"))
    sip_port = _ph_bind_port(tr)
    lst, proc = _ph_udp_listener(sip_port)
    C.append(_ph_check("listen", "Asterisk listening", {"asterisk": "ok", "other": "fail", "none": "fail"}.get(lst, "info"),
                       {"asterisk": f"on UDP {sip_port}", "other": f"UDP {sip_port} is taken by {proc or 'another program'}",
                        "none": f"nothing on UDP {sip_port}"}.get(lst, "can't tell (ss not installed)"),
                       "" if lst in ("asterisk", "unknown") else "Restart Asterisk; if it's still missing, check the transport's bind line"))
    rules = _ph_fw_ctx(ctx)
    C.append(_ph_fw_check("fwsip", "Pi firewall: SIP port", _ph_fw_cover(rules, sip_port, sip_port),
                          f"UDP {sip_port}", _ph_fw_fix(ctx, f"UDP {sip_port}")))
    lo, hi, src = _ph_rtp_range(ctx, running)
    C.append(_ph_fw_check("fwrtp", "Pi firewall: audio", _ph_fw_cover(rules, lo, hi),
                          f"UDP {lo}-{hi}", _ph_fw_fix(ctx, f"UDP {lo}-{hi}") + f" (range from {src})"))
    C.append(_ph_check("router", "Router", "info", "usually nothing to forward",
                       f"The Pi signs in to HOIP and answers to the ports audio arrives from. Only if incoming calls "
                       f"don't arrive: forward UDP {sip_port} to this Pi (and UDP {lo}-{hi} if audio is one-way), and "
                       f"turn off SIP ALG. Forwarding opens Asterisk to the internet, so try a test call without it first"))
    vm = dash.get("voicemail_access", "") if re.match(r"^\*?\d{1,6}$", dash.get("voicemail_access", "")) else _PH_HOIP_VM
    plan = ctx["dialplan"]
    ctxs = []
    for o in _phone_sec_dialing(ctx).get("outgoing", []):
        if o.get("network") == name or any(re.search(r"PJSIP/(?:[^,@/]*@)?" + re.escape(name) + r"\b", d)
                                           for d in o.get("dials", [])):
            ctxs.append(o["context"])
            if o.get("kind") == "dashboard":
                ctxs.append(o["context"] + "-r")
    passes = any(_ph_pat_match(e["pattern"], vm) and e["steps"] and "dvs-invalid" not in e["steps"][0]["raw"]
                 for c in ctxs for e in plan.get(c, []))
    vm_dial, vm_title = vm, f"Voicemail {vm}"
    alias = [e for e in plan.get(f"dvs-net-{name}", []) if e["pattern"] == _PH_DASH_VM_ALIAS]
    if f"dvs-net-{name}" in ctxs and alias:
        vm_dial, vm_title = _PH_DASH_VM_ALIAS, f"Voicemail {vm} (dial {_PH_DASH_VM_ALIAS})"
        passes = any(st["app"].lower() == "dial" and vm in st["args"] for e in alias for st in e["steps"])
    C.append(_ph_check("vm", vm_title, "info",
                       ("the dialing rules send it to HOIP" if passes else "the dialing rules don't pass it")
                       if ctxs else "no dialing rules use this account",
                       "Checks the dialing rules only; no call is placed"))
    return hi, lo, sip_port, vm, vm_dial

def _ph_hoip_checks(ctx: dict, a: dict, running: bool) -> dict:
    name, kv, typed = a["endpoint"]["name"], a["kv"], a["typed"]
    dash = _ph_hoip_dash(name)
    C: list = []
    hosts = [(w, _ph_uri_parts(u)) for w, u in a["uris"]]
    main = next((p["host"] for w, p in hosts if "server_uri" in w and _ph_is_hoip(p["host"])), "") or \
           next((p["host"] for w, p in hosts if _ph_is_hoip(p["host"])), "")
    ips = _ph_resolve_host(main)
    C.append(_ph_check("dns", "Server name lookup", "ok" if ips else "fail",
                       f"{main} → {', '.join(ips[:3])}" if ips else f"{main} can't be looked up",
                       "" if ips else "Check the spelling of the server, and that the Pi has internet and DNS"))
    ports, want = _ph_hoip_server_ports(C, dash, hosts, main)
    tr, user = _ph_hoip_transport_auth(C, a, dash, ips, kv, main, ports, typed, want)
    _ph_hoip_signin(C, a, ips, kv, main, name, running, user)
    hi, lo, sip_port, vm, vm_dial = _ph_hoip_network_vm(C, ctx, dash, name, running, tr)
    counts = {k: sum(1 for c in C if c["status"] == k) for k in ("ok", "warn", "fail", "info")}
    login = dash.get("login_url", "") or (_PH_HOIP_LOGIN if main == _PH_HOIP_PREMIUM else "")
    return {"id": name, "name": ctx["dash"]["names"].get(name, name), "host": main,
            "port": want or (ports[0][1] if ports else ""), "transport": (tr["name"] if tr else ""),
            "username": user, "callsign": dash.get("callsign", ""), "extension": dash.get("extension", ""),
            "caller_id": re.sub(r"[^0-9+ A-Za-z<>\"]", "", kv.get("callerid", ""))[:60],
            "context": kv.get("context", ""), "voicemail_access": vm, "voicemail_dial": vm_dial, "login_url": login,
            "sip_port": sip_port, "rtp": [lo, hi], "checks": C, "counts": counts}

@_phone_section("hoip", "Hams Over IP")
def _phone_sec_hoip(ctx: dict) -> dict:
    accts = _ph_hoip_accounts(ctx)
    if not accts:
        return {"found": False, "accounts": [], "note": "No SIP account points at a hamsoverip.com server"}
    running = _ph_ast_running()
    return {"found": True, "accounts": [_ph_hoip_checks(ctx, a, running) for a in accts]}

_PM_BEGIN = "; >>> sysmon-phone modules (sysmon Phone tab - edit with care) >>>"

_PM_END   = "; <<< sysmon-phone <<<"

_PM_BEGIN_PFX = "; >>> sysmon-phone"

_PM_END_PFX   = "; <<< sysmon-phone"

_PM_OFF   = "; sysmon-phone off: "

_PM_FEATS = ("autopatch", "reverse")

_PM_FEAT_LBL = {"autopatch": "Autopatch (radio dials out)",
                "reverse": "Reverse autopatch (phone calls in to the radio)"}

_PM_NAME_RE = re.compile(r"^[a-z0-9_]+\.so$")

_PM_CONF_RE = re.compile(r"^(load|noload|require|preload|preload-require)\s*=>?\s*([\w.\-]+\.so)\s*$", re.I)

_PM_MODDIRS = ("/usr/lib/asterisk/modules", "/usr/lib/aarch64-linux-gnu/asterisk/modules",
               "/usr/lib/arm-linux-gnueabihf/asterisk/modules", "/usr/lib/x86_64-linux-gnu/asterisk/modules",
               "/usr/lib64/asterisk/modules")

def _pm_conf_parse(text: str) -> dict:
    res = {"entries": [], "autoload": False, "modules_sec": False, "block": None}
    section, zone = "", ""
    for i, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if line.startswith(_PM_BEGIN_PFX):
            zone, res["block"] = "sysmon", [i, None]
            continue
        if line.startswith(_PM_END_PFX):
            if res["block"] and res["block"][1] is None:
                res["block"][1] = i
            zone = ""
            continue
        if line.startswith(_PH_BEGIN):
            zone = "dashboard"
            continue
        if line.startswith(_PH_END):
            zone = ""
            continue
        body = _PH_CMT_RE.sub("", line).strip()
        m = re.match(r"^\[([^\]]+)\]", body)
        if m:
            section = m.group(1).strip().lower()
            if section == "modules":
                res["modules_sec"] = True
            continue
        if section != "modules" or not body:
            continue
        m = re.match(r"^autoload\s*=>?\s*(\S+)", body, re.I)
        if m:
            res["autoload"] = m.group(1).lower() in ("yes", "true", "1", "on")
            continue
        m = _PM_CONF_RE.match(body)
        if m:
            res["entries"].append({"line": i, "kind": m.group(1).lower(), "module": m.group(2),
                                   "zone": zone or "modules.conf"})
    return res

def _pm_conf_state(parsed: dict, mod: str) -> dict:
    ent = [e for e in parsed["entries"] if e["module"] == mod]
    if any(e["kind"] == "noload" for e in ent):
        where = sorted({e["zone"] for e in ent if e["kind"] == "noload"})
        return {"conf": "noload", "where": where}
    if ent:
        return {"conf": "load", "where": sorted({e["zone"] for e in ent})}
    return {"conf": "load (autoload)" if parsed["autoload"] else "not listed", "where": []}

def _pm_running_map() -> "dict | None":
    if not _ph_ast_running():
        return None
    out = _ph_cli("module show", 8)
    got: dict = {}
    for line in out.splitlines():
        toks = line.split()
        if not toks or not toks[0].endswith(".so"):
            continue
        got[toks[0]] = bool(re.search(r"(?<!Not )\bRunning\b", line))
    return got

def _pm_moddir() -> str:
    out = _ph_cli("core show settings", 5) if _ph_ast_running() else ""
    m = re.search(r"Module directory:\s*(\S+)", out)
    if m and os.path.isdir(m.group(1)):
        return m.group(1)
    for d in _PM_MODDIRS:
        if os.path.isfile(os.path.join(d, "app_rpt.so")) or os.path.isfile(os.path.join(d, "pbx_config.so")):
            return d
    return next((d for d in _PM_MODDIRS if os.path.isdir(d)), "")

def _pm_owner(path: str) -> str:
    out = _run(["dpkg", "-S", path], timeout=8)
    m = re.match(r"^([a-z0-9][a-z0-9+.\-]*)(?::[a-z0-9]+)?(?:,\s*\S+)*:\s+(?=/)", out or "")
    return m.group(1) if m else ""

def _pm_needs(ctx: dict) -> dict:
    nets = _phone_sec_networks(ctx)["networks"]
    nodes = _phone_sec_node(ctx)["nodes"]
    dial = _phone_sec_dialing(ctx)
    apps: set = set()
    raw = ""
    for exts in ctx["dialplan"].values():
        for e in exts:
            for st in e["steps"]:
                apps.add(st["app"].lower())
                raw += st["raw"] + "\n"
    sip = [n for n in nets if n["type"] != "iax2"]
    live_in = ("asks for a PIN", "only trusted numbers (no PIN)",
               "connects straight to the node (no PIN)", "custom")
    return {
        "autopatch": any(n["autopatch"] for n in nodes),
        "reverse": any(i["mode"] in live_in for i in dial.get("incoming", [])),
        "sip": bool(sip), "iax": any(n["type"] == "iax2" for n in nets),
        "sip_login": any(n["type"] == "sip" for n in sip),
        "sip_reg": any(n["registers"] for n in sip),
        "sip_ident": any(n["type"] == "sip_ip" or n.get("match") for n in sip),
        "pin": any(i["mode"] == "asks for a PIN" for i in dial.get("incoming", [])),
        "db": bool(re.search(r"\bDB(?:_EXISTS|_DELETE)?\(", raw)) or bool(ctx["dash"]["phone_node"]),
        "playback": bool(apps & {"playback", "background"}),
        "tones_sound": "dvs-tones" in ctx["dialplan"],
        "system": "system" in apps,
        "callerid": bool(re.search(r"\bCALLERID\(", raw)),
    }

def _pm_rows(need: dict) -> list:
    B = list(_PM_FEATS)
    rows = [("app_rpt.so", B, True, "runs every node; autopatch is part of it"),
            ("pbx_config.so", B, True, "reads the dialing rules in extensions.conf"),
            ("res_timing_*", B, True, "the timing source app_rpt needs (any one res_timing module)"),
            ("bridge_simple.so", B, True, "joins the call to the node"),
            ("bridge_softmix.so", B, True, "joins the call to the node"),
            ("chan_bridge_media.so", B, True, "joins the call to the node"),
            ("codec_ulaw.so", B, True, "converts phone audio"),
            ("codec_alaw.so", B, True, "converts phone audio"),
            ("codec_gsm.so", B, True, "converts phone audio")]
    if need["db"]:
        rows.append(("func_db.so", B, True, "reads the dashboard's on/off flags in the dialing rules"))
    if need.get("callerid"):
        rows.append(("func_callerid.so", B, True, "sets your caller ID and checks trusted numbers"))
    if need["sip"]:
        for m in ("chan_pjsip.so", "res_pjsip.so", "res_pjsip_session.so", "res_pjsip_sdp_rtp.so",
                  "res_pjproject.so", "res_rtp_asterisk.so"):
            rows.append((m, B, True, "carries every SIP call"))
    rows.append(("chan_iax2.so", B, True, "links the phone nodes to your radio node" +
                 (", and carries IAX2 calls" if need["iax"] else "")))
    rows.append(("app_dial.so", ["autopatch"], False, "places the call to the phone network"))
    rows.append(("app_senddtmf.so", B, False, "the dashboard's *99, # and keypad tones"))
    if need["sip_login"]:
        rows.append(("res_pjsip_outbound_authenticator_digest.so",
                     ["autopatch", "reverse"] if need["sip_reg"] else ["autopatch"], False,
                     "the SIP login (Hams Over IP and other accounts)"))
    if need["sip_reg"]:
        rows.append(("res_pjsip_outbound_registration.so", ["reverse"], False,
                     "signs in so calls can reach you"))
    if need["sip_ident"]:
        rows.append(("res_pjsip_endpoint_identifier_ip.so", ["reverse"], False,
                     "recognises incoming calls by address"))
    if need["pin"]:
        rows.append(("app_read.so", ["reverse"], False, "asks incoming callers for the PIN"))
    if need["playback"]:
        rows.append(("app_playback.so", B, False, "plays greetings and prompts"))
    if need.get("system"):
        rows.append(("app_system.so", ["autopatch"], False, "hands numbers dialed from the radio (*61) to the dashboard"))
    if need.get("tones_sound"):
        rows.append(("app_chanspy.so", ["autopatch"], False, "the dashboard's 'as sound' tones"))
        rows.append(("format_pcm.so", ["autopatch"], False, "reads the tone recordings"))
    return [{"module": m, "features": f, "locked": lk, "why": w} for m, f, lk, w in rows]

def _pm_collect(ctx: dict) -> dict:
    need = _pm_needs(ctx)
    try:
        text = (ctx["dir"] / "modules.conf").read_text(errors="replace")
        parsed = _pm_conf_parse(text)
        conf_err = ""
    except OSError as e:
        parsed, conf_err = _pm_conf_parse(""), f"modules.conf: {e.strerror or e}"
    running = _pm_running_map()
    moddir = _pm_moddir()
    rows, owners = _pm_rows(need), {}
    for r in rows:
        mod = r["module"]
        if mod.endswith("*"):
            pfx = mod[:-1]
            names = [m for m in (running or {}) if m.startswith(pfx)]
            r.update(conf="-", where=[], running=(any(running[m] for m in names) if running is not None else None),
                     file=True, package="", shown=", ".join(n for n in names if running and running[n]) or "")
            continue
        r.update(_pm_conf_state(parsed, mod))
        r["running"] = (running.get(mod, False) if running is not None else None)
        path = os.path.join(moddir, mod) if moddir else ""
        r["file"] = os.path.isfile(path) if path else None
        r["package"] = ""
        if path and not r["file"]:
            if path not in owners:
                owners[path] = (_pm_owner(path) or _pm_owner(os.path.join(moddir, "pbx_config.so"))
                                or _pm_owner(os.path.join(moddir, "app_rpt.so")))
            r["package"] = owners[path]
        r["blocked_by_dashboard"] = r["conf"] == "noload" and "dashboard" in r.get("where", [])
    groups = []
    for f in _PM_FEATS:
        mine = [r for r in rows if f in r["features"]]
        own = [r for r in mine if not r["locked"] and r["features"] == [f]]
        down = [r["module"] for r in mine if r["running"] is False or r["file"] is False]
        off = bool(own) and all(r["conf"] == "noload" and r["running"] is not True for r in own)
        if not need[f]:
            state = "not set up"
        elif running is None:
            state = "asterisk down"
        elif off:
            state = "off"
        elif down:
            state = "missing"
        else:
            state = "ready"
        groups.append({"feature": f, "label": _PM_FEAT_LBL[f], "configured": need[f], "state": state,
                       "not_running": down, "own": [r["module"] for r in own]})
    pkgs = sorted({r["package"] for r in rows if r.get("package")})
    return {"found": True, "rows": rows, "groups": groups, "moddir": moddir,
            "asterisk_running": running is not None, "autoload": parsed["autoload"],
            "modules_section": parsed["modules_sec"], "has_block": parsed["block"] is not None,
            "missing_files": [r["module"] for r in rows if r.get("file") is False],
            "packages": pkgs, "root": os.geteuid() == 0,
            "note": conf_err or ("" if parsed["modules_sec"] else "modules.conf has no [modules] section")}

@_phone_section("modules", "Autopatch modules")
def _phone_sec_modules(ctx: dict) -> dict:
    return _pm_collect(ctx)

_pm_lock = threading.Lock()

_PM_BACKUPS_KEEP = 5

def _pm_backup(path: Path) -> str:
    dst = path.with_name(f"{path.name}.sysmon-bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(path, dst)
    olds = sorted(path.parent.glob(path.name + ".sysmon-bak-*"))
    for old in olds[:-_PM_BACKUPS_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass
    return str(dst)

def _pm_edit_text(text: str, changes: dict) -> "tuple[str | None, str, list]":
    parsed = _pm_conf_parse(text)
    if not parsed["modules_sec"]:
        return None, "modules.conf has no [modules] section -- fix it by hand first", []
    blk = parsed["block"]
    if blk and blk[1] is None:
        return None, "sysmon's marked block in modules.conf has lost its end line -- fix it by hand", []
    lines = text.splitlines()
    ours = {e["module"]: e["kind"] for e in parsed["entries"] if e["zone"] == "sysmon"}
    warns: list = []
    for mod, kind in changes.items():
        ours[mod] = kind
        if kind != "load":
            continue
        for e in parsed["entries"]:
            if e["module"] != mod or e["kind"] != "noload" or e["zone"] == "sysmon":
                continue
            if e["zone"] == "dashboard":
                warns.append(f"{mod}: the dashboard's own block says noload -- Save Phone on the dashboard to fix it")
            else:
                lines[e["line"]] = _PM_OFF + lines[e["line"]]
    if blk:
        del lines[blk[0]:blk[1] + 1]
    start = next(i for i, l in enumerate(lines)
                 if re.match(r"^\s*\[modules\]", _PH_CMT_RE.sub("", l.strip()), re.I))
    end = next((i for i in range(start + 1, len(lines))
                if re.match(r"^\s*\[[^\]]+\]", _PH_CMT_RE.sub("", lines[i].strip()))), len(lines))
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    if ours:
        block = [_PM_BEGIN] + [f"{k} => {m}" for m, k in sorted(ours.items())] + [_PM_END]
        lines[end:end] = block
    return "\n".join(lines) + "\n", "saved", warns

def _pm_allowed(module: str) -> "tuple[dict | None, str]":
    if not _PM_NAME_RE.match(module or ""):
        return None, "Not a module name"
    sec = _pm_collect(_ph_load_ctx())
    row = next((r for r in sec["rows"] if r["module"] == module), None)
    if row is None:
        return None, f"{module} isn't one of this node's autopatch modules"
    if row["locked"]:
        return None, f"{module} is locked -- changing it would take down the nodes or every call"
    return row, ""

def _pm_call_up() -> bool:
    try:
        return _phone_sec_live(_ph_load_ctx()).get("state", "idle") != "idle"
    except Exception:
        return False

def _pm_set_conf(changes: dict) -> dict:
    path = _AST_DIR / "modules.conf"
    with _pm_lock:
        try:
            text = path.read_text(errors="replace")
        except OSError as e:
            return {"ok": False, "message": f"Couldn't read modules.conf: {e.strerror or e}"}
        new, msg, warns = _pm_edit_text(text, changes)
        if new is None:
            return {"ok": False, "message": msg}
        if new == text:
            return {"ok": True, "message": "modules.conf already says that", "warnings": warns}
        try:
            bak = _pm_backup(path)
            _atomic_write(path, new)
        except OSError as e:
            return {"ok": False, "message": f"Couldn't write modules.conf: {e.strerror or e}"}
    what = ", ".join(f"{k} {m}" for m, k in sorted(changes.items()))
    _log(f"phone modules: modules.conf set {what} (backup {bak})")
    return {"ok": True, "message": f"modules.conf: {what}. Takes effect when Asterisk restarts.",
            "warnings": warns, "backup": bak}

def _pm_set_live(module: str, start: bool) -> dict:
    if not _ph_ast_running():
        return {"ok": False, "message": "Asterisk isn't running"}
    out = _ph_cli(f"module {'load' if start else 'unload'} {module}", 15)
    now = _ph_module_running(_ph_cli(f"module show like {module.rsplit('.', 1)[0]}"), module)
    first = (out or "").strip().splitlines()[0][:160] if (out or "").strip() else ""
    ok = now == start
    _log(f"phone modules: {'start' if start else 'stop'} {module} -> {'ok' if ok else 'failed'} ({first})")
    if ok:
        return {"ok": True, "message": f"{module} {'started' if start else 'stopped'}"}
    return {"ok": False, "message": f"{module} is still {'stopped' if start else 'running'}"
                                    + (f" -- Asterisk said: {first}" if first else "")
                                    + ". Restarting Asterisk may be needed.", "restart_hint": True}

_RT_STUN_SERVERS = (("stun.l.google.com", 19302), ("stun.cloudflare.com", 3478))

_RT_WATCH_SEC = 600

_RT_STATE = {"watch_until": 0.0, "timer": None}

_RT_LOCK = threading.Lock()

def _rt_stun(local_port: int) -> "tuple[str, int] | None":
    for host, port in _RT_STUN_SERVERS:
        try:
            addr = _socket.getaddrinfo(host, port, _socket.AF_INET, _socket.SOCK_DGRAM)[0][4]
        except OSError:
            continue
        tid = secrets.token_bytes(12)
        req = struct.pack("!HHI", 0x0001, 0, 0x2112A442) + tid
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        try:
            s.bind(("0.0.0.0", local_port))
            s.settimeout(2.5)
            for _ in range(2):
                s.sendto(req, addr)
                try:
                    data, _src = s.recvfrom(2048)
                except _socket.timeout:
                    continue
                if len(data) < 20 or data[8:20] != tid:
                    continue
                i = 20
                while i + 4 <= len(data):
                    atype, alen = struct.unpack_from("!HH", data, i)
                    val = data[i + 4:i + 4 + alen]
                    if atype in (0x0020, 0x0001) and len(val) >= 8 and val[1] == 1:
                        p, ip = struct.unpack_from("!H4s", val, 2)
                        if atype == 0x0020:
                            p ^= 0x2112
                            ip = bytes(a ^ b for a, b in zip(ip, b"\x21\x12\xa4\x42"))
                        return _socket.inet_ntoa(ip), p
                    i += 4 + alen + ((4 - alen % 4) % 4)
        except OSError:
            pass
        finally:
            s.close()
    return None

def _rt_free_port(lo: int, hi: int) -> "int | None":
    for p in range(hi, max(lo, hi - 200) - 1, -1):
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        try:
            s.bind(("0.0.0.0", p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    return None

def _rt_history(on: bool) -> None:
    _ph_cli("pjsip set history " + ("on" if on else "off"), timeout=4)

def _rt_watch_stop() -> None:
    with _RT_LOCK:
        _RT_STATE["watch_until"] = 0.0
        _RT_STATE["timer"] = None
    _rt_history(False)

def _rt_test_out() -> list:
    C = []
    if not _ph_ast_running():
        return [_ph_check("ast", "Asterisk", "fail", "not running", "Start Asterisk, then run the test again")]
    with _RT_LOCK:
        watching = _RT_STATE["watch_until"] > time.time()
    _rt_history(True)
    _ph_cli("pjsip send register *all", timeout=6)
    time.sleep(3.0)
    rows = _rt_history_rows()
    seen = None
    for r in reversed(rows):
        if r["dir"] == "in" and r["msg"].startswith("SIP/2.0"):
            full = _ph_cli(f"pjsip show history entry {r['n']}", timeout=6)
            vm = re.search(r"(?im)^Via:.*?received=([0-9.]+).*?rport=(\d+)", full) or \
                 re.search(r"(?im)^Via:.*?rport=(\d+).*?received=([0-9.]+)", full)
            pm = re.search(r"(?im)^Via:\s*SIP/2\.0/\w+\s+[^:;\s]+:(\d+)", full)
            if vm:
                g = vm.groups()
                ip, rport = (g[0], g[1]) if "." in g[0] else (g[1], g[0])
                seen = (ip, int(rport), int(pm.group(1)) if pm else None, r["addr"])
                break
    if not watching:
        _rt_history(False)
    if seen:
        ip, rport, sent, srv = seen
        if sent is None or rport == sent:
            C.append(_ph_check("sipport", "SIP port going out", "ok",
                               f"provider sees {ip}:{rport}", f"Reply from {srv}. The router kept the port number, which is what you want."))
        else:
            C.append(_ph_check("sipport", "SIP port going out", "warn",
                               f"sent from {sent}, provider sees {ip}:{rport}",
                               "The router changes the port number. Usually still works, but if calls fail or drop, "
                               "turn off SIP ALG on the router"))
    else:
        C.append(_ph_check("sipport", "SIP port going out", "info", "no reply with an address in it",
                           "The provider didn't answer the sign-in in time, or no account signs in. Try again in a minute"))
    lo, hi = _rt_rtp_range()
    port = _rt_free_port(lo, hi)
    if port is None:
        C.append(_ph_check("rtpport", "Audio ports going out", "info", "no free port to test from", ""))
    else:
        res = _rt_stun(port)
        if res is None:
            C.append(_ph_check("rtpport", "Audio ports going out", "fail", f"no answer from a STUN server (sent from UDP {port})",
                               "Outgoing UDP may be blocked, or there is no internet. Check the Pi firewall's outgoing rules and the router"))
        else:
            ip, pp = res
            if pp == port:
                C.append(_ph_check("rtpport", "Audio ports going out", "ok", f"UDP {port} → seen as {ip}:{pp}",
                                   "Port kept the same"))
            else:
                C.append(_ph_check("rtpport", "Audio ports going out", "info", f"UDP {port} → seen as {ip}:{pp}",
                                   "The router changes audio port numbers. Normal for most home routers; HOIP calls "
                                   "still work because Asterisk answers to whatever port audio arrives from"))
            if seen and seen[0] != ip:
                C.append(_ph_check("pubip", "Public address", "warn", f"SIP says {seen[0]}, audio says {ip}",
                                   "Two different public addresses -- a second router or carrier NAT. One-way audio is likely"))
            else:
                C.append(_ph_check("pubip", "Public address", "ok", ip))
    return C

def _rt_channelstats() -> list:
    out = []
    for line in _ph_cli("pjsip show channelstats", timeout=6).splitlines():
        tok = line.split()
        idx = next((i for i, x in enumerate(tok) if re.fullmatch(r"\d+:\d\d:\d\d", x)), None)
        if idx is None or idx < 1 or len(tok) < idx + 10:
            continue
        try:
            nums = [float(x) for x in tok[idx + 2:idx + 10]]
        except ValueError:
            continue
        out.append({"channel": tok[idx - 1], "uptime": tok[idx], "codec": tok[idx + 1],
                    "rx": int(nums[0]), "rx_lost": int(nums[1]), "rx_pct": nums[2], "rx_jitter": nums[3],
                    "tx": int(nums[4]), "tx_lost": int(nums[5]), "tx_pct": nums[6], "tx_jitter": nums[7],
                    "rtt": tok[idx + 10] if len(tok) > idx + 10 else ""})
    return out

def _rt_sip_port() -> int:
    try:
        return _ph_sip_port(_ph_load_ctx())
    except Exception:
        return 5060

def _rt_test_in(start: bool) -> list:
    C = []
    if not _ph_ast_running():
        return [_ph_check("ast", "Asterisk", "fail", "not running", "")]
    now = time.time()
    if start:
        _rt_history(True)
        with _RT_LOCK:
            if _RT_STATE["timer"]:
                _RT_STATE["timer"].cancel()
            _RT_STATE["watch_until"] = now + _RT_WATCH_SEC
            tm = threading.Timer(_RT_WATCH_SEC, _rt_watch_stop)
            tm.daemon = True
            _RT_STATE["timer"] = tm
            tm.start()
    with _RT_LOCK:
        until = _RT_STATE["watch_until"]
    rows = _rt_history_rows()
    invites = [r for r in rows if r["dir"] == "in" and r["msg"].upper().startswith("INVITE")]
    if until > now:
        C.append(_ph_check("watch", "Watching for incoming calls", "info",
                           f"{int((until - now) // 60) + 1} min left",
                           "Have someone call your number or extension, then press Check"))
    elif not invites:
        C.append(_ph_check("watch", "Watching for incoming calls", "info", "off",
                           "Press Start watching, then have someone call you"))
    if invites:
        last = invites[-1]
        answers = [r for r in rows if r["dir"] == "out" and r["ts"] >= last["ts"] and r["msg"].startswith("SIP/2.0")]
        codes = [re.sub(r"^SIP/2\.0\s+", "", a["msg"]) for a in answers][:4]
        when = datetime.fromtimestamp(last["ts"]).strftime("%H:%M:%S")
        ok200 = any(c.startswith("200") for c in codes)
        C.append(_ph_check("invite", "Last incoming call", "ok" if ok200 else "warn",
                           f"{when} from {last['addr']}",
                           ("Reached the Pi and was answered" if ok200 else
                            f"Reached the Pi -- so UDP {_rt_sip_port()} gets in" +
                            (". Pi replied: " + " → ".join(codes) if codes else ". No answer from the Pi yet"))))
    elif until > now:
        C.append(_ph_check("invite", "Last incoming call", "info", "none yet", ""))
    return C

def _route_phone_routertest_post(h: "Handler", data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "sysmon is not running as root"}, 403)
        return
    part = str(data.get("part", "")).strip()
    if part == "out":
        h.send_json({"ok": True, "checks": _rt_test_out()})
    elif part == "audio":
        h.send_json({"ok": True, "calls": _rt_channelstats(), "t": time.time()})
    elif part in ("in", "in_start"):
        h.send_json({"ok": True, "checks": _rt_test_in(part == "in_start")})
    else:
        h.send_json({"ok": False, "message": "Unknown part"}, 400)

def _route_phone_modules_post(h: "Handler", data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "sysmon is not running as root"}, 403)
        return
    op = str(data.get("op", "")).strip()
    module = str(data.get("module", "")).strip()
    value = str(data.get("value", "")).strip()
    if op in ("conf", "live"):
        row, err = _pm_allowed(module)
        if row is None:
            h.send_json({"ok": False, "message": err}, 400)
            return
        if op == "conf":
            if value not in ("load", "noload"):
                h.send_json({"ok": False, "message": "value must be load or noload"}, 400)
                return
            res = _pm_set_conf({module: value})
        else:
            if value not in ("start", "stop"):
                h.send_json({"ok": False, "message": "value must be start or stop"}, 400)
                return
            if value == "stop" and _pm_call_up():
                h.send_json({"ok": False, "message": "A phone call is up -- hang up first"}, 409)
                return
            res = _pm_set_live(module, value == "start")
        h.send_json(res, 200 if res.get("ok") else 409)
        return
    if op == "reinstall":
        res = _pm_reinstall(bool(data.get("update", True)))
        h.send_json(res, 200 if res.get("ok") else 409)
        return
    if op in ("activate", "deactivate"):
        res = _pm_feature(str(data.get("feature", "")).strip(), op == "activate")
        h.send_json(res, 200 if res.get("ok") else 409)
        return
    h.send_json({"ok": False, "message": f"Unknown op {op!r}"}, 400)

def _pm_feature(feature: str, on: bool) -> dict:
    if feature not in _PM_FEATS:
        return {"ok": False, "message": "Unknown feature"}
    sec = _pm_collect(_ph_load_ctx())
    other = [f for f in _PM_FEATS if f != feature][0]
    other_on = next(g for g in sec["groups"] if g["feature"] == other)["configured"]
    mine = [r for r in sec["rows"] if feature in r["features"]]
    free = [r for r in mine if not r["locked"]]
    lbl = _PM_FEAT_LBL[feature]
    lines: list = []
    if on:
        if not free:
            return {"ok": True, "message": f"{lbl}: nothing to change", "details": []}
        res = _pm_set_conf({r["module"]: "load" for r in free})
        if not res["ok"]:
            return res
        lines.append("modules.conf: load " + ", ".join(r["module"] for r in free))
        lines += res.get("warnings", [])
        ok = True
        if sec["asterisk_running"]:
            for r in free:
                if r["running"] or r["file"] is False:
                    if r["file"] is False:
                        lines.append(f"{r['module']}: file missing -- see install options")
                        ok = False
                    continue
                st = _pm_set_live(r["module"], True)
                lines.append(st["message"])
                ok = ok and st["ok"]
            core = [r["module"] for r in mine if r["locked"] and r["running"] is False]
            if core:
                lines.append("Core modules not running: " + ", ".join(core) + " -- restart Asterisk")
                ok = False
        else:
            lines.append("Asterisk isn't running -- the modules load when it starts")
        return {"ok": ok, "message": f"{lbl}: {'activated' if ok else 'activated with problems'}",
                "details": lines, "restart_hint": not ok and sec["asterisk_running"]}
    alone = [r for r in free if len(r["features"]) == 1 or not other_on]
    kept = [r["module"] for r in free if r not in alone]
    if not alone:
        return {"ok": False, "message": f"{lbl}: every module it uses is shared or locked, so nothing can be "
                                        f"turned off without affecting the other feature",
                "details": ["Shared, left running: " + ", ".join(kept)] if kept else []}
    if _pm_call_up():
        return {"ok": False, "message": "A phone call is up -- hang up first"}
    res = _pm_set_conf({r["module"]: "noload" for r in alone})
    if not res["ok"]:
        return res
    lines.append("modules.conf: noload " + ", ".join(r["module"] for r in alone))
    ok = True
    if sec["asterisk_running"]:
        for r in alone:
            if r["running"]:
                st = _pm_set_live(r["module"], False)
                lines.append(st["message"])
                ok = ok and st["ok"]
    if kept:
        lines.append(f"Left running (also used by {_PM_FEAT_LBL[other]}): " + ", ".join(kept))
    return {"ok": ok, "message": f"{lbl}: {'deactivated' if ok else 'deactivated with problems'}",
            "details": lines, "restart_hint": not ok}

_PM_PKG_RE = re.compile(r"^[a-z0-9][a-z0-9+.\-]{1,62}$")

_PM_REINSTALL_SCRIPT = r"""set -e
UPD="$1"; shift
if [ "$UPD" = "1" ]; then
  echo "Updating the package list..."
  apt-get update
fi
echo "Reinstalling: $*"
apt-get install --reinstall -y "$@"
echo "Done. Press Re-check on the Autopatch modules card, then Activate."
"""

def _pm_reinstall(update: bool) -> dict:
    if os.geteuid() != 0:
        return {"ok": False, "message": "sysmon is not running as root"}
    sec = _pm_collect(_ph_load_ctx())
    if not sec["missing_files"]:
        return {"ok": False, "message": "No module files are missing -- nothing to reinstall"}
    pkgs = [p for p in sec["packages"] if _PM_PKG_RE.match(p)]
    if not pkgs:
        return {"ok": False, "message": "Couldn't tell which package should have "
                                        + ", ".join(sec["missing_files"]) + " -- see the manual steps on the card"}
    return _net_start_job("phone_reinstall", "Reinstalling " + " ".join(pkgs),
                          ["bash", "-c", _PM_REINSTALL_SCRIPT, "phone_reinstall", "1" if update else "0"] + pkgs,
                          _NET_INSTALL_TIMEOUT, env=_net_apt_env())

def action_phone_parse(section: str = "") -> dict:
    ctx = _ph_load_ctx()
    sections = []
    for sid, title, fn in _PHONE_SECTIONS:
        if section and sid != section:
            continue
        try:
            body = fn(ctx)
        except Exception as e:
            log.exception("phone section %s failed", sid)
            body = {"found": False, "note": f"could not read: {e}"}
        sections.append(dict(body, id=sid, title=title))
    return {"ok": True, "sections": sections, "files": list(ctx["files"]),
            "missing_files": list(ctx["missing"]), "errors": list(ctx["errors"]),
            "read_only": True}

def _route_phone_get(h: Handler) -> None:
    qs = parse_qs(urlparse(h.path).query)
    section = qs.get("section", [""])[0].strip()
    if section and section not in {sid for sid, _t, _f in _PHONE_SECTIONS}:
        h.send_json({"ok": False, "message": f"Unknown section: {section!r}"}, 400)
        return
    h.send_json(action_phone_parse(section))

_RADIO_PRESET_FIELDS = {
    "rxmixerset":   (int,   0,    1000),
    "txmixaset":    (int,   0,    1000),
    "txmixbset":    (int,   0,    1000),
}

_RADIO_PRESET_BASE = ("rxmixerset", "txmixaset", "txmixbset")

def _coerce_radio_field(name: str, raw) -> int | float | None:
    spec = _RADIO_PRESET_FIELDS.get(name)
    if spec is None:
        return None
    ftype, lo, hi = spec
    try:
        val = ftype(str(raw).strip())
    except (ValueError, TypeError):
        return None
    if not (lo <= val <= hi):
        return None
    return val

def _format_radio_field(name: str, val) -> str:
    spec = _RADIO_PRESET_FIELDS.get(name)
    if spec and spec[0] is float:
        return f"{float(val):.2f}"
    return str(int(val))

def _decode_radio_preset_values(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw:
        return {}
    out: dict = {}

    if "=" in raw:

        for pair in raw.split(";"):
            pair = pair.strip()
            if not pair or "=" not in pair:
                continue
            key, _, val = pair.partition("=")
            key = key.strip().lower()
            coerced = _coerce_radio_field(key, val)
            if coerced is None:
                _log(f"WARN — radio preset: dropping field '{key}'={val!r}")
            else:
                out[key] = coerced
    else:

        parts = [p.strip() for p in raw.split(",")]
        if len(parts) == 3:
            for name, val in zip(_RADIO_PRESET_BASE, parts):
                coerced = _coerce_radio_field(name, val)
                if coerced is not None:
                    out[name] = coerced
        else:
            _log(f"WARN — radio preset: legacy CSV expected 3 values, got {len(parts)}")

    return out

def _encode_radio_preset_values(fields: dict) -> str:
    chunks = []
    for name in _RADIO_PRESET_FIELDS:
        if name in fields and fields[name] is not None:
            chunks.append(f"{name}={_format_radio_field(name, fields[name])}")
    return ";".join(chunks)

def _parse_radio_preset(slot: int) -> dict | None:
    if slot < 1 or slot > 5:
        return None
    raw = _cfg.get("radio_presets", f"radio{slot}_values", fallback="")
    fields = _decode_radio_preset_values(raw)

    if not all(k in fields for k in _RADIO_PRESET_BASE):
        return None
    return fields

def _get_radio_presets() -> dict:
    presets = {}
    for slot in range(1, 6):
        parsed = _parse_radio_preset(slot)
        if parsed:
            title = _cfg.get("radio_presets", f"radio{slot}_title", fallback="")
            entry = dict(parsed)
            entry["title"] = title.strip()
            presets[slot] = entry
        else:
            presets[slot] = None
    return presets

def _resolve_radio_preset_title(slot: int, title: str) -> str:
    new_title = str(title).strip()
    if new_title:
        return new_title
    existing_title = _cfg.get("radio_presets", f"radio{slot}_title", fallback="").strip()
    return existing_title

def _set_radio_preset(slot: int, fields: dict, title: str) -> bool:
    if slot < 1 or slot > 5:
        return False
    if not isinstance(fields, dict):
        return False

    clean: dict = {}
    for name, raw in fields.items():
        key = str(name).strip().lower()
        if key not in _RADIO_PRESET_FIELDS:
            continue
        coerced = _coerce_radio_field(key, raw)
        if coerced is None:
            return False
        clean[key] = coerced

    if not all(k in clean for k in _RADIO_PRESET_BASE):
        return False

    updates = {
        f"radio_presets.radio{slot}_values": _encode_radio_preset_values(clean),
        f"radio_presets.radio{slot}_title": _resolve_radio_preset_title(slot, title),
    }
    return save_config(updates)

def _clear_radio_preset(slot: int) -> bool:
    if slot < 1 or slot > 5:
        return False
    updates = {
        f"radio_presets.radio{slot}_values": "",
        f"radio_presets.radio{slot}_title": "",
    }
    return save_config(updates)

_RADIO_TUNE_DRIVERS = ("simpleusb",)

def _get_radio_tune() -> dict:
    try:
        slot = int(_cfg.get("radio_tune", "active_slot", fallback="0"))
    except (ValueError, TypeError):
        slot = 0
    if slot < 0 or slot > 5:
        slot = 0
    drv = _cfg.get("radio_tune", "active_driver", fallback="").strip().lower()
    if drv not in _RADIO_TUNE_DRIVERS:
        drv = ""
    out = {"active_slot": slot, "active_driver": drv}
    for d in _RADIO_TUNE_DRIVERS:
        raw = _cfg.get("radio_tune", f"{d}_values", fallback="")
        out[d] = _decode_radio_preset_values(raw)
    return out

def _set_radio_tune(driver: str, fields: dict) -> bool:
    driver = (driver or "").strip().lower()
    if driver not in _RADIO_TUNE_DRIVERS:
        _log(f"WARN — radio_tune mirror: unknown driver {driver!r}")
        return False
    current = _get_radio_tune().get(driver, {})
    for name, raw in (fields or {}).items():
        key = str(name).strip().lower()
        coerced = _coerce_radio_field(key, raw)
        if coerced is None:
            _log(f"WARN — radio_tune mirror: dropping field '{key}'={raw!r}")
            continue
        current[key] = coerced
    return save_config({
        f"radio_tune.{driver}_values": _encode_radio_preset_values(current),
    })

def _set_active_radio_slot(slot: int, driver: str) -> bool:
    try:
        slot = int(slot)
    except (ValueError, TypeError):
        return False
    if slot < 0 or slot > 5:
        return False
    driver = (driver or "").strip().lower()
    if slot != 0 and driver not in _RADIO_TUNE_DRIVERS:
        return False
    return save_config({
        "radio_tune.active_slot":   str(slot),
        "radio_tune.active_driver": driver if slot != 0 else "",
    })

_SIMPLEUSB_FILE = Path("/etc/asterisk/simpleusb.conf")

_SU_BOOL_ALIASES = {"yes": "yes", "1": "yes", "no": "no", "0": "no"}

def _su_norm_bool(raw) -> "str | None":
    return _SU_BOOL_ALIASES.get(str(raw).strip().lower())

def _su_norm_choice(spec: dict, raw) -> "str | None":
    val = str(raw).strip().lower()
    return val if val in spec["values"] else None

_TUNE_STANZA_RE = re.compile(r'^\s*\[([^\]]+)\]\s*(\([^)]*\))?\s*(?:[;#].*)?$')

_TUNE_KV_RE = re.compile(r'^(\s*)([A-Za-z_][\w]*)(\s*=\s*)([^;#]*?)(\s*[;#].*)?$')

def _tune_scan_conf(lines: list, keys: tuple) -> tuple:
    wanted = {k.lower() for k in keys} | {"devstr"}
    occurrences: dict = {}
    stanzas: list = []
    devstr_stanzas: set = set()
    cur_stanza = ""
    cur_template = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith((";", "#")):
            continue
        m = _TUNE_STANZA_RE.match(line)
        if m:
            cur_stanza = m.group(1).strip()
            cur_template = (m.group(2) or "").strip() == "(!)"
            stanzas.append((cur_stanza, idx, cur_template))
            continue
        kv = _TUNE_KV_RE.match(line)
        if not kv:
            continue
        key_lower = kv.group(2).lower()
        if key_lower not in wanted:
            continue
        occurrences.setdefault(key_lower, []).append(
            (idx, cur_stanza, cur_template))
        if key_lower == "devstr":
            devstr_stanzas.add(cur_stanza)
    return occurrences, stanzas, devstr_stanzas

def _tune_effective_value(lines: list, occ_list: list) -> str:
    non_tmpl = [o for o in occ_list if not o[2]]
    idx = (non_tmpl[-1] if non_tmpl else occ_list[-1])[0]
    return _TUNE_KV_RE.match(lines[idx]).group(4).strip()

def _tune_apply_updates(lines: list, formatted: dict) -> tuple:
    occurrences, stanzas, devstr_stanzas = _tune_scan_conf(
        lines, tuple(formatted.keys()))

    node_stanzas = [s for s in stanzas
                    if not s[2] and s[0].strip().lower() != "general"]
    target = next((s for s in node_stanzas if s[0] in devstr_stanzas),
                  node_stanzas[0] if node_stanzas else None)

    new_lines = list(lines)
    updated_keys: set = set()
    to_append: list = []
    blank_keys: set = set()

    for key, val_str in formatted.items():
        occ_list = occurrences.get(key, [])
        non_tmpl = [o for o in occ_list if not o[2]]
        if val_str == "":
            blank_keys.add(key)
            if non_tmpl:
                idx = non_tmpl[-1][0]
                new_lines[idx] = "; " + new_lines[idx].lstrip()
                updated_keys.add(key)
            else:
                _log(f"tune save: {key} blank, no node-stanza line to switch off")
            continue
        if non_tmpl:
            idx = non_tmpl[-1][0]
            m = _TUNE_KV_RE.match(new_lines[idx])

            new_lines[idx] = (f"{m.group(1)}{m.group(2)}{m.group(3)}"
                              f"{val_str}{m.group(5) or ''}\n")
            updated_keys.add(key)
        else:

            to_append.append((key, val_str))

    appended_keys: set = set()
    if to_append:
        if target is not None:

            t_pos = next(i for i, s in enumerate(stanzas) if s is target)
            insert_at = (stanzas[t_pos + 1][1]
                         if t_pos + 1 < len(stanzas) else len(new_lines))

            while insert_at > target[1] + 1 and \
                    new_lines[insert_at - 1].strip() == "":
                insert_at -= 1
            stanza_label = target[0]
        elif not stanzas:
            insert_at = len(new_lines)
            stanza_label = "(end of file)"
        else:
            missing = ", ".join(k for k, _ in to_append)
            return (None, updated_keys, set(),
                    f"no node stanza found to hold new key(s): {missing} — "
                    f"file has only template/[general] stanzas")
        if insert_at > 0 and new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        block = [f"{k} = {v}\n" for k, v in to_append]
        new_lines[insert_at:insert_at] = block
        appended_keys = {k for k, _ in to_append}
        _log(f"tune save: appended {', '.join(sorted(appended_keys))} "
             f"to stanza [{stanza_label}]")

    unplaced = set(formatted) - updated_keys - appended_keys - blank_keys
    if unplaced:
        return (None, updated_keys, appended_keys,
                f"could not place key(s): {', '.join(sorted(unplaced))}")

    return new_lines, updated_keys, appended_keys, ""

def parse_simpleusb_tune_settings(path: Path = _SIMPLEUSB_FILE) -> dict:

    result = {key: None for key in _SIMPLEUSB_FIELD_SPECS}
    result["devstr"] = None
    result["path"]   = str(path)
    result["exists"] = False

    if not path.exists():
        return result

    result["exists"] = True
    field_keys = tuple(_SIMPLEUSB_FIELD_SPECS.keys())

    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        occurrences, _stanzas, _dev = _tune_scan_conf(lines, field_keys)
        for key, occ_list in occurrences.items():
            val_clean = _tune_effective_value(lines, occ_list)
            if key == "devstr":
                result["devstr"] = val_clean
                continue
            spec = _SIMPLEUSB_FIELD_SPECS.get(key)
            if spec is None:
                continue
            if spec["type"] == "int":
                try:
                    result[key] = int(val_clean)
                except ValueError:
                    _log(f"WARN — simpleusb {key} not numeric: {val_clean}")
            elif spec["type"] == "bool":
                normalized = _su_norm_bool(val_clean)
                if normalized is not None:
                    result[key] = normalized
                else:
                    _log(f"WARN — simpleusb {key} not yes/no: {val_clean}")
            elif spec["type"] in ("enum", "pin"):
                normalized = _su_norm_choice(spec, val_clean)
                if normalized is not None:
                    result[key] = normalized
                else:
                    _log(f"WARN — simpleusb {key} not one of "
                         f"{'/'.join(spec['values'])}: {val_clean}")
    except Exception as e:
        _log(f"WARN — simpleusb parse error: {e}")

    return result

def save_simpleusb_tune_settings(updates: dict, path: Path = _SIMPLEUSB_FILE) -> tuple[bool, str]:

    if not path.exists():
        msg = f"File not found: {path}"
        _log(f"WARN — simpleusb save: {msg}")
        return False, msg

    formatted: dict = {}
    for key, val in updates.items():
        if val is None:
            continue
        spec = _SIMPLEUSB_FIELD_SPECS.get(key)
        if spec is None:
            _log(f"WARN — simpleusb save: dropping unknown field {key!r}")
            continue
        if spec["type"] == "int":
            try:
                ival = int(val)
            except (TypeError, ValueError):
                msg = f"{key} must be numeric, got {repr(val)}"
                return False, msg
            if ival < spec["min"] or ival > spec["max"]:
                msg = f"{key} out of bounds ({spec['min']}–{spec['max']}): {ival}"
                return False, msg
            formatted[key] = str(ival)
        elif spec["type"] == "bool":
            normalized = _su_norm_bool(val)
            if normalized is None:
                msg = f"{key} must be 'yes' or 'no', got {repr(val)}"
                return False, msg
            formatted[key] = normalized
        elif spec["type"] in ("enum", "pin"):
            if spec["type"] == "pin" and str(val).strip() == "":
                formatted[key] = ""
                continue
            normalized = _su_norm_choice(spec, val)
            if normalized is None:
                msg = (f"{key} must be one of {', '.join(spec['values'])}, "
                       f"got {repr(val)}")
                return False, msg
            formatted[key] = normalized

    if not formatted:
        return False, "no settings to update"

    try:

        old_values = parse_simpleusb_tune_settings(path)

        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        new_lines, updated_keys, appended_keys, err = \
            _tune_apply_updates(lines, formatted)
        if err:
            _log(f"WARN — simpleusb save: {err}")
            return False, err

        tmp = path.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
            f.flush()
            os.fsync(f.fileno())  

        os.replace(tmp, path)

        parts = []
        if updated_keys:
            parts.append(f"Updated: {', '.join(sorted(updated_keys))}")
        if appended_keys:
            parts.append(f"Added: {', '.join(sorted(appended_keys))}")
        msg = "; ".join(parts) or "No changes"

        audit_log = []
        for key in sorted(updated_keys | appended_keys):
            old_val = old_values.get(key)
            new_val = formatted[key] or "(blank)"

            audit_log.append(f"{key} {old_val}→{new_val}")

        _log(f"simpleusb tune saved: {msg} ({'; '.join(audit_log)})")
        return True, msg

    except Exception as e:
        msg = f"Save failed: {str(e)}"
        _log(f"WARN — simpleusb save error: {msg}", stderr=True)
        return False, msg

_RADIO_RESTART_LOCK       = threading.Lock()

_RADIO_RESTART_STATE_LOCK = threading.Lock()

_radio_restart_state = {
    "phase":       "idle",
    "driver":      "",
    "started_at":  0.0,
    "finished_at": 0.0,
    "last_ok":     None,
    "last_msg":    "",
    "unload_ok":   None,
}

def _radio_restart_snapshot() -> dict:
    with _RADIO_RESTART_STATE_LOCK:
        return dict(_radio_restart_state)

def _radio_restart_update(**kw) -> None:
    with _RADIO_RESTART_STATE_LOCK:
        _radio_restart_state.update(kw)

def radio_stack_restarting() -> bool:
    with _RADIO_RESTART_STATE_LOCK:
        return _radio_restart_state["phase"] != "idle"

def _restart_radio_stack(driver: str) -> None:
    module = f"chan_{driver}.so"
    unload_ok = False
    try:

        _radio_restart_update(phase="unloading", driver=driver,
                              started_at=time.time(), unload_ok=None)
        try:
            r = subprocess.run(
                ["asterisk", "-rx", f"module unload {module}"],
                capture_output=True, text=True, timeout=10,
            )
            out = ((r.stdout or "") + (r.stderr or "")).lower()
            unload_ok = (r.returncode == 0) and ("unable" not in out) and ("error" not in out)
            _log(f"radio restart: unload {module} — "
                 f"{'OK' if unload_ok else 'not unloaded (expected under app_rpt), proceeding'}")
        except Exception as e:
            _log(f"radio restart: unload {module} attempt failed ({e}) — proceeding")
        _radio_restart_update(unload_ok=unload_ok)

        _radio_restart_update(phase="settling")
        time.sleep(2)

        _radio_restart_update(phase="restarting")
        try:
            r = subprocess.run(
                ["systemctl", "restart", "asterisk.service"],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode == 0:
                _radio_restart_update(last_ok=True,
                                      last_msg="Asterisk restarted")
                _log("radio restart: asterisk.service restarted OK")
            else:
                err = (r.stderr or "").strip() or "unknown error"
                _radio_restart_update(last_ok=False,
                                      last_msg=f"Asterisk restart failed: {err}")
                _log(f"WARN — radio restart failed: {err}", stderr=True)
        except subprocess.TimeoutExpired:
            _radio_restart_update(last_ok=False,
                                  last_msg="Asterisk restart timed out (>30s)")
            _log("WARN — radio restart timed out (>30s)", stderr=True)
        except Exception as e:
            _radio_restart_update(last_ok=False,
                                  last_msg=f"Restart error: {e}")
            _log(f"WARN — radio restart exception: {e}", stderr=True)
    finally:
        _radio_restart_update(phase="idle", finished_at=time.time())
        _RADIO_RESTART_LOCK.release()

def start_radio_stack_restart(driver: str) -> tuple[bool, str]:
    driver = (driver or "").strip().lower()
    if driver not in _RADIO_TUNE_DRIVERS:
        return False, f"unknown driver {driver!r}"
    if not _RADIO_RESTART_LOCK.acquire(blocking=False):
        return False, "restart already in progress"
    try:
        t = threading.Thread(target=_restart_radio_stack, args=(driver,),
                             name="radio-restart", daemon=True)
        t.start()
        return True, "restart started"
    except Exception as e:

        _RADIO_RESTART_LOCK.release()
        _log(f"WARN — radio restart thread start failed: {e}", stderr=True)
        return False, f"failed to start restart thread: {e}"

def _asterisk_is_up(driver: str) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["asterisk", "-rx", "core show uptime"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0 or "uptime" not in (r.stdout or "").lower():
            return False, "asterisk CLI not answering"
    except Exception as e:
        log.debug("_asterisk_is_up: %s", e)
        return False, "asterisk CLI not answering"

    try:
        settings = parse_simpleusb_tune_settings()
        if not settings:
            return True, "up (tune file empty or unparsed)"
    except Exception as e:
        return True, f"up (tune re-read failed: {e})"
    return True, "up"

_RN_FIELDS = {
    "duplex":       {"type": "int",  "min": 0, "max": 4,     "default": "2"},
    "telemdefault": {"type": "int",  "min": 0, "max": 2,     "default": "1"},
    "hangtime":     {"type": "int",  "min": 0, "max": 60000, "default": "5000"},
    "linktolink":   {"type": "bool",                          "default": "no"},
}

_RN_KEY_LINE_RE = re.compile(r"^(\s*)([A-Za-z_]\w*)(\s*=\s*)([^;]*?)(\s*;.*)?$")

def _rn_norm(key: str, raw: str) -> str:
    val = (raw or "").strip().split()[0] if (raw or "").strip() else ""
    if _RN_FIELDS[key]["type"] == "bool":
        low = val.lower()
        if low in ("yes", "1", "true", "on", "y"):
            return "yes"
        if low in ("no", "0", "false", "off", "n"):
            return "no"
    return val

def _rn_source(secs: list, name: str, key: str, _depth: int = 0) -> "tuple[str, str]":
    if _depth > 5:
        return "", ""
    val, origin = "", ""
    for s in secs:
        if s["name"] != name:
            continue
        for t in s["templates"]:
            v2, o2 = _rn_source(secs, t, key, _depth + 1)
            if o2:
                val, origin = v2, o2
        for k, v, *_ in s["kv"]:
            if k.strip().lower() == key:
                val, origin = v, name
    return val, origin

def _rn_role(kv: dict) -> str:
    rx = (kv.get("rxchannel", "").split() or [""])[0]
    low = rx.lower()
    if low.startswith("simpleusb/"):
        return "radio (SimpleUSB)"
    if low.startswith("radio/") or low.startswith("usbradio/"):
        return "radio (USBRadio)"
    if low.startswith("usrp/"):
        return "USRP bridge"
    if "pseudo" in low:
        return "no radio (hub)"
    return rx or "no rxchannel"

def read_rpt_node_settings(ast_dir=None) -> dict:
    ctx = {"dir": Path(ast_dir or _AST_DIR), "conf": {"rpt.conf": []},
           "files": [], "missing": [], "errors": []}
    _ph_parse_file(ctx, "rpt.conf", "rpt.conf", {"sec": None}, 0, False)
    secs = ctx["conf"]["rpt.conf"]
    path = str(ctx["dir"] / "rpt.conf")
    if "rpt.conf" in ctx["missing"]:
        return {"ok": False, "path": path, "nodes": [], "message": "rpt.conf not found"}
    if ctx["errors"] and not secs:
        return {"ok": False, "path": path, "nodes": [], "message": "; ".join(ctx["errors"])}
    dash = _ph_dash_info()
    pnodes = dash.get("phone_nodes") or {}
    nodes = []
    for name in dict.fromkeys(s["name"] for s in secs):
        if not name.isdigit() or _RPT_NON_NODE_RE.match(name):
            continue
        own = [s for s in secs if s["name"] == name]
        if any(s["is_template"] for s in own):
            continue
        kv, managed, _f = _ph_resolve(secs, name)
        last = own[-1]
        values = {}
        for key, spec in _RN_FIELDS.items():
            raw, origin = _rn_source(secs, name, key)
            src = ("set on node" if origin == name else f"from {origin}") if origin else "default"
            values[key] = {"value": _rn_norm(key, raw) if origin else spec["default"],
                           "source": src}
        role = _rn_role(kv)
        if name in pnodes:
            role = f"phone node for {pnodes[name]}"
        elif name == dash.get("phone_node"):
            role = "phone bridge"
        locked = ""
        if managed or last["managed"]:
            locked = "Written by the dashboard's phone setup -- change it there"
        elif last["file"] != "rpt.conf":
            locked = f"Set in {last['file']} -- edit that file on the Edit tab"
        nodes.append({"node": name, "private": int(name) <= 1999, "role": role,
                      "file": last["file"], "editable": not locked, "locked": locked,
                      "values": values})
    nodes.sort(key=lambda n: int(n["node"]))
    return {"ok": True, "path": path, "nodes": nodes, "message": "",
            "warnings": ctx["errors"] + [f"missing include: {m}" for m in ctx["missing"]]}

def _rn_apply(lines: list, node: str, changes: dict) -> "tuple[list, list, list]":
    starts = []
    in_cmt = False
    for i, raw in enumerate(lines):
        line = raw.strip()
        if in_cmt:
            if "--;" in line:
                in_cmt = False
            continue
        if line.startswith(";--"):
            in_cmt = "--;" not in line[3:]
            continue
        sm = _PH_SEC_RE.match(line)
        if sm:
            starts.append((i, sm.group(1).strip()))
    hdr = [i for i, (_n, nm) in enumerate(starts) if nm == node]
    if not hdr:
        raise ValueError(f"[{node}] not found in rpt.conf")
    k = hdr[-1]
    begin = starts[k][0]
    end = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
    new = list(lines)
    updated, added = [], []
    inserts = []
    for key, val in changes.items():
        hit = None
        in_cmt = False
        for i in range(begin + 1, end):
            line = new[i].strip()
            if in_cmt:
                if "--;" in line:
                    in_cmt = False
                continue
            if line.startswith(";--"):
                in_cmt = "--;" not in line[3:]
                continue
            m = _RN_KEY_LINE_RE.match(new[i].rstrip("\n"))
            if m and m.group(2).lower() == key:
                hit = (i, m)
        if hit:
            i, m = hit
            nl = "\n" if new[i].endswith("\n") else ""
            new[i] = f"{m.group(1)}{m.group(2)}{m.group(3)}{val}{m.group(5) or ''}{nl}"
            updated.append(key)
        else:
            inserts.append(f"{key} = {val}\n")
            added.append(key)
    if inserts:
        new[begin + 1:begin + 1] = inserts
    return new, updated, added

def save_rpt_node_settings(node: str, changes: dict, reload: bool = False,
                           ast_dir=None) -> "tuple[bool, str]":
    cur = read_rpt_node_settings(ast_dir)
    if not cur["ok"]:
        return False, cur["message"]
    entry = next((n for n in cur["nodes"] if n["node"] == node), None)
    if entry is None:
        return False, f"Node {node} is not in rpt.conf"
    if not entry["editable"]:
        return False, entry["locked"]
    todo = {k: v for k, v in changes.items() if entry["values"][k]["value"] != v}
    if not todo:
        return True, "No changes"
    path = Path(ast_dir or _AST_DIR) / "rpt.conf"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        new, updated, added = _rn_apply(lines, node, todo)
        if new != lines:
            _atomic_write(path, "".join(new))
    except (OSError, ValueError) as e:
        _log(f"WARN — rpt node save {node}: {e}")
        return False, f"Save failed: {e}"
    audit = "; ".join(f"{k} {entry['values'][k]['value']}→{v}" for k, v in sorted(todo.items()))
    _log(f"rpt.conf [{node}] saved: {audit}")
    parts = []
    if updated:
        parts.append(f"Updated: {', '.join(sorted(updated))}")
    if added:
        parts.append(f"Added: {', '.join(sorted(added))}")
    msg = f"[{node}] " + "; ".join(parts)
    if reload:
        out, err = _run_with_stderr(["asterisk", "-rx", "module reload app_rpt"], timeout=15)
        if err and not out:
            _log(f"WARN — rpt node save {node}: reload failed: {err}")
            return True, f"{msg}. Saved, but the reload failed: {err.splitlines()[0]}"
        msg += f". app_rpt reload: {(out.splitlines() or ['sent'])[0]}"
    else:
        msg += ". Not loaded yet -- reload app_rpt or restart Asterisk"
    return True, msg

def _route_rpt_nodes_get(h: Handler) -> None:
    h.send_json(read_rpt_node_settings())

def _route_rpt_nodes_post(h: Handler, data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "This operation requires root privileges (try: sudo)"}, 403)
        return
    node = str(data.get("node", "")).strip()
    if not node.isdigit() or len(node) > 7:
        h.send_json({"ok": False, "message": "node must be a node number"}, 400)
        return
    raw = data.get("changes")
    if not isinstance(raw, dict) or not raw:
        h.send_json({"ok": False, "message": "No settings to update"}, 400)
        return
    changes = {}
    for key, val in raw.items():
        spec = _RN_FIELDS.get(key)
        if spec is None:
            h.send_json({"ok": False, "message": f"Unknown setting {key!r}"}, 400)
            return
        if spec["type"] == "bool":
            norm = _rn_norm(key, str(val))
            if norm not in ("yes", "no"):
                h.send_json({"ok": False, "message": f"{key} must be yes or no"}, 400)
                return
            changes[key] = norm
            continue
        try:
            ival = int(str(val).strip())
        except (TypeError, ValueError):
            h.send_json({"ok": False, "message": f"{key} must be a whole number"}, 400)
            return
        if not spec["min"] <= ival <= spec["max"]:
            h.send_json({"ok": False,
                         "message": f"{key} must be {spec['min']}–{spec['max']} (got {ival})"}, 400)
            return
        changes[key] = str(ival)
    ok, msg = save_rpt_node_settings(node, changes, bool(data.get("reload")))
    h.send_json({"ok": ok, "message": msg}, 200 if ok else 400)

def _route_simpleusb_tune_get(h: Handler) -> None:

    settings = parse_simpleusb_tune_settings()
    h.send_json({
        "ok":       settings.get("exists", False),
        "settings": {
            "devstr": settings.get("devstr"),
            **{key: settings.get(key) for key in _SIMPLEUSB_FIELD_SPECS},
        },
        "path":     settings.get("path"),
        "exists":   settings.get("exists"),
        "module":   module_state("chan_simpleusb.so"),
    })

def _route_simpleusb_tune_post(h: Handler, data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "This operation requires root privileges (try: sudo)"}, 403)
        return

    updates = {}
    for key, spec in _SIMPLEUSB_FIELD_SPECS.items():
        val = data.get(key)
        if val is None:
            continue
        if spec["type"] == "int":
            try:
                ival = int(val)
            except (TypeError, ValueError):
                h.send_json({
                    "ok": False,
                    "message": f"{key} must be numeric (got {repr(val)})"
                }, 400)
                return
            if ival < spec["min"] or ival > spec["max"]:
                h.send_json({
                    "ok": False,
                    "message": f"{key} value {ival} out of bounds — must be {spec['min']}–{spec['max']}"
                }, 400)
                return
            updates[key] = ival
        elif spec["type"] == "bool":
            normalized = _su_norm_bool(val)
            if normalized is None:
                h.send_json({
                    "ok": False,
                    "message": f"{key} must be 'yes' or 'no' (got {repr(val)})"
                }, 400)
                return
            updates[key] = normalized
        elif spec["type"] in ("enum", "pin"):
            if spec["type"] == "pin" and str(val).strip() == "":
                updates[key] = ""
                continue
            normalized = _su_norm_choice(spec, val)
            if normalized is None:
                h.send_json({
                    "ok": False,
                    "message": f"{key} must be one of "
                               f"{', '.join(spec['values'])} (got {repr(val)})"
                }, 400)
                return
            updates[key] = normalized

    if not updates:
        h.send_json({
            "ok": False,
            "message": "no settings to update — provide at least one SimpleUSB setting"
        }, 400)
        return

    ok, msg = save_simpleusb_tune_settings(updates)
    if not ok:
        h.send_json({
            "ok": False,
            "message": msg
        }, 500)
        return

    if not _set_radio_tune("simpleusb", {k: v for k, v in updates.items()
                                          if k in _RADIO_PRESET_FIELDS}):
        _log("WARN — simpleusb save: radio_tune mirror update failed")

    slot_raw = data.get("slot")
    if slot_raw is not None:
        try:
            slot = int(slot_raw)
        except (TypeError, ValueError):
            slot = -1
        if 1 <= slot <= 5:
            if not _set_active_radio_slot(slot, "simpleusb"):
                _log(f"WARN — simpleusb save: active_slot={slot} persist failed")
        else:
            _log(f"WARN — simpleusb save: ignoring bad slot {slot_raw!r}")

    reload_requested = bool(data.get("reload", False))
    restart_state = None
    restart_msg = ""
    if reload_requested:
        started, restart_msg = start_radio_stack_restart("simpleusb")
        if not started and "in progress" in restart_msg:
            h.send_json({
                "ok": False,
                "message": f"Saved, but restart not started: {restart_msg}",
                "restart": "busy",
            }, 409)
            return
        restart_state = "started" if started else "failed"

    h.send_json({
        "ok":          True,
        "message":     msg,
        "restart":     restart_state,
        "restart_msg": restart_msg or None,

        "reload_ok":   None,
        "reload_msg":  None,
    })

def _route_radio_presets_get(h: Handler) -> None:
    presets = _get_radio_presets()
    h.send_json({
        "ok": True,
        "presets": presets,

        "tune": _get_radio_tune(),
    })

def _route_radio_driver_get(h: Handler) -> None:
    su = module_state("chan_simpleusb.so")
    su_on = su in ("load", "require")
    active = "simpleusb" if su_on else None

    h.send_json({
        "ok":        True,
        "simpleusb": su,
        "active":    active,
        "none":      active is None,
    })

def _route_radio_stack_status(h: Handler) -> None:
    snap = _radio_restart_snapshot()
    restarting = radio_stack_restarting()
    elapsed = 0.0
    if snap["started_at"]:
        end = snap["finished_at"] if (not restarting and snap["finished_at"]) else time.time()
        elapsed = max(0.0, end - snap["started_at"])

    resp = {
        "ok":         True,
        "restarting": restarting,
        "phase":      snap["phase"],
        "driver":     snap["driver"],
        "last_ok":    snap["last_ok"],
        "last_msg":   snap["last_msg"],
        "unload_ok":  snap["unload_ok"],
        "elapsed":    round(elapsed, 1),
        "up":         None,
        "up_detail":  "",
    }
    if not restarting:
        drv = snap["driver"] or "simpleusb"
        up, detail = _asterisk_is_up(drv)
        resp["up"] = up
        resp["up_detail"] = detail
    h.send_json(resp)

def _route_radio_presets_post(h: Handler, data: dict) -> None:
    try:
        slot = int(data.get("slot", 0))
        if slot < 1 or slot > 5:
            h.send_json({"ok": False, "message": "slot must be 1–5"}, 400)
            return

        if data.get("clear"):
            if _clear_radio_preset(slot):
                h.send_json({"ok": True, "message": f"Radio {slot} preset cleared"})
            else:
                h.send_json({"ok": False, "message": f"Failed to clear preset {slot}"}, 500)
            return

        title = str(data.get("title", "")).strip()

        fields: dict = {}
        for name in _RADIO_PRESET_FIELDS:
            if name in data and data[name] is not None and str(data[name]).strip() != "":
                coerced = _coerce_radio_field(name, data[name])
                if coerced is None:
                    ftype, lo, hi = _RADIO_PRESET_FIELDS[name]
                    h.send_json({
                        "ok": False,
                        "message": f"{name} invalid or out of bounds "
                                   f"({lo}–{hi}) — got {data[name]!r}"
                    }, 400)
                    return
                fields[name] = coerced

        missing = [k for k in _RADIO_PRESET_BASE if k not in fields]
        if missing:
            h.send_json({
                "ok": False,
                "message": f"missing required field(s): {', '.join(missing)}"
            }, 400)
            return

        if _set_radio_preset(slot, fields, title):

            drv = str(data.get("driver", "")).strip().lower()
            if drv in _RADIO_TUNE_DRIVERS:
                if not _set_active_radio_slot(slot, drv):
                    _log(f"WARN — preset save: active_slot={slot} persist failed")

                if not _set_radio_tune(drv, fields):
                    _log("WARN — preset save: radio_tune mirror update failed")
            saved_title = _cfg.get("radio_presets", f"radio{slot}_title", fallback="").strip()
            h.send_json({
                "ok": True,
                "message": f"Radio {slot} preset saved: {saved_title or f'Radio {slot}'}"
            })
        else:
            h.send_json({
                "ok": False,
                "message": f"Failed to save preset {slot}"
            }, 500)

    except (ValueError, TypeError) as e:
        h.send_json({
            "ok": False,
            "message": f"Invalid input: {str(e)}"
        }, 400)

_RADIO_TUNE_DRIVER_FIELDS = {
    "simpleusb": tuple(_SIMPLEUSB_FIELD_SPECS.keys()),
}

_RADIO_TUNE_SAVE_FN = {
    "simpleusb": save_simpleusb_tune_settings,
}

def _radio_tune_save_preset(data: dict, driver: str, updates: dict) -> "tuple[bool, str] | tuple[None, None]":
    slot_raw = data.get("preset_slot")
    if slot_raw is None:
        return None, None

    try:
        slot = int(slot_raw)
    except (TypeError, ValueError):
        slot = -1
    if not (1 <= slot <= 5):
        preset_msg = f"ignoring bad preset_slot {slot_raw!r} — must be 1–5"
        _log(f"WARN — {driver} tune save: {preset_msg}")
        return False, preset_msg

    title = str(data.get("preset_title", "")).strip()

    preset_fields = {k: v for k, v in updates.items()
                      if k in _RADIO_PRESET_FIELDS}
    missing = [k for k in _RADIO_PRESET_BASE if k not in preset_fields]
    if missing:
        preset_msg = f"preset not saved — missing required field(s): {', '.join(missing)}"
        _log(f"WARN — {driver} tune save: {preset_msg}")
        return False, preset_msg

    if _set_radio_preset(slot, preset_fields, title):
        if not _set_active_radio_slot(slot, driver):
            _log(f"WARN — {driver} tune save: active_slot={slot} persist failed")
        saved_title = _cfg.get("radio_presets", f"radio{slot}_title", fallback="").strip()
        return True, f"Radio {slot} preset saved: {saved_title or f'Radio {slot}'}"

    preset_msg = f"failed to save preset {slot}"
    _log(f"WARN — {driver} tune save: {preset_msg}")
    return False, preset_msg

def _route_radio_tune_save_post(h: Handler, data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "This operation requires root privileges (try: sudo)"}, 403)
        return

    driver = str(data.get("driver", "")).strip().lower()
    if driver not in _RADIO_TUNE_DRIVER_FIELDS:
        h.send_json({
            "ok": False,
            "message": f"unknown driver {driver!r} — must be 'simpleusb'"
        }, 400)
        return

    allowed_fields = _RADIO_TUNE_DRIVER_FIELDS[driver]
    updates = {k: data[k] for k in allowed_fields if k in data and data[k] is not None}

    if not updates:
        h.send_json({
            "ok": False,
            "message": "no settings to update — provide at least one SimpleUSB setting"
        }, 400)
        return

    ok, msg = _RADIO_TUNE_SAVE_FN[driver](updates)
    if not ok:
        h.send_json({"ok": False, "message": msg}, 400)
        return

    mirror_updates = {k: v for k, v in updates.items()
                      if k in _RADIO_PRESET_FIELDS}
    if mirror_updates and not _set_radio_tune(driver, mirror_updates):
        _log(f"WARN — {driver} tune save: radio_tune mirror update failed")

    preset_saved, preset_msg = _radio_tune_save_preset(data, driver, updates)

    reload_requested = bool(data.get("reload", False))
    restart_state = None
    restart_msg = ""
    if reload_requested:
        started, restart_msg = start_radio_stack_restart(driver)
        if not started and "in progress" in restart_msg:
            h.send_json({
                "ok": False,
                "message": f"Saved, but restart not started: {restart_msg}",
                "restart": "busy",
                "preset_saved": preset_saved,
                "preset_msg": preset_msg,
            }, 409)
            return
        restart_state = "started" if started else "failed"

    h.send_json({
        "ok":          True,
        "message":     msg,
        "preset_saved": preset_saved,
        "preset_msg":   preset_msg,
        "restart":      restart_state,
        "restart_msg":  restart_msg or None,
    })

AMBE_DEVICES: "dict[tuple, str]" = {
    ("0403", "6015"): "ThumbDV",
}

AMBE_FTDI_VIDS: "dict[str, str]" = {
    "0403": "Serial adapter (FTDI) — possible AMBE",
}

def _usb_tty_map() -> "dict[str, list]":
    import glob as _glob
    result: "dict[str, list]" = {}
    for pattern in ("/sys/class/tty/ttyUSB*", "/sys/class/tty/ttyACM*"):
        for tty_sysfs in _glob.glob(pattern):
            dev_name = Path(tty_sysfs).name
            dev_node = f"/dev/{dev_name}"
            device_link = Path(tty_sysfs) / "device"
            if not device_link.exists():
                continue
            try:
                resolved = device_link.resolve()

                p = resolved
                for _ in range(6):
                    p = p.parent
                    if (p / "idVendor").exists():
                        key = str(p)
                        result.setdefault(key, []).append(dev_node)
                        break
            except Exception as e:
                log.debug("_usb_tty_map: %s", e)
                continue
    return result

def _udev_symlink_for_nodes(dev_nodes: list) -> "str | None":
    try:
        for entry in os.scandir("/dev"):
            try:
                if entry.is_symlink():
                    if os.path.realpath(entry.path) in dev_nodes:
                        return entry.path
            except Exception as e:
                log.debug("_udev_symlink_for_nodes: %s", e)
                continue
    except Exception as e:
        log.debug("_udev_symlink_for_nodes: %s", e)
        pass
    return None

def _read_ambe_watchdog() -> "dict | None":
    p = Path("/run/ambe_status.json")
    try:
        if not p.exists():
            return None
        if time.time() - p.stat().st_mtime > 30:
            return None
        return json.loads(p.read_text())
    except Exception as e:
        log.debug("_read_ambe_watchdog: %s", e)
        return None

def _ambe_layer2(node: str) -> dict:
    try:
        r = subprocess.run(
            ["stty", "-F", node],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0:
            return {"ok": True, "detail": f"stty accessible · {node}"}
        stderr = (r.stderr or "").strip()
        if "Permission denied" in stderr:
            return {"ok": False, "detail": f"permission denied · {node}"}
        if "No such file" in stderr:
            return {"ok": False, "detail": f"device node missing · {node}"}
        return {"ok": False, "detail": (stderr[:80] or "stty failed")}
    except FileNotFoundError:
        return {"ok": False, "detail": "stty not found"}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)[:80]}

def _ambe_layer3(node: str) -> dict:
    try:
        r = subprocess.run(
            ["fuser", node],
            capture_output=True, text=True, timeout=4,
        )
    except FileNotFoundError:
        return {"ok": None, "detail": "fuser not available", "known": False}
    except Exception as exc:
        return {"ok": None, "detail": str(exc)[:80], "known": False}

    raw = (r.stdout + " " + r.stderr).strip()
    if not raw:
        return {
            "ok":     False,
            "detail": "port unclaimed — is DVSwitch running?",
            "known":  False,
        }

    procs = []
    for tok in raw.split():
        m = re.match(r'^(\d+)', tok)
        if not m:
            continue
        pid_s = m.group(1)
        comm_path = Path(f"/proc/{pid_s}/comm")
        try:
            proc_name = comm_path.read_text().strip()
        except Exception as e:
            log.debug("_ambe_layer3: %s", e)
            proc_name = "unknown"
        procs.append((pid_s, proc_name))

    if not procs:
        return {
            "ok":     False,
            "detail": f"fuser output unparseable: {raw[:60]}",
            "known":  False,
        }

    _KNOWN_DVS = frozenset((
        "analog_bridge", "analog-bridge",
        "mmdvm_bridge",  "mmdvm-bridge",
        "dvswitch",
    ))
    is_known = any(p[1].lower() in _KNOWN_DVS for p in procs)
    detail   = "  ·  ".join(f"{name} pid {pid}" for pid, name in procs)

    if not is_known:
        detail = f"unknown process — {detail}"

    return {"ok": True, "detail": detail, "known": is_known}

def _get_ambe_devices_impl() -> list:
    tty_map  = _usb_tty_map()
    watchdog = _read_ambe_watchdog()
    results  = []

    usb_root = Path("/sys/bus/usb/devices")
    if not usb_root.exists():
        return []

    for entry in os.scandir(usb_root):

        try:
            dev_path = Path(entry.path).resolve()
        except Exception as e:
            log.debug("_get_ambe_devices_impl: %s", e)
            continue

        vid_file = dev_path / "idVendor"
        pid_file = dev_path / "idProduct"
        if not vid_file.exists() or not pid_file.exists():
            continue

        try:
            vid = vid_file.read_text().strip().lower()
            pid = pid_file.read_text().strip().lower()
        except Exception as e:
            log.debug("_get_ambe_devices_impl: %s", e)
            continue

        try:
            if (dev_path / "bDeviceClass").read_text().strip() == "09":
                continue
        except Exception as e:
            log.debug("_get_ambe_devices_impl: %s", e)
            pass

        def _attr(name: str) -> str:
            try:
                return (dev_path / name).read_text().strip()
            except Exception as e:
                log.debug("_attr: %s", e)
                return ""

        manufacturer = _attr("manufacturer")
        product      = _attr("product")

        dev_nodes = tty_map.get(str(dev_path), [])
        if not dev_nodes:
            continue

        pair = (vid, pid)
        if pair in AMBE_DEVICES:
            label      = AMBE_DEVICES[pair]
            category   = "ambe"
            ambe_known = True
        elif vid in AMBE_FTDI_VIDS:
            label      = AMBE_FTDI_VIDS[vid]
            category   = "serial"
            ambe_known = False
        else:
            label      = product or f"{vid}:{pid}"
            category   = "serial"
            ambe_known = False

        udev_symlink = _udev_symlink_for_nodes(dev_nodes)
        source       = "watchdog" if watchdog is not None else "live"

        node = dev_nodes[0]

        if ambe_known:
            l1 = {"ok": True,  "detail": f"VID:PID match — {label}"}
        else:
            l1 = {"ok": True,  "detail": f"serial device detected — {label}"}

        l2 = _ambe_layer2(node)

        if l2["ok"]:
            l3 = _ambe_layer3(node)
        else:
            l3 = {"ok": None, "detail": "skipped — serial not accessible", "known": False}

        l4 = {"ok": None, "detail": "press Ping to test"}

        if watchdog:
            wd_layers = watchdog.get("layers", {})
            for lk, lv in (("l1", l1), ("l2", l2), ("l3", l3)):
                if lk in wd_layers:
                    lv.update(wd_layers[lk])

        results.append({
            "vid":          vid,
            "pid":          pid,
            "manufacturer": manufacturer,
            "product":      product,
            "dev_nodes":    dev_nodes,
            "udev_symlink": udev_symlink,
            "category":     category,
            "label":        label,
            "ambe_known":   ambe_known,
            "source":       source,
            "layers": {
                "l1": l1,
                "l2": l2,
                "l3": l3,
                "l4": l4,
            },
        })

    return results

def get_ambe_devices() -> list:
    try:
        return _get_ambe_devices_impl()
    except Exception as exc:
        _log(f"get_ambe_devices: error — {exc}", stderr=True)
        return []

_CMEDIA_VID = "0d8c"

def _parse_asound_cards() -> "list[dict]":
    results = []
    try:
        raw = Path("/proc/asound/cards").read_text()
    except Exception as e:
        log.debug("_parse_asound_cards: %s", e)
        return []

    header_re = re.compile(
        r'^\s*(\d+)\s+\[(\S+)\s*\]:\s+(\S+)\s+-\s+(.+)$'
    )
    for line in raw.splitlines():
        m = header_re.match(line)
        if m:
            results.append({
                "index":     int(m.group(1)),
                "short_id":  m.group(2).strip(),
                "driver":    m.group(3).strip(),
                "long_name": m.group(4).strip(),
            })
    return results

def _audio_usb_ids(card_index: int) -> "tuple[str, str]":
    sysfs = Path(f"/sys/class/sound/card{card_index}/device")
    if not sysfs.exists():
        return ("", "")
    try:
        resolved = sysfs.resolve()
        p = resolved
        for _ in range(6):
            p = p.parent
            vid_file = p / "idVendor"
            pid_file = p / "idProduct"
            if vid_file.exists() and pid_file.exists():
                vid = vid_file.read_text().strip().lower()
                pid = pid_file.read_text().strip().lower()
                return (vid, pid)
    except Exception as e:
        log.debug("_audio_usb_ids: %s", e)
        pass
    return ("", "")

def _audio_tty_nodes(card_index: int) -> "list[str]":
    sysfs = Path(f"/sys/class/sound/card{card_index}/device")
    if not sysfs.exists():
        return []
    try:
        resolved = sysfs.resolve()
        p = resolved
        usb_root = None
        for _ in range(6):
            p = p.parent
            if (p / "idVendor").exists():
                usb_root = str(p)
                break
        if not usb_root:
            return []
        return sorted(_usb_tty_map().get(usb_root, []))
    except Exception as e:
        log.debug("_audio_tty_nodes: %s", e)
        return []

def _audio_is_usb(card: dict, vid: str) -> bool:
    if vid:
        return True
    return "usb" in card.get("long_name", "").lower()

def _audio_check_free(card_index: int) -> "tuple[bool, str]":
    import glob as _glob
    pattern   = f"/dev/snd/pcmC{card_index}D*"
    pcm_nodes = _glob.glob(pattern)

    if not pcm_nodes:

        return (True, "no PCM nodes (card may be idle)")

    try:
        r = subprocess.run(
            ["fuser"] + pcm_nodes,
            capture_output=True, text=True, timeout=4,
        )
    except FileNotFoundError:
        return (True, "fuser not available — assuming free")
    except Exception as exc:
        return (True, f"fuser error — {str(exc)[:60]}")

    raw = (r.stdout + r.stderr).strip()
    if not raw:
        return (True, "no process holding PCM")

    holders = []
    for pid_s in raw.split():
        m = re.match(r'^-?(\d+)', pid_s)
        if not m:
            continue
        pid_s = m.group(1)
        try:
            name = Path(f"/proc/{pid_s}/comm").read_text().strip()
        except Exception as e:
            log.debug("_audio_check_free: %s", e)
            name = "unknown"
        holders.append(f"{name} pid {pid_s}")

    detail = "  ·  ".join(holders) if holders else raw[:60]
    return (False, f"HELD by {detail}")

def _audio_dvswitch_compat(card_index: int) -> "tuple[bool, str | None]":
    stream0 = Path(f"/proc/asound/card{card_index}/stream0")
    if not stream0.exists():
        return (False, "stream0 not found — card may not support audio streaming")

    try:
        text = stream0.read_text()
    except Exception as exc:
        return (False, f"cannot read stream0: {exc}")

    has_capture  = bool(re.search(r'^Capture:',  text, re.MULTILINE))
    has_playback = bool(re.search(r'^Playback:', text, re.MULTILINE))
    if not has_capture:
        return (False, "no capture (microphone) stream")
    if not has_playback:
        return (False, "no playback stream")

    capture_parts  = re.split(r'^Capture:',  text, maxsplit=1, flags=re.MULTILINE)
    capture_block  = capture_parts[1]  if len(capture_parts)  > 1 else ""
    playback_parts = re.split(r'^Playback:', text, maxsplit=1, flags=re.MULTILINE)
    playback_block = playback_parts[1] if len(playback_parts) > 1 else ""

    def _rates_ok(block: str) -> "tuple[bool, str]":
        rates_m = re.search(r'Rates:\s*(.+)', block)
        if not rates_m:
            return (False, "cannot parse sample rates")
        
        rates_list = [r.strip(",") for r in rates_m.group(1).split()]
        if "8000" not in rates_list:
            first_rate = rates_list[0] if rates_list else "unknown"
            return (False, f"8kHz not supported — min rate {first_rate}Hz")
        return (True, "")

    cap_ok, cap_msg = _rates_ok(capture_block)
    if not cap_ok:
        return (False, f"capture: {cap_msg}")
    play_ok, play_msg = _rates_ok(playback_block)
    if not play_ok:
        return (False, f"playback: {play_msg}")

    if "S16_LE" not in text:
        return (False, "S16_LE format not supported")

    if not re.search(r'Channels:\s*1', capture_block):
        return (False, "mono capture not supported")

    return (True, None)

def _audio_asl_compat(vid: str) -> "tuple[bool, str | None]":
    if vid == _CMEDIA_VID:
        return (True, None)
    if vid:
        return (False, f"not CM1xx (vid {vid}) — PTT/COS/CTCSS unavailable")
    return (False, "not CM1xx — PTT/COS/CTCSS unavailable")

def _get_audio_devices_impl() -> list:
    cards   = _parse_asound_cards()
    results = []

    for card in cards:
        idx = card["index"]
        vid, pid = _audio_usb_ids(idx)
        is_usb   = _audio_is_usb(card, vid)

        if not is_usb:
            continue

        alsa_sysfs  = Path(f"/sys/class/sound/card{idx}")
        alsa_exists = alsa_sysfs.exists()
        c1 = {
            "ok":     alsa_exists,
            "detail": "USB audio + ALSA card present" if alsa_exists
                      else "ALSA sysfs entry missing — possible driver issue",
        }

        free, free_detail = _audio_check_free(idx)
        c2 = {"ok": free, "detail": free_detail}

        dvswitch_ok, dvswitch_fail = _audio_dvswitch_compat(idx)

        asl_ok, asl_fail = _audio_asl_compat(vid)

        stream0_exists = Path(f"/proc/asound/card{idx}/stream0").exists()

        tty_nodes = _audio_tty_nodes(idx)

        results.append({
            "card_index":          idx,
            "card_id":             card["short_id"],
            "card_name":           card["long_name"],
            "vid":                 vid,
            "pid":                 pid,
            "is_usb":              is_usb,
            "tty_nodes":           tty_nodes,
            "checks": {
                "c1": c1,
                "c2": c2,
            },
            "dvswitch_ok":         dvswitch_ok,
            "dvswitch_fail_reason": dvswitch_fail,
            "asl_ok":              asl_ok,
            "asl_fail_reason":     asl_fail,
            "stream0_exists":      stream0_exists,
        })

    return results

def get_audio_devices() -> list:
    try:
        return _get_audio_devices_impl()
    except Exception as exc:
        _log(f"get_audio_devices: error — {exc}", stderr=True)
        return []

def get_lsusb() -> dict:
    if not shutil.which("lsusb"):
        return {"available": False, "flat": [], "tree": "",
                "error": "lsusb not found — install usbutils"}
    try:
        flat_raw = _run(["lsusb"], timeout=8)
        tree_raw = _run(["lsusb", "-t"], timeout=8)
        return {
            "available": True,
            "flat":      flat_raw.splitlines() if flat_raw else [],
            "tree":      tree_raw,
            "error":     None,
        }
    except Exception as exc:
        return {"available": True, "flat": [], "tree": "",
                "error": str(exc)[:120]}

def get_asl_find_sound() -> dict:
    if not shutil.which("asl-find-sound"):
        return {"available": True, "installed": False, "output": "",
                "error": "asl-find-sound not found — install asl3 or asl-apt-utils"}
    try:
        out, err = _run_with_stderr(["asl-find-sound"], timeout=15)
        combined = out if out else err
        return {
            "available": True,
            "installed": True,
            "output":    combined,
            "error":     None,
        }
    except Exception as exc:
        return {"available": True, "installed": True, "output": "",
                "error": str(exc)[:120]}

def get_alsa_cards() -> dict:
    if not shutil.which("aplay"):
        return {"available": False, "playback": "", "capture": "",
                "error": "aplay not found — install alsa-utils"}
    try:
        pb, _ = _run_with_stderr(["aplay",   "-l"], timeout=8)
        cap, _ = _run_with_stderr(["arecord", "-l"], timeout=8)
        return {
            "available": True,
            "playback":  pb,
            "capture":   cap,
            "error":     None,
        }
    except Exception as exc:
        return {"available": True, "playback": "", "capture": "",
                "error": str(exc)[:120]}

_UDEV_RULES_PATH = Path("/etc/udev/rules.d/99-ambe-sysmon.rules")

_UDEV_LINE_RE = re.compile(
    r'ATTRS\{idVendor\}=="([0-9a-f]{4})"'
    r'.*?ATTRS\{idProduct\}=="([0-9a-f]{4})"'
    r'.*?SYMLINK\+="([^"]+)"',
    re.IGNORECASE,
)

_UDEV_SYMLINK_RE = re.compile(r'^[A-Za-z0-9_\-]{1,32}$')

_UDEV_HEXID_RE   = re.compile(r'^[0-9a-f]{4}$', re.IGNORECASE)

def read_udev_ambe_rules() -> list:
    try:
        if not _UDEV_RULES_PATH.exists():
            return []
        rules = []
        for line in _UDEV_RULES_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = _UDEV_LINE_RE.search(line)
            if m:
                rules.append({
                    "vid":     m.group(1).lower(),
                    "pid":     m.group(2).lower(),
                    "symlink": m.group(3),
                })
        return rules
    except Exception as exc:
        _log(f"read_udev_ambe_rules: {exc}")
        return []

def _udev_rule_line(vid: str, pid: str, symlink: str) -> str:
    return (
        f'SUBSYSTEM=="tty", '
        f'ATTRS{{idVendor}}=="{vid}", '
        f'ATTRS{{idProduct}}=="{pid}", '
        f'SYMLINK+="{symlink}", '
        f'MODE="0660"'
    )

def _udev_reload() -> "tuple[bool, str]":
    msgs = []
    for cmd in (
        ["udevadm", "control", "--reload-rules"],
        ["udevadm", "trigger", "--subsystem-match=tty", "--action=add"],
    ):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
            if r.returncode != 0:
                msgs.append(f"{cmd[1]} failed: {(r.stderr or '').strip()[:60]}")
        except FileNotFoundError:
            msgs.append("udevadm not found — rule written, apply manually or reboot")
            break
        except Exception as exc:
            msgs.append(f"{cmd[1]} error: {str(exc)[:60]}")
    if msgs:
        _log(f"udev reload warnings: {'; '.join(msgs)}")
        return (False, "; ".join(msgs))
    return (True, "udev rules reloaded")

def write_udev_ambe_rule(
    existing: list,
    vid: str,
    pid: str,
    symlink: str,
) -> "tuple[bool, str]":
    vid     = vid.lower().strip()
    pid     = pid.lower().strip()
    symlink = symlink.strip()

    if not _UDEV_HEXID_RE.match(vid):
        return (False, f"invalid VID '{vid}' — must be 4 hex digits")
    if not _UDEV_HEXID_RE.match(pid):
        return (False, f"invalid PID '{pid}' — must be 4 hex digits")
    if not _UDEV_SYMLINK_RE.match(symlink):
        return (False,
                f"invalid symlink name '{symlink}' — "
                f"use A-Z 0-9 _ - only, max 32 chars")

    for rule in existing:
        if rule["symlink"] == symlink and not (
            rule["vid"] == vid and rule["pid"] == pid
        ):
            return (
                False,
                f"symlink '{symlink}' already assigned to "
                f"{rule['vid']}:{rule['pid']} — choose a different name",
            )

    new_rules = [r for r in existing
                 if not (r["vid"] == vid and r["pid"] == pid)]
    new_rules.append({"vid": vid, "pid": pid, "symlink": symlink})

    lines  = ["# Generated by ASL-DVS SYSMON — do not edit manually"]
    lines += [_udev_rule_line(r["vid"], r["pid"], r["symlink"])
              for r in new_rules]
    content = "\n".join(lines) + "\n"

    try:
        _UDEV_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(_UDEV_RULES_PATH, content)  
        _log(f"udev rule written: {vid}:{pid} → /dev/{symlink}")
    except Exception as exc:
        return (False, f"write failed: {exc}")

    reload_ok, reload_msg = _udev_reload()
    msg = f"rule saved ({vid}:{pid} → /dev/{symlink})"
    if not reload_ok:
        msg += f" — reload warning: {reload_msg}"
    return (True, msg)

def delete_udev_ambe_rule(
    existing: list,
    vid: str,
    pid: str,
) -> "tuple[bool, str]":
    vid = vid.lower().strip()
    pid = pid.lower().strip()

    if not _UDEV_HEXID_RE.match(vid):
        return (False, f"invalid VID '{vid}'")
    if not _UDEV_HEXID_RE.match(pid):
        return (False, f"invalid PID '{pid}'")

    new_rules = [r for r in existing
                 if not (r["vid"] == vid and r["pid"] == pid)]

    if len(new_rules) == len(existing):
        return (False, f"no rule found for {vid}:{pid}")

    try:
        if not new_rules:

            _UDEV_RULES_PATH.unlink(missing_ok=True)
            _log("udev rules file removed (no rules remain)")
        else:
            lines  = ["# Generated by ASL-DVS SYSMON — do not edit manually"]
            lines += [_udev_rule_line(r["vid"], r["pid"], r["symlink"])
                      for r in new_rules]
            content = "\n".join(lines) + "\n"
            _atomic_write(_UDEV_RULES_PATH, content)  
            _log(f"udev rule deleted: {vid}:{pid}")
    except Exception as exc:
        return (False, f"write failed: {exc}")

    reload_ok, reload_msg = _udev_reload()
    msg = f"rule deleted ({vid}:{pid})"
    if not reload_ok:
        msg += f" — reload warning: {reload_msg}"
    return (True, msg)

_TTY_BAUD_ALLOWLIST: "frozenset[int]" = frozenset({230400, 460800})

_TTY_DEV_RE = re.compile(r'^/dev/tty[A-Za-z0-9]+$')

def _set_latency_timer(dev_name: str) -> "tuple[bool, str]":
    timer_path = Path(f"/sys/bus/usb-serial/devices/{dev_name}/latency_timer")
    try:
        if not timer_path.exists():
            return (False, f"latency_timer not found at {timer_path} — FTDI low-latency not set")
        timer_path.write_text("1")
        return (True, f"latency_timer set to 1 for {dev_name}")
    except PermissionError:
        return (False, "permission denied writing latency_timer — not running as root?")
    except Exception as exc:
        return (False, f"latency_timer write failed: {str(exc)[:60]}")

def set_tty_baud(dev_node: str, baud: int) -> "tuple[bool, str]":

    dev_node = dev_node.strip()
    if not _TTY_DEV_RE.match(dev_node):
        return (False,
                f"invalid device node '{dev_node}' — "
                f"must match /dev/tty[A-Za-z0-9]+")

    try:
        baud = int(baud)
    except (TypeError, ValueError):
        return (False, f"baud must be an integer, got {baud!r}")
    if baud not in _TTY_BAUD_ALLOWLIST:
        allowed = ", ".join(str(b) for b in sorted(_TTY_BAUD_ALLOWLIST))
        return (False, f"baud {baud} not permitted — allowed: {allowed}")

    if not Path(dev_node).exists():
        return (False, f"device not found: {dev_node}")

    dev_name   = Path(dev_node).name
    lt_ok, lt_msg = _set_latency_timer(dev_name)
    if not lt_ok:
        _log(f"set_tty_baud: latency_timer warning — {lt_msg}")

    try:
        r = subprocess.run(
            ["stty", "-F", dev_node,
             str(baud), "raw", "cs8", "-cstopb", "-parenb"],
            capture_output=True, text=True, timeout=5,
        )
    except FileNotFoundError:
        return (False, "stty not found")
    except Exception as exc:
        return (False, f"stty error: {str(exc)[:80]}")

    if r.returncode != 0:
        stderr = (r.stderr or "").strip()
        if "Permission denied" in stderr:
            return (False, f"permission denied on {dev_node} — not running as root?")
        if "No such file" in stderr:
            return (False, f"device node missing: {dev_node}")
        return (False, f"stty failed: {stderr[:80] or 'unknown error'}")

    _log(f"set_tty_baud: {dev_node} @ {baud} baud")
    msg = (
        f"stty OK — {dev_node} set to {baud} baud  "
        f"(session-only: lost on reconnect/reboot — "
        f"point DVSwitch config to udev symlink for persistence)"
    )
    if not lt_ok:
        msg += f"  [latency_timer warning: {lt_msg}]"

    return (True, msg)

_DVSI_START       = 0x61

_DVSI_PRODID_REQ  = bytes([0x61, 0x00, 0x01, 0x00, 0x30])

_DVSI_HEADER_LEN  = 4

def _parse_dvsi_response(data: bytes) -> "str | None":
    if len(data) < _DVSI_HEADER_LEN + 1:
        return None
    if data[0] != _DVSI_START:
        return None
    pkt_len = (data[1] << 8) | data[2]
    if pkt_len < 1:
        return None
    
    payload = data[_DVSI_HEADER_LEN + 1 : _DVSI_HEADER_LEN + pkt_len]
    if not payload:
        return None
    product = payload.rstrip(b'\x00').decode('ascii', errors='replace').strip()
    return product if product else None

def _ping_attempt(dev_node: str, baud: int) -> dict:
    import select

    baud_const = _BAUD_TO_TERMIOS.get(baud)
    if baud_const is None:
        return {
            "ok": False, "responding": False,
            "product_id": None, "baud_used": baud,
            "error": f"termios constant unavailable for {baud} baud",
        }

    fd = -1
    try:
        import termios

        fd = os.open(dev_node, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)

        attrs        = termios.tcgetattr(fd)
        attrs[0]     = 0
        attrs[1]     = 0
        attrs[2]     = (termios.CS8 | termios.CLOCAL |
                        termios.CREAD)
        attrs[3]     = 0
        attrs[4]     = baud_const
        attrs[5]     = baud_const
        attrs[6][termios.VMIN]  = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIOFLUSH)

        os.write(fd, _DVSI_PRODID_REQ)

        ready, _, _ = select.select([fd], [], [], 2.0)
        if not ready:
            return {
                "ok": False, "responding": False,
                "product_id": None, "baud_used": baud,
                "error": (
                    f"no response at {baud} baud within 2s — "
                    f"check latency_timer or DVSwitch holding port"
                ),
            }

        data = os.read(fd, 64)
        product = _parse_dvsi_response(data)
        if product is None:
            return {
                "ok": False, "responding": False,
                "product_id": None, "baud_used": baud,
                "error": (
                    f"malformed response at {baud} baud "
                    f"(got {len(data)} bytes, start=0x{data[0]:02x})"
                    if data else "empty response"
                ),
            }

        _log(f"ping_ambe_chip: {dev_node} → {product} @ {baud} baud")
        return {
            "ok": True, "responding": True,
            "product_id": product, "baud_used": baud,
            "error": None,
        }

    except PermissionError:
        return {
            "ok": False, "responding": False,
            "product_id": None, "baud_used": baud,
            "error": f"permission denied on {dev_node} — not running as root?",
        }
    except OSError as exc:

        if exc.errno == 16:
            return {
                "ok": False, "responding": False,
                "product_id": None, "baud_used": baud,
                "error": f"device busy — DVSwitch may be holding {dev_node}",
            }
        return {
            "ok": False, "responding": False,
            "product_id": None, "baud_used": baud,
            "error": f"OS error opening {dev_node}: {exc}",
        }
    except Exception as exc:
        return {
            "ok": False, "responding": False,
            "product_id": None, "baud_used": baud,
            "error": f"ping error: {str(exc)[:80]}",
        }
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except Exception as e:
                log.debug("_ping_attempt: %s", e)
                pass

def _ambe_usb_bus_dev(dev_node: str) -> "tuple[str, str] | None":
    dev_name  = Path(dev_node).name
    tty_link  = Path(f"/sys/class/tty/{dev_name}/device")
    if not tty_link.exists():
        return None
    try:
        resolved = tty_link.resolve()
        p = resolved
        for _ in range(6):
            p = p.parent
            busnum_f = p / "busnum"
            devnum_f = p / "devnum"
            if busnum_f.exists() and devnum_f.exists():
                bus = int(busnum_f.read_text().strip())
                dev = int(devnum_f.read_text().strip())
                return (f"{bus:03d}", f"{dev:03d}")
    except Exception as e:
        log.debug("_ambe_usb_bus_dev: %s", e)
        pass
    return None

def reset_ambe_chip(dev_node: str) -> dict:
    import fcntl as _fcntl
    USBDEVFS_RESET = 0x5514

    bd = _ambe_usb_bus_dev(dev_node)
    if bd is None:
        return {
            "ok":          False,
            "message":     f"Cannot locate USB device for {dev_node} — sysfs walk failed",
            "re_detected": False,
            "holder":      None,
        }
    bus, dev_num = bd
    usb_path = f"/dev/bus/usb/{bus}/{dev_num}"
    if not Path(usb_path).exists():
        return {
            "ok":          False,
            "message":     f"USB path {usb_path} not found — check permissions",
            "re_detected": False,
            "holder":      None,
        }

    holder = None
    try:
        l2 = _ambe_layer2(dev_node)
        if not l2.get("ok"):
            holder = l2.get("detail", "unknown process")
    except Exception as e:
        log.debug("reset_ambe_chip: %s", e)
        pass

    try:
        with open(usb_path, "wb") as fd:
            _fcntl.ioctl(fd, USBDEVFS_RESET, 0)
    except PermissionError:
        return {
            "ok":          False,
            "message":     f"Permission denied on {usb_path} — sysmon must run as root",
            "re_detected": False,
            "holder":      holder,
        }
    except Exception as exc:
        return {
            "ok":          False,
            "message":     f"USB reset ioctl failed: {exc}",
            "re_detected": False,
            "holder":      holder,
        }

    time.sleep(1.5)

    re_detected = False
    try:
        re_detected = Path(f"/sys/class/tty/{Path(dev_node).name}").exists()
    except Exception as e:
        log.debug("reset_ambe_chip: %s", e)
        pass

    msg = (
        f"USB reset sent → {usb_path} — "
        + ("device re-enumerated" if re_detected else "device not yet visible, allow a moment")
    )
    if holder:
        msg += f" · note: {holder}"

    return {
        "ok":          True,
        "message":     msg,
        "re_detected": re_detected,
        "holder":      holder,
    }

def ping_ambe_chip(dev_node: str) -> dict:
    dev_node = dev_node.strip()

    if not _TTY_DEV_RE.match(dev_node):
        return {
            "ok": False, "responding": False, "product_id": None,
            "baud_used": None,
            "error": f"invalid device node '{dev_node}'",
        }

    if not Path(dev_node).exists():
        return {
            "ok": False, "responding": False, "product_id": None,
            "baud_used": None,
            "error": f"device not found: {dev_node}",
        }

    if not _BAUD_TO_TERMIOS:
        return {
            "ok": False, "responding": False, "product_id": None,
            "baud_used": None,
            "error": "termios module unavailable — ping requires Linux",
        }

    dev_name = Path(dev_node).name
    lt_ok, lt_msg = _set_latency_timer(dev_name)
    if not lt_ok:
        _log(f"ping_ambe_chip: latency_timer warning — {lt_msg}")

    for baud in (460800, 230400):
        result = _ping_attempt(dev_node, baud)
        if result["responding"]:
            return result
        err = result.get("error", "")
        if "busy" in err or "permission denied" in err:
            return result

    return {
        "ok":         False,
        "responding": False,
        "product_id": None,
        "baud_used":  460800,
        "error": (
            "no response at 460800 or 230400 baud — "
            "check latency_timer or stop DVSwitch before pinging"
        ),
    }

def _dvs_active_units() -> "list[str]":

    _DVS_PATTERNS = (
        "analog_bridge", "analog-bridge",
        "mmdvm_bridge",  "mmdvm-bridge",
        "md380",
        "dvswitch-mode",
        "stfu",
        "ysf-gateway", "ysf_gateway",
        "p25gateway",  "p25-gateway",
        "nxdngateway", "nxdn-gateway",
        "dmrgateway",  "dmr-gateway",
        "ircddbgateway",
        "dstarrepeater",
        "m17gateway",  "m17-gateway",
        "quantar",
    )
    try:
        raw = subprocess.run(
            ["systemctl", "list-units", "--type=service",
             "--state=active", "--no-pager", "--no-legend"],
            capture_output=True, text=True, timeout=8,
        ).stdout
    except Exception as e:
        log.debug("_dvs_active_units: %s", e)
        return []

    active = []
    for line in raw.splitlines():
        parts = line.split()
        if not parts:
            continue
        unit = parts[0].strip()
        if not _validate_unit(unit):
            continue
        name_lower = unit.lower()
        if any(pat in name_lower for pat in _DVS_PATTERNS):
            active.append(unit)
    return active

_HEALTH_UNITS = ("nodecontrol", "asl_dvs_dashboard", "sysmon", "wifimon", "instmon", "44helper",
                 "asterisk", "analog_bridge", "mmdvm_bridge", "md380-emu", "usrp2m17", "allmon3")
_HEALTH_CACHE_SECS = 30.0
_health_lock = threading.Lock()
_health_cache: dict = {"at": None, "data": None}
_HC_KILLED_RE = re.compile(r"Killed process (\d+) \(([^)]+)\)")
_HC_DISK_USAGE_RE = re.compile(r"take up ([\d.]+)\s*([KMGT]?)B?", re.I)
_HC_UNIT_MULT = {"": 1 / (1024 * 1024), "K": 1 / 1024, "M": 1.0, "G": 1024.0, "T": 1024.0 * 1024}

def _hc(cid: str, title: str, status: str, headline: str, rows=None, note: str = "") -> dict:
    return {"id": cid, "title": title, "status": status, "headline": headline,
            "rows": rows or [], "note": note}

def _hc_cmd(cmd: list, timeout: int = 6) -> "tuple[str, str]":
    if not shutil.which(cmd[0]):
        return "", f"{cmd[0]} not found"
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "", f"{cmd[0]} timed out"
    except OSError as exc:
        return "", str(exc)
    err = (r.stderr.strip().splitlines() or [""])[0]
    return r.stdout, ("" if r.returncode == 0 else (err or f"{cmd[0]} exited {r.returncode}"))

def _hc_meminfo() -> dict:
    out = {}
    try:
        for ln in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = ln.partition(":")
            parts = v.split()
            if parts and parts[0].isdigit():
                out[k.strip()] = int(parts[0]) // 1024
    except OSError:
        pass
    return out

def _hc_clock() -> dict:
    out, prob = _hc_cmd(["timedatectl", "show", "-p", "NTPSynchronized", "-p", "NTP", "-p", "Timezone"])
    if prob:
        return _hc("clock", "Clock", "unknown", f"Can't read the clock state ({prob})")
    kv = dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln)
    synced, ntp = kv.get("NTPSynchronized") == "yes", kv.get("NTP") == "yes"
    rows = [["Now", datetime.now().strftime("%Y-%m-%d %H:%M:%S")], ["Time zone", kv.get("Timezone", "?")],
            ["Time sync", "on" if ntp else "off"], ["Synced", "yes" if synced else "no"]]
    if synced:
        return _hc("clock", "Clock", "pass", "Clock is in sync", rows)
    note = ("The Pi Zero 2 W has no clock battery, so after a power cut its time is wrong until it syncs. "
            "A wrong clock breaks HTTPS (GitHub updates), AllStarLink registration and some digital-mode logins. "
            + ("Turn sync on: sudo timedatectl set-ntp true" if not ntp
               else "Sync is on but hasn't worked: check the internet and that UDP port 123 isn't blocked."))
    return _hc("clock", "Clock", "warn", "Clock is NOT in sync" if ntp else "Time sync is turned off", rows, note)

def _hc_oom() -> dict:
    kills = None
    try:
        for ln in Path("/proc/vmstat").read_text().splitlines():
            if ln.startswith("oom_kill "):
                kills = int(ln.split()[1])
    except (OSError, ValueError):
        pass
    if kills is None:
        return _hc("oom", "Out-of-memory kills", "unknown", "The kernel doesn't report OOM kills (/proc/vmstat)")
    rows = [["Since boot", str(kills)]]
    if kills == 0:
        return _hc("oom", "Out-of-memory kills", "pass", "None since boot", rows)
    out, _prob = _hc_cmd(["journalctl", "-k", "-b", "--no-pager", "-o", "short-iso", "-g", "Killed process", "-n", "5"], 8)
    for ln in out.splitlines():
        m = _HC_KILLED_RE.search(ln)
        if m:
            rows.append([ln.split(" ", 1)[0][:19], f"{m.group(2)} (pid {m.group(1)})"])
    return _hc("oom", "Out-of-memory kills", "fail",
               f"The kernel killed {kills} process{'es' if kills != 1 else ''} for lack of memory since boot", rows,
               "Memory ran out. Something was stopped to free it, and may have restarted since. "
               "Check Memory per service below for the biggest users.")

def _hc_memory() -> dict:
    mi = _hc_meminfo()
    total, avail = mi.get("MemTotal"), mi.get("MemAvailable")
    if not total or avail is None:
        return _hc("memory", "Memory", "unknown", "Can't read /proc/meminfo")
    st, sf = mi.get("SwapTotal", 0), mi.get("SwapFree", 0)
    used_swap = st - sf
    zram = False
    try:
        zram = any(ln.startswith("/dev/zram") for ln in Path("/proc/swaps").read_text().splitlines())
    except OSError:
        pass
    rows = [["Total", f"{total} MB"], ["Available", f"{avail} MB ({avail * 100 // total}%)"],
            ["Swap", f"{used_swap} of {st} MB used" + (" (zram)" if zram else "") if st else "none"]]
    status, notes = "pass", []
    if avail < 32:
        status = "fail"
        notes.append("Less than 32 MB is free: the kernel may start killing processes.")
    elif avail < 64:
        status = "warn"
        notes.append("Less than 64 MB is free.")
    if st and used_swap * 100 >= st * 75:
        status = "fail" if status == "fail" else "warn"
        notes.append("Swap is over 75% used: the Pi will be slow, and an SD card wears faster with swap on it.")
    head = f"{avail} MB of {total} MB available"
    return _hc("memory", "Memory", status, head, rows, " ".join(notes))

def _hc_dir_mb(path: str, budget: float = 3.0) -> "float | None":
    total, deadline = 0, time.monotonic() + budget
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
        if time.monotonic() > deadline:
            return None
    return total / (1024 * 1024)

def _hc_disk() -> dict:
    rows, status, notes = [], "pass", []
    try:
        vs = os.statvfs("/")
        size = vs.f_blocks * vs.f_frsize
        free = vs.f_bavail * vs.f_frsize
        pct = free * 100 / size if size else 0
        rows.append(["Root free", f"{free // (1024 * 1024)} MB of {size // (1024 * 1024)} MB ({pct:.0f}%)"])
        if pct < 5:
            status = "fail"
            notes.append("The root file system is almost full: logs and updates will start failing.")
        elif pct < 10:
            status = "warn"
            notes.append("Less than 10% of the root file system is free.")
    except OSError as exc:
        rows.append(["Root free", f"unknown ({exc})"])
        status = "unknown"
    out, prob = _hc_cmd(["journalctl", "--disk-usage"])
    m = _HC_DISK_USAGE_RE.search(out or "")
    if m:
        jmb = float(m.group(1)) * _HC_UNIT_MULT.get(m.group(2).upper(), 1.0)
        rows.append(["Journal", f"{jmb:.0f} MB"])
        if jmb > 200:
            status = "fail" if status == "fail" else "warn"
            notes.append("The journal is over 200 MB. Cap it with SystemMaxUse= in /etc/systemd/journald.conf "
                         "(for example 50M), then: sudo systemctl restart systemd-journald")
    else:
        rows.append(["Journal", f"unknown ({prob or 'no size in the output'})"])
    vlog = _hc_dir_mb("/var/log")
    rows.append(["/var/log", f"{vlog:.0f} MB" if vlog is not None else "too many files to count quickly"])
    if vlog is not None and vlog > 300:
        status = "fail" if status == "fail" else "warn"
        notes.append("/var/log is over 300 MB.")
    head = rows[0][1] if rows else "unknown"
    return _hc("disk", "Disk and logs", status, f"Root: {head}", rows, " ".join(notes))

def _hc_services() -> dict:
    rows, warn = [], []
    for unit in _HEALTH_UNITS:
        out, prob = _hc_cmd(["systemctl", "show", f"{unit}.service", "-p", "LoadState", "-p", "ActiveState",
                             "-p", "MemoryCurrent", "-p", "NRestarts"], 5)
        if prob:
            continue
        kv = dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln)
        if kv.get("LoadState") != "loaded":
            continue
        mem = kv.get("MemoryCurrent", "")
        mem_txt = f"{int(mem) // (1024 * 1024)} MB" if mem.isdigit() else "—"
        try:
            restarts = int(kv.get("NRestarts", "0") or 0)
        except ValueError:
            restarts = 0
        if restarts >= 3:
            warn.append(unit)
        rows.append([unit, f"{kv.get('ActiveState', '?')} · {mem_txt}" + (f" · restarted {restarts}x" if restarts else "")])
    if not rows:
        return _hc("services", "Memory per service", "unknown", "systemctl gave no service data")
    if warn:
        return _hc("services", "Memory per service", "warn", f"Restarted 3 or more times: {', '.join(warn)}", rows,
                   "systemd has restarted these since they were last started by hand or at boot. Check their logs on the Journal tab.")
    return _hc("services", "Memory per service", "pass", f"{len(rows)} services", rows)

_HEALTH_CHECKS = (_hc_clock, _hc_oom, _hc_memory, _hc_disk, _hc_services)

def get_node_health(max_age: float = _HEALTH_CACHE_SECS) -> list:
    with _health_lock:
        at = _health_cache["at"]
        if at is not None and time.monotonic() - at < max_age and _health_cache["data"] is not None:
            return _health_cache["data"]
    data = []
    for fn in _HEALTH_CHECKS:
        try:
            data.append(fn())
        except Exception as exc:
            log.debug("health: %s failed: %s", fn.__name__, exc)
            data.append(_hc(fn.__name__[4:], fn.__name__[4:].title(), "unknown", f"Check failed: {exc}"))
    with _health_lock:
        _health_cache["at"], _health_cache["data"] = time.monotonic(), data
    return data

def _route_health(h: Handler) -> None:
    h.send_json({"ok": True, "checks": get_node_health()})

def _route_hardware_get(h: Handler) -> None:
    ambe  = get_ambe_devices()
    audio = get_audio_devices()
    rules = read_udev_ambe_rules()

    rules_map = {(r["vid"], r["pid"]): r for r in rules}
    for dev in ambe:
        dev["udev_rule"] = rules_map.get((dev["vid"], dev["pid"]))

    h.send_json({
        "ok":          True,
        "ambe":        ambe,
        "audio":       audio,
        "udev_rules":  rules,
        "ambe_count":  len(ambe),
        "audio_count": len(audio),

        "power": {
            "throttle":    get_throttle_state(),
            "core_volts":  get_pi_voltage(),
            "cpu_temp":    get_cpu_temp(),
        },
        "video": get_video_state(),
    })

def _route_hardware_diag(h: Handler) -> None:
    h.send_json({
        "ok":            True,
        "lsusb":         get_lsusb(),
        "asl_find_sound": get_asl_find_sound(),
        "alsa":          get_alsa_cards(),
    })

def _hw_set_udev(h: Handler, data: dict) -> None:
    vid     = str(data.get("vid",     "")).strip().lower()
    pid     = str(data.get("pid",     "")).strip().lower()
    symlink = str(data.get("symlink", "")).strip()

    if not _UDEV_HEXID_RE.match(vid):
        h.send_json({"ok": False,
                     "message": f"invalid vid '{vid}' — must be 4 hex digits"}, 400)
        return
    if not _UDEV_HEXID_RE.match(pid):
        h.send_json({"ok": False,
                     "message": f"invalid pid '{pid}' — must be 4 hex digits"}, 400)
        return
    if not _UDEV_SYMLINK_RE.match(symlink):
        h.send_json({"ok": False,
                     "message": (
                         f"invalid symlink name '{symlink}' — "
                         f"use A-Z 0-9 _ - only, max 32 chars")}, 400)
        return

    existing = read_udev_ambe_rules()
    ok, msg  = write_udev_ambe_rule(existing, vid, pid, symlink)
    _log(msg, stderr=not ok)
    h.send_json({"ok": ok, "message": msg}, 200 if ok else 500)

def _hw_del_udev(h: Handler, data: dict) -> None:
    vid = str(data.get("vid", "")).strip().lower()
    pid = str(data.get("pid", "")).strip().lower()

    if not _UDEV_HEXID_RE.match(vid):
        h.send_json({"ok": False,
                     "message": f"invalid vid '{vid}' — must be 4 hex digits"}, 400)
        return
    if not _UDEV_HEXID_RE.match(pid):
        h.send_json({"ok": False,
                     "message": f"invalid pid '{pid}' — must be 4 hex digits"}, 400)
        return

    existing = read_udev_ambe_rules()
    ok, msg  = delete_udev_ambe_rule(existing, vid, pid)
    _log(msg, stderr=not ok)
    h.send_json({"ok": ok, "message": msg}, 200 if ok else 500)

def _hw_set_tty(h: Handler, data: dict) -> None:
    dev  = str(data.get("dev",  "")).strip()
    baud = data.get("baud", 0)

    if not _TTY_DEV_RE.match(dev):
        h.send_json({"ok": False,
                     "message": (
                         f"invalid device node '{dev}' — "
                         f"must match /dev/tty[A-Za-z0-9]+")}, 400)
        return

    try:
        baud = int(baud)
    except (TypeError, ValueError):
        h.send_json({"ok": False,
                     "message": f"baud must be an integer, got {baud!r}"}, 400)
        return

    if baud not in _TTY_BAUD_ALLOWLIST:
        allowed = ", ".join(str(b) for b in sorted(_TTY_BAUD_ALLOWLIST))
        h.send_json({"ok": False,
                     "message": f"baud {baud} not permitted — allowed: {allowed}"}, 400)
        return

    ok, msg = set_tty_baud(dev, baud)
    _log(msg, stderr=not ok)
    h.send_json({"ok": ok, "message": msg}, 200 if ok else 500)

def _hw_ping(h: Handler, data: dict) -> None:
    dev = str(data.get("dev", "")).strip()

    if not _TTY_DEV_RE.match(dev):
        h.send_json({"ok": False,
                     "message": (
                         f"invalid device node '{dev}' — "
                         f"must match /dev/tty[A-Za-z0-9]+")}, 400)
        return

    result = ping_ambe_chip(dev)
    _log(
        f"ping {dev}: {'OK — ' + str(result.get('product_id')) if result['ok'] else result.get('error','')}",
        stderr=not result["ok"],
    )
    h.send_json({
        "ok":         result["ok"],
        "message":    (
            f"AMBE chip responding — {result['product_id']}"
            if result["ok"]
            else result.get("error", "ping failed")
        ),
        "responding":  result["responding"],
        "product_id":  result["product_id"],
        "baud_used":   result["baud_used"],
        "error":       result["error"],
    }, 200 if result["ok"] else 500)

def _hw_reset_ambe(h: Handler, data: dict) -> None:
    dev = str(data.get("dev", "")).strip()

    if not _TTY_DEV_RE.match(dev):
        h.send_json({"ok": False,
                     "message": (
                         f"invalid device node '{dev}' — "
                         f"must match /dev/tty[A-Za-z0-9]+")}, 400)
        return

    units = _dvs_active_units()

    stop_results = []
    for u in units:
        if not _validate_unit(u):
            continue
        r = subprocess.run(["systemctl", "stop", u],
                           capture_output=True, text=True, timeout=15)
        ok_u = r.returncode == 0
        stop_results.append({"unit": u, "ok": ok_u})
        _log(f"reset_ambe: stop {u}: {'OK' if ok_u else r.stderr.strip()}", stderr=not ok_u)

    result = reset_ambe_chip(dev)
    _log(
        f"reset_ambe {dev}: {'OK — re_detected=' + str(result['re_detected']) if result['ok'] else result.get('message', 'failed')}",
        stderr=not result["ok"],
    )

    _PHASE_A = ("analog_bridge", "analog-bridge",
                "mmdvm_bridge",  "mmdvm-bridge",
                "md380")
    phase_a = [u for u in units if any(p in u.lower() for p in _PHASE_A)]
    phase_b = [u for u in units if u not in phase_a]

    restart_results = []

    for u in phase_a:
        if not _validate_unit(u):
            continue
        r = subprocess.run(["systemctl", "start", u],
                           capture_output=True, text=True, timeout=15)
        ok_u = r.returncode == 0
        restart_results.append({"unit": u, "ok": ok_u, "phase": "A"})
        _log(f"reset_ambe: start {u} (phase A): {'OK' if ok_u else r.stderr.strip()}", stderr=not ok_u)

    if phase_a and phase_b:
        time.sleep(3)

    for u in phase_b:
        if not _validate_unit(u):
            continue
        r = subprocess.run(["systemctl", "start", u],
                           capture_output=True, text=True, timeout=15)
        ok_u = r.returncode == 0
        restart_results.append({"unit": u, "ok": ok_u, "phase": "B"})
        _log(f"reset_ambe: start {u} (phase B): {'OK' if ok_u else r.stderr.strip()}", stderr=not ok_u)

    stopped  = len(stop_results)
    restarted = sum(r["ok"] for r in restart_results)
    svc_summary = (f"{stopped} service(s) stopped, {restarted}/{stopped} restarted"
                   if stopped else "no pinned services")

    h.send_json({
        "ok":            result["ok"],
        "message":       result["message"],
        "re_detected":   result["re_detected"],
        "holder":        result["holder"],
        "svc_summary":   svc_summary,
        "stop_results":  stop_results,
        "restart_results": restart_results,
    }, 200 if result["ok"] else 500)

BOOT_CONFIG      = Path("/boot/firmware/config.txt")
_BOOTCFG_BACKUP  = "config.txt.asl_dvs.bak"
_VIDEO_OFF_TAG   = "#ASL-DVS-VIDEO-OFF# "
_GPUMEM_BEGIN    = "#ASL-DVS-GPUMEM-BEGIN"
_GPUMEM_END      = "#ASL-DVS-GPUMEM-END"
_GPUMEM_LOW_MB   = 16
_VC4_OVERLAY_RE  = re.compile(r'^\s*dtoverlay\s*=\s*vc4-f?kms-v3d\b')
_GPUMEM_LINE_RE  = re.compile(r'^\s*gpu_mem\s*=\s*(\d+)')
_HW_REF_RE       = re.compile(r'\b(?:plug)?hw:\s*\d+|^\s*card\s+\d+\b|\bcard\s*=\s*\d+\b', re.I)
_HW_REF_GLOBS    = ("/etc/asterisk/*.conf", "/opt/Analog_Bridge/*.ini",
                    "/opt/MMDVM_Bridge/*.ini", "/etc/asound.conf", "/root/.asoundrc")

def _bootcfg_parse(text: str) -> dict:
    lines = text.splitlines()
    active = [ln for ln in lines if _VC4_OVERLAY_RE.match(ln)]
    tagged = [ln for ln in lines if ln.startswith(_VIDEO_OFF_TAG)]
    in_block = False
    gpu_low = False
    other_gpu = None
    for ln in lines:
        s = ln.strip()
        if s == _GPUMEM_BEGIN:
            in_block = gpu_low = True
            continue
        if s == _GPUMEM_END:
            in_block = False
            continue
        if not in_block:
            m = _GPUMEM_LINE_RE.match(ln)
            if m:
                other_gpu = int(m.group(1))
    return {
        "video_off":       bool(tagged) and not active,
        "video_partial":   bool(tagged) and bool(active),
        "video_lines":     len(active) + len(tagged),
        "gpumem_low":      gpu_low,
        "gpumem_other":    other_gpu,
    }

def _bootcfg_set_video(text: str, off: bool) -> str:
    out = []
    for ln in text.splitlines(keepends=True):
        if off and _VC4_OVERLAY_RE.match(ln):
            out.append(_VIDEO_OFF_TAG + ln)
        elif not off and ln.startswith(_VIDEO_OFF_TAG):
            out.append(ln[len(_VIDEO_OFF_TAG):])
        else:
            out.append(ln)
    return "".join(out)

def _bootcfg_set_gpumem(text: str, low: bool) -> str:
    out = []
    skip = False
    for ln in text.splitlines(keepends=True):
        s = ln.strip()
        if s == _GPUMEM_BEGIN:
            skip = True
            continue
        if skip:
            if s == _GPUMEM_END:
                skip = False
            continue
        out.append(ln)
    res = "".join(out)
    if low:
        if res and not res.endswith("\n"):
            res += "\n"
        res += (f"{_GPUMEM_BEGIN}\n[all]\ngpu_mem={_GPUMEM_LOW_MB}\n{_GPUMEM_END}\n")
    return res

def _bootcfg_write(new_text: str) -> None:
    d = BOOT_CONFIG.parent
    shutil.copy2(BOOT_CONFIG, d / _BOOTCFG_BACKUP)
    tmp = d / (BOOT_CONFIG.name + ".asl_dvs.tmp")
    with open(tmp, "w") as fh:
        fh.write(new_text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, BOOT_CONFIG)
    try:
        fd = os.open(str(d), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass
    os.sync()

_BOOT_RESTORE_FILE    = CONFIG_FILE.parent / "boot_restore.json"
_BOOT_RESTORE_MAX_AGE = 1800

def _bootcfg_save_for_update() -> bool:
    try:
        st = _bootcfg_parse(BOOT_CONFIG.read_text())
    except OSError:
        return False
    video = bool(st["video_off"] or st["video_partial"])
    gpu = bool(st["gpumem_low"])
    if not (video or gpu):
        return False
    try:
        _BOOT_RESTORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_BOOT_RESTORE_FILE, "w") as fh:
            json.dump({"saved_at": time.time(), "video_off": video, "gpumem_low": gpu}, fh)
        os.chmod(_BOOT_RESTORE_FILE, 0o600)
    except OSError:
        return False
    return True

def _bootcfg_saved_state(service_present: bool):
    now = time.time()
    try:
        with open(_BOOT_RESTORE_FILE) as fh:
            d = json.load(fh)
        if now - float(d.get("saved_at", 0)) > _BOOT_RESTORE_MAX_AGE:
            return None
        return bool(d.get("video_off")), bool(d.get("gpumem_low"))
    except (OSError, ValueError, TypeError):
        pass
    if service_present:
        return None
    bak = BOOT_CONFIG.parent / _BOOTCFG_BACKUP
    try:
        if now - bak.stat().st_ctime > _BOOT_RESTORE_MAX_AGE:
            return None
        st = _bootcfg_parse(bak.read_text())
    except OSError:
        return None
    return bool(st["video_off"] or st["video_partial"]), bool(st["gpumem_low"])

def _bootcfg_reapply_saved(service_present: bool) -> list:
    saved = _bootcfg_saved_state(service_present)
    try:
        _BOOT_RESTORE_FILE.unlink()
    except OSError:
        pass
    if not saved or not (saved[0] or saved[1]):
        return []
    try:
        text = BOOT_CONFIG.read_text()
    except OSError:
        return []
    new = text
    done = []
    if saved[0]:
        new = _bootcfg_set_video(new, True)
        done.append("HDMI/video driver off")
    if saved[1]:
        new = _bootcfg_set_gpumem(new, True)
        done.append("low GPU memory")
    if new == text:
        return []
    try:
        _bootcfg_write(new)
    except OSError:
        return []
    return done

def _bootcfg_restore_all() -> bool:
    try:
        text = BOOT_CONFIG.read_text()
    except OSError:
        return False
    new = _bootcfg_set_gpumem(_bootcfg_set_video(text, False), False)
    if new == text:
        return False
    _bootcfg_write(new)
    return True

def _video_live_state() -> dict:
    try:
        mods = Path("/proc/modules").read_text()
    except OSError:
        mods = ""
    vc4 = any(ln.split(" ", 1)[0] == "vc4" for ln in mods.splitlines())
    hdmi = []
    for st in sorted(Path("/sys/class/drm").glob("card*-HDMI-*/status")):
        try:
            hdmi.append({"name": st.parent.name.split("-", 1)[1],
                         "status": st.read_text().strip()})
        except OSError:
            pass
    cma_kb = None
    try:
        for ln in Path("/proc/meminfo").read_text().splitlines():
            if ln.startswith("CmaTotal:"):
                cma_kb = int(ln.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    gpu_mb = None
    m = re.search(r'gpu=(\d+)M', _run(["vcgencmd", "get_mem", "gpu"], timeout=3))
    if m:
        gpu_mb = int(m.group(1))
    hdmi_snd = []
    try:
        for ln in Path("/proc/asound/cards").read_text().splitlines():
            mm = re.match(r'\s*(\d+)\s+\[([^\]]+)\]\s*:\s*(.*)', ln)
            if mm and ("hdmi" in mm.group(2).lower() or "hdmi" in mm.group(3).lower()):
                hdmi_snd.append(f"card {mm.group(1)}: {mm.group(2).strip()}")
    except OSError:
        pass
    return {"vc4_loaded": vc4, "hdmi": hdmi, "cma_mb": (cma_kb // 1024) if cma_kb is not None else None,
            "gpu_mb": gpu_mb, "hdmi_sound": hdmi_snd}

def _video_hw_refs(limit: int = 12) -> list:
    refs = []
    for pat in _HW_REF_GLOBS:
        for fn in sorted(glob.glob(pat)):
            try:
                with open(fn, errors="replace") as fh:
                    for n, ln in enumerate(fh, 1):
                        body = ln.split(";", 1)[0] if fn.endswith(".conf") and "asterisk" in fn else ln
                        if body.lstrip().startswith("#"):
                            continue
                        if _HW_REF_RE.search(body):
                            refs.append(f"{fn}:{n}: {ln.strip()[:120]}")
                            if len(refs) >= limit:
                                return refs
            except OSError:
                continue
    return refs

def get_video_state() -> dict:
    try:
        text = BOOT_CONFIG.read_text()
    except OSError:
        return {"available": False, "config": str(BOOT_CONFIG),
                "message": f"{BOOT_CONFIG} not found (Bookworm or Trixie only)"}
    cfg  = _bootcfg_parse(text)
    live = _video_live_state()
    video_pending = cfg["video_lines"] > 0 and (cfg["video_off"] == live["vc4_loaded"])
    gpu_pending = False
    if live["gpu_mb"] is not None:
        if cfg["gpumem_low"]:
            gpu_pending = live["gpu_mb"] != _GPUMEM_LOW_MB
        else:
            gpu_pending = (live["gpu_mb"] == _GPUMEM_LOW_MB
                           and cfg["gpumem_other"] != _GPUMEM_LOW_MB)
    return {
        "available":      True,
        "config":         str(BOOT_CONFIG),
        "video_off":      cfg["video_off"],
        "video_partial":  cfg["video_partial"],
        "video_lines":    cfg["video_lines"],
        "gpumem_low":     cfg["gpumem_low"],
        "gpumem_other":   cfg["gpumem_other"],
        "gpumem_low_mb":  _GPUMEM_LOW_MB,
        "video_pending":  video_pending,
        "gpumem_pending": gpu_pending,
        "backup":         str(BOOT_CONFIG.parent / _BOOTCFG_BACKUP),
        "live":           live,
        "hw_refs":        _video_hw_refs() if (not cfg["video_off"] and live["hdmi_sound"]) else [],
    }

def _hw_boot_opt(h: Handler, data: dict) -> None:
    opt = str(data.get("opt", "")).strip()
    on  = bool(data.get("on"))
    if opt not in ("video", "gpumem"):
        h.send_json({"ok": False, "message": f"unknown option '{opt}'"}, 400); return
    try:
        text = BOOT_CONFIG.read_text()
    except OSError as e:
        h.send_json({"ok": False, "message": f"cannot read {BOOT_CONFIG}: {e}"}); return
    cfg = _bootcfg_parse(text)
    if opt == "video":
        if on and cfg["video_lines"] == 0:
            h.send_json({"ok": False, "message":
                         "No dtoverlay=vc4-kms-v3d line in config.txt; the video driver is not loaded from there"})
            return
        new = _bootcfg_set_video(text, on)
        what = "HDMI and video driver " + ("disabled" if on else "restored")
    else:
        new = _bootcfg_set_gpumem(text, on)
        what = f"GPU memory {'set to ' + str(_GPUMEM_LOW_MB) + ' MB' if on else 'restored to the default'}"
    if new == text:
        h.send_json({"ok": True, "message": f"No change needed ({what} already)",
                     "video": get_video_state()}); return
    try:
        _bootcfg_write(new)
    except OSError as e:
        h.send_json({"ok": False, "message": f"write failed: {e}"}); return
    _log(f"config.txt: {what}", stderr=True)
    h.send_json({"ok": True, "message": f"{what} in config.txt. Reboot to apply.",
                 "video": get_video_state()})

_HARDWARE_ACTIONS = {
    "boot_opt":   _hw_boot_opt,
    "set_udev":   _hw_set_udev,
    "del_udev":   _hw_del_udev,
    "set_tty":    _hw_set_tty,
    "ping":       _hw_ping,
    "reset_ambe": _hw_reset_ambe,
}

def _route_hardware_post(h: Handler, data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "root required"}); return

    action = str(data.get("action", "")).strip()
    fn = _HARDWARE_ACTIONS.get(action)
    if fn is None:
        h.send_json({"ok": False,
                     "message": f"unknown action '{action}'"}, 400)
        return
    fn(h, data)

def _dvsm_node_ip() -> str:
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception as e:
        log.debug("_dvsm_node_ip: %s", e)
        try:
            return _socket.gethostbyname(_socket.gethostname())
        except Exception as e:
            log.debug("_dvsm_node_ip: %s", e)
            return "unknown"

def _dvsm_wan_ip() -> str:
    import urllib.request as _urllib
    for url in ("https://api.ipify.org",
                "https://checkip.amazonaws.com"):
        try:
            with _urllib.urlopen(url, timeout=2) as resp:
                ip = resp.read().decode().strip()

                if ip and len(ip) <= 45 and all(c in "0123456789.:abcdefABCDEF" for c in ip):
                    return ip
        except Exception as e:
            log.debug("_dvsm_wan_ip: %s", e)
            continue
    return ""

def _dvsm_resolve_shared(iax: dict, rpt: dict) -> dict:

    _cfg_cs  = _cfg.get("identity", "callsign", fallback="").strip().upper()
    callsign = (rpt.get("callsign", "")
                or iax.get("iaxrpt_callerid", "")
                or _cfg_cs
                or "—")
    bindport = iax.get("bindport", "4569")

    pub_nodes = rpt.get("public_nodes", [])
    all_nodes = rpt.get("nodes", [])
    nodes     = pub_nodes if pub_nodes else all_nodes
    node_id   = nodes[0]["id"] if nodes else "—"

    registers = iax.get("registers", [])
    pub_registers = [r for r in registers if int(r.get("node","0") or "0") > 1999]

    use_registers = pub_registers if pub_registers else registers

    reg_node  = use_registers[0]["node"]     if use_registers else node_id
    reg_pass  = use_registers[0]["password"] if use_registers else ""
    reg_host  = use_registers[0]["host"]     if use_registers else ""
    reg_source = use_registers[0].get("source", "iax.conf") if use_registers else ""
    node_mode_ok = any(
        r["host"].lower() in ("register.allstarlink.org", "allstarlink.org")
        for r in use_registers
    )

    _cands = iax.get("iaxrpt_candidates", [])
    _sel   = next((c for c in _cands if c["name"].lower() == "iaxrpt"), None)
    if _sel is None and callsign and callsign != "—":
        _sel = next((c for c in _cands if c["name"].lower() == callsign.lower()), None)
    if _sel is None and _cands:
        _sel = _cands[0]

    iaxrpt_ok     = _sel is not None
    iaxrpt_secret = _sel["secret"] if _sel else ""
    iaxrpt_name   = _sel["name"]   if _sel else ""

    return {
        "callsign": callsign, "bindport": bindport,
        "nodes": nodes, "node_id": node_id,
        "reg_node": reg_node, "reg_pass": reg_pass, "reg_host": reg_host,
        "reg_source": reg_source, "node_mode_ok": node_mode_ok,
        "iaxrpt_ok": iaxrpt_ok, "iaxrpt_secret": iaxrpt_secret,
        "iaxrpt_name": iaxrpt_name,
    }

def _dvsm_account_direct_iax2(sh: dict, iax: dict, node_ip: str, wan_ip: str) -> dict:
    status = "pass" if (iax["raw_ok"] and sh["iaxrpt_ok"]) else "fail"
    fields = [
        {"label": "Protocol",   "value": "IAX2",    "masked": False, "secret": None,
         "note": "Fixed value — not read from config"},
        {"label": "Host (LAN)", "value": node_ip,   "masked": False, "secret": None,
         "note": "Use when on the same network as the node (detected live, not from a config file)"},
        {"label": "Host (WAN)", "value": wan_ip or None, "masked": False, "secret": None,
         "note": ("Use when connecting over the internet (via api.ipify.org / checkip.amazonaws.com)"
                  if wan_ip else "Could not detect — check router WAN address")},
        {"label": "Port",       "value": sh["bindport"],  "masked": False, "secret": None,
         "note": "Source: iax.conf [general] bindport"},
        {"label": "Username",   "value": sh["iaxrpt_name"] or "iaxrpt",
         "masked": False, "secret": None,
         "note": (f"Source: iax.conf section [{sh['iaxrpt_name']}]"
                  if sh["iaxrpt_name"] and sh["iaxrpt_name"] != "iaxrpt"
                  else "Source: iax.conf section name (defaults to \"iaxrpt\")")},
        {"label": "Password",   "value": None,      "masked": True,  "secret": sh["iaxrpt_secret"],
         "note": (f"From [{sh['iaxrpt_name']}] secret= in iax.conf"
                  if sh["iaxrpt_ok"] else "No user section with secret= found in iax.conf")},
        {"label": "CallerID",   "value": sh["callsign"],  "masked": False, "secret": None,
         "note": "Source: rpt.conf callsign → iax.conf CallerID → sysmon.conf [identity] (first match wins)"},
        {"label": "Caller Number", "value": "(leave blank)", "masked": False, "secret": None,
         "note": "Optional field on the DVSM account form — leave empty"},
        {"label": "Node",       "value": sh["node_id"],   "masked": False, "secret": None,
         "note": "Source: first public node (>1999) in rpt.conf"},
    ]
    notes = ["Phone Mode IAX2 connection — CHECK in DVSM account settings"]
    return {
        "status": status, "fields": fields, "notes": notes,
        "error": "" if iax["raw_ok"] else iax["error"],
    }

def _dvsm_account_iaxrpt(sh: dict, iax: dict, node_ip: str, wan_ip: str) -> dict:
    status = "pass" if (iax["raw_ok"] and sh["iaxrpt_ok"]) else "fail"
    fields = [
        {"label": "Protocol",    "value": "IAX2",          "masked": False, "secret": None,
         "note": "Fixed value — not read from config"},
        {"label": "Host (LAN)",  "value": node_ip,         "masked": False, "secret": None,
         "note": "Use when on the same network as the node (detected live, not from a config file)"},
        {"label": "Host (WAN)",  "value": wan_ip or None,  "masked": False, "secret": None,
         "note": ("Use when connecting over the internet (via api.ipify.org / checkip.amazonaws.com)"
                  if wan_ip else "Could not detect — check router WAN address")},
        {"label": "Port",        "value": sh["bindport"],  "masked": False, "secret": None,
         "note": "Source: iax.conf [general] bindport"},
        {"label": "Username",    "value": sh["iaxrpt_name"] or "iaxrpt",
         "masked": False, "secret": None,
         "note": (f"Source: iax.conf section [{sh['iaxrpt_name']}]"
                  if sh["iaxrpt_name"] and sh["iaxrpt_name"] != "iaxrpt"
                  else "Source: iax.conf section name (defaults to \"iaxrpt\")")},
        {"label": "Password",    "value": None,            "masked": True,
         "secret": sh["iaxrpt_secret"],
         "note": (f"From [{sh['iaxrpt_name']}] secret= in iax.conf"
                  if sh["iaxrpt_ok"] else "No user section with secret= found")},
        {"label": "CallerID",    "value": sh["callsign"],  "masked": False, "secret": None,
         "note": "Source: rpt.conf callsign → iax.conf CallerID → sysmon.conf [identity] (first match wins)"},
        {"label": "Caller Num",  "value": "0",             "masked": False, "secret": None,
         "note": "Fixed value — must be 0 (zero)"},
        {"label": "Node",        "value": sh["node_id"],   "masked": False, "secret": None,
         "note": "Source: first public node (>1999) in rpt.conf"},
    ]
    missing = (
        [] if sh["iaxrpt_ok"]
        else ["No user section with secret= found — add [iaxrpt] or [callsign] section to iax.conf"]
    )
    notes = [
        "Recommended connection method for DVSM — radio mode uses the least data"
        " and only transfers audio when the channel is active.",
        "Phone Mode IAX2 connection — UNCHECK · Caller Number MUST BE 0",
    ]
    return {
        "status": status, "fields": fields, "notes": notes, "missing": missing,
        "error": "" if iax["raw_ok"] else iax["error"],
    }

def _dvsm_account_node_mode(sh: dict, iax: dict) -> dict:
    status = "pass" if sh["node_mode_ok"] else ("warn" if iax["raw_ok"] else "fail")
    fields = [
        {"label": "Protocol",   "value": "IAX2",
         "masked": False, "secret": None, "note": "Fixed value — not read from config"},
        {"label": "Hostname",   "value": "register.allstarlink.org",
         "masked": False, "secret": None, "note": "Fixed value — always register.allstarlink.org"},
        {"label": "Port",       "value": "4569",
         "masked": False, "secret": None, "note": "Fixed value — AllStarLink registration port"},
        {"label": "Username",   "value": sh["reg_node"],
         "masked": False, "secret": None,
         "note": "Source: first public register=> node number in iax.conf"},
        {"label": "Password",   "value": None,  "masked": True,
         "secret": sh["reg_pass"],
         "note": (f"From {sh['reg_source'] or 'iax.conf'} — register=>{sh['reg_node']}:●●@{sh['reg_host']}"
                  if sh["reg_pass"] else "No register=> line found for a public node (>1999)")},
        {"label": "CallerID",   "value": sh["callsign"],
         "masked": False, "secret": None,
         "note": "Source: rpt.conf callsign → iax.conf CallerID → sysmon.conf [identity] (first match wins)"},
        {"label": "Caller Number", "value": "(leave blank)", "masked": False, "secret": None,
         "note": "Optional field on the DVSM account form — leave empty"},
        {"label": "Node",       "value": "(leave blank)",
         "masked": False, "secret": None,
         "note": "Leave the Node field empty in DVSM"},
    ]
    notes = [
        "Use an UNUSED node number registered to your callsign at allstarlink.org",
        "Auto Connect — UNCHECK",
    ]
    return {
        "status": status, "fields": fields, "notes": notes,
        "error": "" if iax["raw_ok"] else iax["error"],
    }

def _dvsm_account_usrp(sh: dict, ab: dict, node_ip: str, wan_ip: str) -> dict:
    usrp_ok  = ab["raw_ok"] and bool(ab["rx_port"]) and bool(ab["tx_port"])
    status   = "pass" if usrp_ok else ("warn" if ab["raw_ok"] else "fail")
    _ab_addr = ab["address"] or "127.0.0.1"
    dmr_id, dmr_id_source = _resolve_node_dmr_id("")
    fields = [
        {"label": "Protocol",    "value": "USRP",
         "masked": False, "secret": None, "note": "Fixed value — not read from config"},
        {"label": "Host (local)", "value": _ab_addr,
         "masked": False, "secret": None,
         "note": "Use when DVSM runs on this node (loopback) — Source: analog_bridge.cfg [USRP] address"},
        {"label": "Host (LAN)",  "value": node_ip,
         "masked": False, "secret": None,
         "note": "Use when DVSM is on the same network (detected live, not from a config file)"},
        {"label": "Host (WAN)",  "value": wan_ip or None,
         "masked": False, "secret": None,
         "note": ("Use when connecting over the internet (via api.ipify.org / checkip.amazonaws.com)"
                  if wan_ip else "Could not detect — check router WAN address")},
        {"label": "DVSM TX→",   "value": ab["rx_port"] or "—",
         "masked": False, "secret": None,
         "note": "Source: analog_bridge.cfg [USRP] rxPort — DVSM sends audio here"},
        {"label": "DVSM RX←",  "value": ab["tx_port"] or "—",
         "masked": False, "secret": None,
         "note": "Source: analog_bridge.cfg [USRP] txPort — DVSM receives audio here"},
        {"label": "Callsign",   "value": sh["callsign"],
         "masked": False, "secret": None,
         "note": "Source: rpt.conf callsign → iax.conf CallerID → sysmon.conf [identity] (first match wins)"},
        {"label": "DMR ID",     "value": dmr_id or "—",
         "masked": False, "secret": None,
         "note": (f"Source: {dmr_id_source}" if dmr_id_source
                  else "Not set — check MMDVM_Bridge.ini [General] Id")},
    ]
    notes = [
        "Ports shown from ASL perspective. DVSM TX → ASL rxPort; DVSM RX ← ASL txPort.",
    ]
    if ab.get("source"):
        notes.append(f"Source: {ab['source']}")
    error = "" if ab["raw_ok"] else ab["error"]
    return {"status": status, "fields": fields, "notes": notes, "error": error}

def _dvsm_compat_checks(sh: dict, iax: dict, rpt: dict) -> list:
    nodes = sh["nodes"]
    compat: list = []

    def _compat(key: str, source: str, enables: str, val: bool,
                fix: "str | None", info_msg: "str | None" = None) -> dict:
        if info_msg:
            return {"key": key, "source": source, "enables": enables,
                    "status": "info", "value": info_msg, "fix": None}
        return {"key": key, "source": source, "enables": enables,
                "status": "pass" if val else "fail",
                "value": "yes" if val else "not set",
                "fix": fix if not val else None}

    if nodes:
        nid = nodes[0]["id"]
        n   = nodes[0]
        src = f"rpt.conf [{nid}]"
        def _opt(key: str, enables: str, val: bool, line: str) -> dict:
            if val:
                return {"key": key, "source": src, "enables": enables,
                        "status": "pass", "value": "yes", "fix": None}
            return {"key": key, "source": src, "enables": enables,
                    "status": "info", "value": "not set",
                    "fix": f"Only needed for DVSwitch Mobile -- add '{line}' to [{nid}] in rpt.conf, restart asterisk"}

        def _risky(key: str, enables: str, val: bool, why: str) -> dict:
            if val:
                return {"key": key, "source": src, "enables": enables,
                        "status": "warn", "value": "yes",
                        "fix": f"On: {why} Leave it off unless you need it."}
            return {"key": key, "source": src, "enables": enables,
                    "status": "info", "value": "not set",
                    "fix": "Off (safer). Only turn on if DVSwitch Mobile really needs it."}

        compat += [
            _opt("propagate_dtmf", "DTMF commands from DVSM",
                 n["propagate_dtmf"], "propagate_dtmf = yes"),
            _risky("propagate_phonedtmf", "Phone DTMF (HamVoIP nodes)",
                   n["propagate_phonedtmf"],
                   "phone callers' tones (like *99 and #) are passed to every linked node, bridges included."),
            _risky("remote_dtmf_allowed", "DTMF from remote connections",
                   n["remote_dtmf_allowed"],
                   "any linked node can send commands to this node."),
            _opt("phonesendlinks", "DVSM Status tab — linked-node list",
                 n["phonesendlinks"], "phonesendlinks = 1"),
        ]
    else:
        compat.append({
            "key": "rpt.conf", "source": "rpt.conf", "status": "fail",
            "enables": "all DVSM rpt features",
            "value": rpt.get("error", "no node sections found"),
            "fix": None,
        })

    rct_val = iax.get("requirecalltoken", "").lower()
    cto_val = iax.get("calltokenopt",     "").lower()
    if not rct_val and not cto_val:
        compat.append(_compat(
            "requirecalltoken", "iax.conf",
            "Call token enforcement (DVSM handles automatically)",
            True, None,
            info_msg="Not set — default behavior. DVSM handles call tokens automatically.",
        ))
    else:
        rct_relaxed = rct_val in ("no", "0", "false")
        compat.append({
            "key":     "requirecalltoken",
            "source":  "iax.conf",
            "enables": "Non-node client connections (HamVoIP compat)",
            "status":  "pass" if rct_relaxed else "info",
            "value":   iax.get("requirecalltoken", ""),
            "fix":     None,
        })

    compat.append({
        "key":     f"[{sh['iaxrpt_name']}] section" if sh["iaxrpt_ok"] else "[iaxrpt] section",
        "source":  "iax.conf",
        "enables": "IAXRpt radio-mode connections",
        "status":  "pass" if sh["iaxrpt_ok"] else "fail",
        "value":   (f"found as [{sh['iaxrpt_name']}]" if sh["iaxrpt_ok"] else "missing"),
        "fix":     ("No user section with secret= found — add [iaxrpt] or [callsign] section"
                    if not sh["iaxrpt_ok"] else None),
    })
    return compat

def _build_dvsm_payload() -> dict:
    node_ip  = _dvsm_node_ip()
    wan_ip   = _dvsm_wan_ip()
    iax      = _dvsm_read_iax_conf()
    rpt      = _dvsm_read_rpt_conf()
    ab       = _dvsm_read_ab()

    sh = _dvsm_resolve_shared(iax, rpt)

    direct    = _dvsm_account_direct_iax2(sh, iax, node_ip, wan_ip)
    iaxrpt    = _dvsm_account_iaxrpt(sh, iax, node_ip, wan_ip)
    node_mode = _dvsm_account_node_mode(sh, iax)
    usrp      = _dvsm_account_usrp(sh, ab, node_ip, wan_ip)
    compat    = _dvsm_compat_checks(sh, iax, rpt)

    return {
        "node_ip":  node_ip,
        "callsign": sh["callsign"],
        "accounts": {
            "direct_iax2": direct,
            "iaxrpt":      iaxrpt,
            "node_mode":   node_mode,
            "usrp":        usrp,
        },
        "compat": compat,
    }

def _route_dvsm(h: Handler) -> None:
    payload = _build_dvsm_payload()
    payload["ok"] = True
    h.send_json(payload)

_STFU_SERVICE_NAME  = "stfu"

_STFU_SERVICE_PATHS = [
    Path("/lib/systemd/system/stfu.service"),
    Path("/etc/systemd/system/stfu.service"),
]

def _stfu_install_check() -> dict:

    binary_ok   = (
        _STFU_BINARY.exists()
        and os.access(str(_STFU_BINARY), os.X_OK)
    )
    binary_path = str(_STFU_BINARY) if binary_ok else ""

    svc_path, svc_installed, svc_active, svc_enabled = _svc_install_state(
        _STFU_SERVICE_NAME, _STFU_SERVICE_PATHS)

    return {
        "binary_ok":         binary_ok,
        "binary_path":       binary_path,
        "service_installed": svc_installed,
        "service_path":      svc_path,
        "service_active":    svc_active,
        "service_enabled":   svc_enabled,
    }

def _stfu_sample_stanza(cfg: dict) -> str:

    lines = [
        "[STFU]",
        f"BMAddress={_placeholder(cfg['bm_address'],    'BM server address')}",
        f"BMPort={cfg['bm_port'] or '62031'}",
        "BMPassword=<your BM hotspot password>",
        f"UserID={_placeholder(cfg['dmr_id'],           'your DMR ID')}",
        f"Address={cfg['address'] or '127.0.0.1'}",
        f"RXPort={_placeholder(cfg['rx_port'],           'rx port')}",
        f"TXPort={_placeholder(cfg['tx_port'],           'tx port')}",
        f"StartTG={_placeholder(cfg['start_tg'],         'starting talkgroup')}",
        f"subscriberFile={_placeholder(cfg['subscriber_file'], '/opt/STFU/subscriber_ids.csv')}",
        f"TalkerAlias={cfg['talker_alias'] or '1'}",
        f"LogLevel={cfg['log_level'] or '1'}",
    ]
    return "\n".join(lines)

def _stfu_build_fields(cfg: dict) -> list:
    sub_val  = cfg["subscriber_file"] or "—"
    sub_note = None
    if cfg["subscriber_ok"] and cfg["subscriber_rows"] > 0:
        sub_note = f"Found — {cfg['subscriber_rows']:,} IDs"
    elif cfg["subscriber_ok"]:
        sub_note = "Found (row count unavailable)"
    elif cfg["subscriber_file"]:
        sub_note = "File not found on disk"
    else:
        sub_note = "Not configured — download from radioid.net"

    dmr_note = (f"From {cfg['dmr_id_source']}"
                if cfg["dmr_id_source"] else "Not found in any config file")

    return [

        {"group": "BrandMeister Connection"},
        {"label": "BM Server",   "value": cfg["bm_address"] or None,
         "masked": False, "secret": None,
         "note": "Regional servers at brandmeister.network — see master server page"
                 if cfg["bm_address"] else "Not set — enter BM server address"},
        {"label": "BM Port",     "value": cfg["bm_port"],
         "masked": False, "secret": None, "note": "Default 62031"},
        {"label": "BM Password", "value": None,
         "masked": True,  "secret": cfg["bm_password"],
         "note": ("brandmeister.network → Self Care → Hotspot Security"
                  if cfg["bm_password"] else
                  "Not set — brandmeister.network → Self Care → Hotspot Security")},

        {"group": "Identity"},
        {"label": "DMR ID", "value": cfg["dmr_id"] or None,
         "masked": False, "secret": None, "note": dmr_note},

        {"group": "USRP Bridge Ports"},
        {"label": "Address", "value": cfg["address"],
         "masked": False, "secret": None, "note": "Local address for USRP bridge"},
        {"label": "RX Port", "value": cfg["rx_port"] or None,
         "masked": False, "secret": None, "note": "STFU listens here"},
        {"label": "TX Port", "value": cfg["tx_port"] or None,
         "masked": False, "secret": None, "note": "STFU sends here"},

        {"group": "Startup & Logging"},
        {"label": "Start TG",        "value": cfg["start_tg"] or None,
         "masked": False, "secret": None, "note": "Talkgroup to join on service start"},
        {"label": "Subscriber File", "value": sub_val,
         "masked": False, "secret": None, "note": sub_note},
        {"label": "Talker Alias",    "value": cfg["talker_alias"] or "1",
         "masked": False, "secret": None, "note": "1 = send name with transmission"},
        {"label": "Log Level",       "value": cfg["log_level"] or "1",
         "masked": False, "secret": None, "note": "1 = normal, 2 = debug"},
    ]

def _stfu_build_compat(cfg: dict, inst: dict) -> list:
    bm_ok   = bool(cfg["bm_address"]) and cfg["bm_address"] != _DVS_DEF_SERVER
    pw_ok   = bool(cfg["bm_password"])
    id_ok   = bool(cfg["dmr_id"])  and cfg["dmr_id"] != _DVS_DEF_DMR_ID
    port_ok = bool(cfg["rx_port"]) and bool(cfg["tx_port"])

    return [
        {"key": "BMAddress configured",
         "enables": "BrandMeister server set",
         "status": "pass" if bm_ok else "fail",
         "value":  cfg["bm_address"] or "not set",
         "fix":    "Set BMAddress in DVSwitch.ini [STFU]" if not bm_ok else None},
        {"key": "BMPassword set",
         "enables": "Hotspot password present",
         "status": "pass" if pw_ok else "fail",
         "value":  "set" if pw_ok else "not set",
         "fix":    ("brandmeister.network → Self Care → Hotspot Security"
                    if not pw_ok else None)},
        {"key": "UserID configured",
         "enables": "DMR ID non-default",
         "status": "pass" if id_ok else "fail",
         "value":  cfg["dmr_id"] or "not set",
         "fix":    "Set UserID in DVSwitch.ini [STFU]" if not id_ok else None},
        {"key": "Ports configured",
         "enables": "RX and TX ports set",
         "status": "pass" if port_ok else "warn",
         "value":  f"RX={cfg['rx_port'] or '—'} TX={cfg['tx_port'] or '—'}",
         "fix":    "Set RXPort and TXPort in DVSwitch.ini [STFU]" if not port_ok else None},
        {"key": "Subscriber file found",
         "enables": "DMR ID → callsign lookup",
         "status": "pass" if cfg["subscriber_ok"] else "warn",
         "value":  (f"{cfg['subscriber_rows']:,} IDs"
                    if cfg["subscriber_ok"] and cfg["subscriber_rows"] > 0
                    else ("found" if cfg["subscriber_ok"] else "not found")),
         "fix":    "Download from radioid.net and set subscriberFile path" if not cfg["subscriber_ok"] else None},
        {"key": "Service running",
         "enables": "STFU active",
         "status": ("pass" if inst["service_active"] else
                    "warn" if inst["service_installed"] else "fail"),
         "value":  ("active"    if inst["service_active"]    else
                    "installed" if inst["service_installed"]  else "not installed"),
         "fix":    ("systemctl start stfu" if inst["service_installed"] and not inst["service_active"]
                    else "Install stfu.service — see DVSwitch GitHub" if not inst["service_installed"]
                    else None)},
    ]

def _build_stfu_payload() -> dict:
    inst = _stfu_install_check()
    cfg  = _stfu_read_config()

    fields = _stfu_build_fields(cfg)
    compat = _stfu_build_compat(cfg, inst)

    return {
        "ok":           True,
        "install":      inst,
        "config":       {
            "raw_ok":       cfg["raw_ok"],
            "dvs_path":     cfg["dvs_path"],
            "stfu_present": cfg["stfu_present"],
            "fields":       fields,
            "error":        cfg.get("error", ""),
        },
        "compat":        compat,
        "sample_stanza": _stfu_sample_stanza(cfg),
        "dvs_path":      cfg["dvs_path"],
    }

def _route_stfu_get(h: Handler) -> None:
    h.send_json(_build_stfu_payload())

def _route_stfu_post(h: Handler, data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "root required"}); return

    action = str(data.get("action", "")).strip().lower()

    if action == "restart":
        try:
            _run(["systemctl", "restart", _STFU_SERVICE_NAME], timeout=10)
            h.send_json({"ok": True, "message": "stfu restarted"})
        except Exception as exc:
            h.send_json({"ok": False, "message": str(exc)})
        return

    h.send_json({"ok": False, "message": f"unknown action '{action}'"}, 400)

_M17_BINARY        = Path("/opt/USRP2M17/USRP2M17")

_M17_SERVICE_NAME  = "usrp2m17"

_M17_SERVICE_PATHS = [
    Path("/lib/systemd/system/usrp2m17.service"),
    Path("/etc/systemd/system/usrp2m17.service"),
]

_M17_EXPECT_USRP_DST_PORT   = "32008"

_M17_EXPECT_USRP_LOCAL_PORT = "34008"

def _m17_install_check() -> dict:
    binary_ok   = (
        _M17_BINARY.exists()
        and os.access(str(_M17_BINARY), os.X_OK)
    )
    binary_path = str(_M17_BINARY) if binary_ok else ""

    svc_path, svc_installed, svc_active, svc_enabled = _svc_install_state(
        _M17_SERVICE_NAME, _M17_SERVICE_PATHS)

    return {
        "binary_ok":         binary_ok,
        "binary_path":       binary_path,
        "service_installed": svc_installed,
        "service_path":      svc_path,
        "service_active":    svc_active,
        "service_enabled":   svc_enabled,
    }

def _m17_build_fields(cfg: dict) -> list:
    is_disconnected = (not cfg["address"]) or cfg["address"] == _M17_PLACEHOLDER_ADDRESS
    refl_note = ("Not connected — placeholder address"
                 if is_disconnected else
                 "Rewritten in full by the ASL-DVS-M17 dashboard on every connect")

    return [
        {"group": "Reflector"},
        {"label": "Callsign",  "value": cfg["callsign"] or None,
         "masked": False, "secret": None,
         "note": "Not set" if not cfg["callsign"] else None},
        {"label": "Name",      "value": cfg["name"] or None,
         "masked": False, "secret": None, "note": refl_note},
        {"label": "Address",   "value": cfg["address"] or None,
         "masked": False, "secret": None, "note": refl_note},

        {"group": "M17 Network"},
        {"label": "LocalPort",     "value": cfg["m17_local_port"] or None,
         "masked": False, "secret": None, "note": "Bridge's outbound port toward the reflector"},
        {"label": "DstPort",       "value": cfg["m17_dst_port"] or None,
         "masked": False, "secret": None, "note": "Standard M17 reflector port (17000)"},
        {"label": "GainAdjustdB",  "value": cfg["m17_gain"] or None,
         "masked": False, "secret": None, "note": None},

        {"group": "USRP Bridge Ports"},
        {"label": "Address",      "value": cfg["usrp_address"] or None,
         "masked": False, "secret": None, "note": "Should be 127.0.0.1 — ASL is local"},
        {"label": "DstPort",      "value": cfg["usrp_dst_port"] or None,
         "masked": False, "secret": None,
         "note": f"ASL listens here; bridge sends here — expected {_M17_EXPECT_USRP_DST_PORT}"},
        {"label": "LocalPort",    "value": cfg["usrp_local_port"] or None,
         "masked": False, "secret": None,
         "note": f"Bridge listens here; ASL sends here — expected {_M17_EXPECT_USRP_LOCAL_PORT}"},
        {"label": "GainAdjustdB", "value": cfg["usrp_gain"] or None,
         "masked": False, "secret": None, "note": None},

        {"group": "Logging"},
        {"label": "DisplayLevel", "value": cfg["display_level"] or "0",
         "masked": False, "secret": None, "note": None},
        {"label": "FileLevel",    "value": cfg["file_level"] or "0",
         "masked": False, "secret": None, "note": None},
        {"label": "FilePath",     "value": cfg["file_path"] or None,
         "masked": False, "secret": None, "note": None},
        {"label": "FileRoot",     "value": cfg["file_root"] or None,
         "masked": False, "secret": None, "note": None},
    ]

def _m17_build_compat(cfg: dict, inst: dict) -> list:
    callsign_ok = bool(cfg["callsign"])
    addr_ok     = bool(cfg["address"]) and cfg["address"] != _M17_PLACEHOLDER_ADDRESS
    ports_ok    = (cfg["usrp_dst_port"]   == _M17_EXPECT_USRP_DST_PORT and
                   cfg["usrp_local_port"] == _M17_EXPECT_USRP_LOCAL_PORT)

    compat = [
        {"key": "Callsign configured",
         "enables": "M17 Network Callsign set",
         "status": "pass" if callsign_ok else "fail",
         "value":  cfg["callsign"] or "not set",
         "fix":    "Set Callsign via an M17 connect on the ASL-DVS-M17 dashboard" if not callsign_ok else None},
        {"key": "Reflector connected",
         "enables": "Address is a real reflector, not the disconnect placeholder",
         "status": "pass" if addr_ok else "warn",
         "value":  cfg["address"] or "not set",
         "fix":    None if addr_ok else "Not an error — this is expected when idle/disconnected"},
        {"key": "USRP ports match dashboard scheme",
         "enables": f"DstPort={_M17_EXPECT_USRP_DST_PORT} / LocalPort={_M17_EXPECT_USRP_LOCAL_PORT}",
         "status": "pass" if ports_ok else "fail",
         "value":  f"DstPort={cfg['usrp_dst_port'] or '—'} LocalPort={cfg['usrp_local_port'] or '—'}",
         "fix":    ("Ports have drifted from the ASL-DVS-M17 dashboard's fixed scheme — "
                    "rpt.conf's [1917] rxchannel will silently stop matching") if not ports_ok else None},
        {"key": "Service running",
         "enables": "usrp2m17 active",
         "status": ("pass" if inst["service_active"] else
                    "warn" if inst["service_installed"] else "fail"),
         "value":  ("active"    if inst["service_active"]    else
                    "installed" if inst["service_installed"] else "not installed"),
         "fix":    ("systemctl start usrp2m17" if inst["service_installed"] and not inst["service_active"]
                    else "Install usrp2m17.service — see USRP2M17 Bridge Manual" if not inst["service_installed"]
                    else None)},
    ]

    rpt  = _dvsm_read_rpt_conf()
    node = _m17_find_rpt_node(rpt, "1917") if rpt.get("raw_ok") else None
    if not rpt.get("raw_ok"):
        compat.append({
            "key": "rpt.conf [1917] node stanza",
            "enables": "M17 bridge linkable via ASL",
            "status": "warn",
            "value": "rpt.conf unreadable",
            "fix": rpt.get("error") or "Check /etc/asterisk/rpt.conf permissions",
        })
    elif node is None:
        compat.append({
            "key": "rpt.conf [1917] node stanza",
            "enables": "M17 bridge linkable via ASL",
            "status": "fail",
            "value": "not found",
            "fix": ("Add a [1917] node stanza with "
                    f"rxchannel = USRP/127.0.0.1:{_M17_EXPECT_USRP_LOCAL_PORT}:{_M17_EXPECT_USRP_DST_PORT} "
                    "— see USRP2M17-Selector manual §3.1"),
        })
    else:
        rx_tx = node.get("usrp_rx", "")
        rx_rx = node.get("usrp_tx", "")
        node_ports_match = (rx_tx == cfg["usrp_local_port"] and rx_rx == cfg["usrp_dst_port"])
        compat.append({
            "key": "rpt.conf [1917] node stanza",
            "enables": "M17 bridge linkable via ASL",
            "status": "pass" if node_ports_match else "warn",
            "value": node.get("rxchannel") or "present, rxchannel unparsed",
            "fix": (None if node_ports_match else
                    f"rxchannel ports don't match USRP2M17.ini — expect "
                    f"USRP/127.0.0.1:{cfg['usrp_local_port'] or '?'}:{cfg['usrp_dst_port'] or '?'}"),
        })

    return compat

def _m17_sample_stanza(cfg: dict) -> str:

    lines = [
        "[M17 Network]",
        f"Callsign={_placeholder(cfg['callsign'], 'your callsign')}",
        f"Address={_placeholder(cfg['address'], 'reflector IP')}",
        f"Name={_placeholder(cfg['name'], 'M17-XXX C')}",
        f"LocalPort={cfg['m17_local_port'] or '17010'}",
        f"DstPort={cfg['m17_dst_port'] or '17000'}",
        f"GainAdjustdB={cfg['m17_gain'] or '3'}",
        "",
        "[USRP Network]",
        f"Address={cfg['usrp_address'] or '127.0.0.1'}",
        f"DstPort={cfg['usrp_dst_port'] or _M17_EXPECT_USRP_DST_PORT}",
        f"LocalPort={cfg['usrp_local_port'] or _M17_EXPECT_USRP_LOCAL_PORT}",
        f"GainAdjustdB={cfg['usrp_gain'] or '3'}",
        "",
        "[Log]",
        f"DisplayLevel={cfg['display_level'] or '0'}",
        f"FileLevel={cfg['file_level'] or '0'}",
        f"FilePath={cfg['file_path'] or '/var/log/usrp'}",
        f"FileRoot={cfg['file_root'] or 'USRP2M17'}",
    ]
    return "\n".join(lines)

def _m17hosts_status() -> dict:
    base = {"path": str(_M17HOSTS_DEST), "size": 0, "mtime": None, "age_days": None}
    if not _M17HOSTS_DEST.exists():
        return {**base, "present": False, "ok": False, "count": 0,
                "generated": "", "error": "file not found"}
    try:
        raw = _M17HOSTS_DEST.read_bytes()
        st  = _M17HOSTS_DEST.stat()
    except OSError as exc:
        return {**base, "present": True, "ok": False, "count": 0,
                "generated": "", "error": str(exc)}

    v = _m17hosts_validate(raw)
    return {
        "present":   True,
        "ok":        v["ok"],
        "count":     v["count"],
        "generated": v["generated"],
        "error":     v["error"],
        "size":      st.st_size,
        "mtime":     datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        "age_days":  round((time.time() - st.st_mtime) / 86400, 1),
        "path":      str(_M17HOSTS_DEST),
    }

def _build_m17_payload() -> dict:
    inst = _m17_install_check()
    cfg  = _m17_read_config()

    fields = _m17_build_fields(cfg)
    compat = _m17_build_compat(cfg, inst)

    return {
        "ok":           True,
        "install":      inst,
        "config":       {
            "raw_ok":  cfg["raw_ok"],
            "ini_path": cfg["ini_path"],
            "fields":  fields,
            "error":   cfg.get("error", ""),
        },
        "compat":        compat,
        "sample_stanza": _m17_sample_stanza(cfg),
        "ini_path":      cfg["ini_path"],
        "hosts":         _m17hosts_status(),
    }

def _route_m17_get(h: Handler) -> None:
    h.send_json(_build_m17_payload())

def _route_m17_post(h: Handler, data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "root required"}); return

    action = str(data.get("action", "")).strip().lower()

    if action == "restart":
        try:
            _run(["systemctl", "restart", _M17_SERVICE_NAME], timeout=10)
            h.send_json({"ok": True, "message": "usrp2m17 restarted"})
        except Exception as exc:
            h.send_json({"ok": False, "message": str(exc)})
        return

    if action == "update_hosts":
        try:
            r = _m17hosts_fetch()
        except Exception as exc:
            h.send_json({"ok": False, "message": str(exc)})
            return
        if not r["ok"]:
            h.send_json({"ok": False, "message": r["error"] or "update failed", **r})
            return
        msg = (f"unchanged — {r['count']} reflectors, list generated {r['generated']}"
               if not r["changed"] else
               f"updated — {r['count']} reflectors, list generated {r['generated']}")
        h.send_json({"ok": True, "message": msg, **r})
        return

    h.send_json({"ok": False, "message": f"unknown action '{action}'"}, 400)

_IRCDDB_CONF_PATH = Path("/etc/ircddbgateway")
_IRCDDB_SERVICE   = "ircddbgatewayd.service"

def _cmd_or_problem(argv: list, timeout: int = 8) -> "tuple[str, str]":
    if not shutil.which(argv[0]):
        return "", f"{argv[0]} is not installed on this Pi"
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "", f"{argv[0]} took longer than {timeout} s"
    except OSError as exc:
        return "", f"{argv[0]} could not run: {exc}"
    return (r.stdout or "") + (("\n" + r.stderr) if r.stderr and not r.stdout else ""), ""

def _udp_listeners() -> "tuple[dict, str]":
    out, prob = _cmd_or_problem(["ss", "-Hlunp"], 6)
    res = {}
    for ln in out.splitlines():
        m = re.search(r"\s(\S+):(\d+)\s+\S+\s*(?:users:\(\(\"([^\"]+)\")?", ln)
        if m:
            res.setdefault(m.group(2), set()).add(m.group(3) or "?")
    return res, prob

def _ircddb_read_conf() -> "tuple[dict, str]":
    try:
        text = _IRCDDB_CONF_PATH.read_text(errors="replace")
    except FileNotFoundError:
        return {}, "missing"
    except OSError as exc:
        return {}, f"can't read it: {exc}"
    kv: dict = {}
    for ln in text.splitlines():
        k, sep, v = ln.partition("=")
        if sep and k.strip() and not k.lstrip().startswith(("#", ";")):
            kv[k.strip()] = v.strip()
    return kv, ""

def _pi_ipv4s() -> "set[str]":
    out = _run(["ip", "-o", "-4", "addr", "show"], timeout=4)
    return set(re.findall(r"\binet (\d+\.\d+\.\d+\.\d+)/", out))

_IRCDDB_ENABLE_KEYS = (("ircddbEnabled", "1"), ("ircddbEnabled2", "1"), ("ircddbEnabled3", "0"), ("ircddbEnabled4", "0"))

def _dstar_gw_checks() -> dict:
    kv, prob = _ircddb_read_conf()
    path = str(_IRCDDB_CONF_PATH)
    svc = get_service_state(_IRCDDB_SERVICE)
    rows: list = []

    def row(key, enables, status, fix=None):
        rows.append({"key": key, "enables": enables, "status": status, "fix": fix})

    row(f"{_IRCDDB_SERVICE}: {svc}", "D-Star gateway service running",
        "pass" if svc == "active" else "fail",
        None if svc == "active" else "Start it: sudo systemctl start ircddbgatewayd")

    if prob:
        missing = prob == "missing"
        row(path, "ircDDBGateway config file", "fail",
            "Not found -- is ircDDBGateway installed?" if missing else f"{path}: {prob}")
        return {"ok": True, "path": path, "present": not missing, "status": "fail",
                "badge": "MISSING" if missing else "FAIL", "service": svc, "checks": rows}

    gw = kv.get("gatewayCallsign", "").upper()
    row(f"gatewayCallsign = {gw or '(blank)'}", "Gateway callsign",
        "pass" if gw else "fail", None if gw else "Set gatewayCallsign to your callsign")

    band = kv.get("repeaterBand1", "").upper()
    rcall = (kv.get("repeaterCall1", "") or gw).upper()
    band_ok = len(band) == 1 and band.isalpha()
    ident = (rcall[:7].ljust(7) + band) if (rcall and band_ok) else ""
    row(f"repeaterBand1 = {band or '(blank)'}" + (f"  ->  {ident}" if ident else ""),
        "Repeater 1 module (how the dashboard names this node)",
        "pass" if ident else "fail",
        None if ident else "Set repeaterBand1 to a module letter, e.g. B")

    def flag(k, d):
        v = kv.get(k)
        if v is None:
            return d == "1", f"{k} not set" + (" (on by default)" if d == "1" else "")
        return v.strip() == "1", f"{k} = {v}"

    irc = [flag(k, d) for k, d in _IRCDDB_ENABLE_KEYS]
    irc_on = [t for o, t in irc if o]
    row("; ".join(irc_on) if irc_on else irc[0][1], "ircDDB (finds gateway callsigns)",
        "pass" if irc_on else "warn",
        None if irc_on else "Set ircddbEnabled=1. Reflectors still work without it, "
                            "but gateway callsigns can't be found")

    dx, dx_txt = flag("dextraEnabled", "1")
    row(dx_txt, "DExtra (gateway links and XRF reflectors use it)",
        "pass" if dx else "fail",
        None if dx else "Set dextraEnabled=1 -- ircDDBGateway refuses gateway links and XRF reflectors without it")

    rc_on = kv.get("remoteEnabled", "0") == "1"
    row(f"remoteEnabled = {kv.get('remoteEnabled', '(not set)')}", "Remote control (dashboard gateway links)",
        "pass" if rc_on else "warn",
        None if rc_on else "Optional: set remoteEnabled=1 so the dashboard hears whether a gateway link was "
                           "accepted, and links work even with a fixed reconnect "
                           "(without it the dashboard uses dvswitch.sh tune)")

    pw = kv.get("remotePassword", "")
    try:
        port = int(kv.get("remotePort", "0") or 0)
    except ValueError:
        port = 0
    port_ok = 0 < port < 65536
    if rc_on:
        row("remotePassword = " + ("(set)" if pw else "(blank)"), "Remote control password",
            "pass" if pw else "fail", None if pw else "Set remotePassword -- remote control stays off without one")
        row(f"remotePort = {kv.get('remotePort', '(not set)')}", "Remote control UDP port",
            "pass" if port_ok else "fail", None if port_ok else "Set remotePort to a free UDP port, e.g. 10022")
        if port_ok:
            lis, lprob = _udp_listeners()
            if lprob:
                row(f"UDP {port}", "Remote control listening", "info", f"Can't check: {lprob}")
            else:
                up = str(port) in lis
                row(f"UDP {port}: " + ("listening" if up else "not listening"), "Remote control listening",
                    "pass" if up else "warn",
                    None if up else "Restart ircddbgatewayd to apply the remote-control settings")
    else:
        row("remotePassword / remotePort", "Only needed with remote control on", "info")

    addr = kv.get("gatewayAddress", "")
    if not addr or addr == "0.0.0.0":
        row("gatewayAddress = " + (addr or "(blank)"), "Listen address (this Pi's, not the router's)", "pass",
            "Normal: all of this Pi's addresses." + (f" Don't forward UDP {port} on your router."
                                                     if rc_on and port_ok else ""))
    elif addr.startswith("127."):
        row(f"gatewayAddress = {addr}", "Listen address (this Pi's, not the router's)", "fail",
            "Loopback blocks reflector and gateway links -- leave gatewayAddress blank")
    else:
        mine = _pi_ipv4s()
        if mine and addr not in mine:
            row(f"gatewayAddress = {addr}", "Listen address (this Pi's, not the router's)", "fail",
                f"Not an address of this Pi ({', '.join(sorted(mine))}) -- leave it blank, "
                f"don't use the router's address")
        else:
            row(f"gatewayAddress = {addr}", "Listen address (this Pi's, not the router's)", "pass")

    statuses = [r["status"] for r in rows]
    status = "fail" if "fail" in statuses else "warn" if "warn" in statuses else "pass"
    return {"ok": True, "path": path, "present": True, "status": status,
            "badge": {"pass": "OK", "warn": "WARN", "fail": "FAIL"}[status],
            "service": svc, "checks": rows}

def _route_dstar_gw_get(h: Handler) -> None:
    h.send_json(_dstar_gw_checks())

def _route_dstar_gw_post(h: Handler, data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "root required"}); return
    action = str(data.get("action", "")).strip().lower()
    if action == "restart":
        try:
            r = subprocess.run(["systemctl", "restart", _IRCDDB_SERVICE],
                               capture_output=True, text=True, timeout=20)
        except Exception as exc:
            h.send_json({"ok": False, "message": str(exc)}); return
        if r.returncode != 0:
            h.send_json({"ok": False, "message": (r.stderr or r.stdout or "restart failed").strip()}); return
        h.send_json({"ok": True, "message": "ircddbgatewayd restarted"})
        return
    h.send_json({"ok": False, "message": f"unknown action '{action}'"}, 400)

_NL_BINS      = (Path("/usr/local/bin/nodetalker.py"), Path("/usr/local/bin/nodelisten.py"))
_NL_CONFS     = (Path("/etc/asl_dvs/nodetalker.conf"), Path("/etc/asl_dvs/nodelisten.conf"))
_NL_DASH_CONF = Path("/etc/asl_dvs/asl_dvs.conf")
_NL_SERVICES  = ("nodetalker.service", "nodelisten.service")
_NL_FEED_MARKS = ("nodelisten.py,--feed,", "nodetalker.py,--feed,")

def _nl_conf_path() -> Path:
    return next((p for p in _NL_CONFS if p.exists()), _NL_CONFS[0])

def _nl_service() -> str:
    return next((s for s in _NL_SERVICES if get_service_installed(s)), _NL_SERVICES[0])
_NL_TX_NODE   = "1921"
_NL_TX_SEND   = 32018
_NL_TX_LISTEN = 34018
_NL_DEFAULTS  = {"port": 8993, "udp_port": 6200, "node": "", "https": True, "allow_wan": False,
                 "public_listen": False, "max_listeners": 3}
_NL_TAILNET   = ipaddress.ip_network("100.64.0.0/10")
_NL_IP_RE     = re.compile(r"^[0-9A-Fa-f:.]{2,45}$")

def _nl_bool(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")

def _nl_read_conf() -> "tuple[dict, str]":
    cfg = dict(_NL_DEFAULTS)
    conf = _nl_conf_path()
    if not conf.exists():
        return cfg, "missing"
    cp = configparser.ConfigParser(interpolation=None)
    try:
        cp.read(str(conf))
    except (configparser.Error, OSError) as exc:
        return cfg, f"can't read it: {exc}"
    name = next((s for s in ("nodetalker", "nodelisten") if cp.has_section(s)), "")
    if name:
        sec = cp[name]
        for k in ("port", "udp_port", "max_listeners"):
            v = sec.get(k, "").strip()
            if v.isdigit():
                cfg[k] = int(v)
        for k in ("https", "allow_wan", "public_listen"):
            if k in sec:
                cfg[k] = _nl_bool(sec.get(k))
        n = sec.get("node", "").strip()
        if n.isdigit():
            cfg["node"] = n
    return cfg, ""

def _nl_main_node(cfg: dict) -> str:
    if cfg.get("node"):
        return cfg["node"]
    try:
        section = ""
        for raw in _NL_DASH_CONF.read_text(errors="replace").splitlines():
            line = raw.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip().upper()
                continue
            if section == "CONFIG":
                m = re.match(r"^asl_node\s*=\s*(\d+)\s*$", line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return ""

def _nl_is_lan(text: str) -> bool:
    try:
        ip = ipaddress.ip_address(str(text).strip().strip("[]"))
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_private or ip.is_loopback or ip.is_link_local or (ip.version == 4 and ip in _NL_TAILNET)

def _nl_clean_ip(text: str) -> str:
    ip = str(text).strip().strip("[]")
    if ip.lower().startswith("::ffff:") and "." in ip:
        ip = ip[7:]
    return ip

def _nl_feeder_pids() -> list:
    pids = []
    for d in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            with open(d, "rb") as fh:
                cmd = fh.read()
                if b"nodelisten.py\0--feed\0" in cmd or b"nodetalker.py\0--feed\0" in cmd:
                    pids.append(int(d.split("/")[2]))
        except (OSError, ValueError):
            continue
    return pids

def _nl_health(port: int) -> "tuple[bool, str, str]":
    import http.client as _http
    import ssl as _ssl
    first_err = ""
    for scheme in ("https", "http"):
        try:
            if scheme == "https":
                ctx = _ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = _ssl.CERT_NONE
                conn = _http.HTTPSConnection("127.0.0.1", port, timeout=4, context=ctx)
            else:
                conn = _http.HTTPConnection("127.0.0.1", port, timeout=4)
            conn.request("GET", "/api/health")
            resp = conn.getresponse()
            body = resp.read(4096)
            conn.close()
            if resp.status != 200:
                if not first_err:
                    first_err = f"{scheme.upper()} {resp.status}"
                continue
            try:
                ver = str(json.loads(body.decode("utf-8", "replace")).get("version", ""))[:20]
            except (ValueError, AttributeError):
                ver = ""
            return True, scheme, ver
        except Exception as e:
            if not first_err:
                first_err = str(e)[:80] or type(e).__name__
    return False, "", first_err

def _nl_web_clients(port: int) -> "tuple[list, str]":
    out, prob = _cmd_or_problem(["ss", "-Htn", "state", "established", f"( sport = :{port} )"], 6)
    if prob:
        return [], prob
    by_ip: dict = {}
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) < 4:
            continue
        ip = _nl_clean_ip(parts[-1].rsplit(":", 1)[0])
        if not _NL_IP_RE.match(ip):
            continue
        by_ip[ip] = by_ip.get(ip, 0) + 1
    clients = [{"ip": ip, "conns": n, "lan": _nl_is_lan(ip), "local": ip in ("127.0.0.1", "::1")}
               for ip, n in sorted(by_ip.items())]
    return clients, ""

def _nl_lstats(node: str) -> "tuple[bool, list]":
    if not node:
        return False, []
    out, err = _run_with_stderr(["asterisk", "-rx", f"rpt lstats {node}"], timeout=6)
    if not out and err:
        return False, []
    return True, [ln.split()[0] for ln in out.splitlines() if ln.split() and ln.split()[0].isdigit()]

def _nodelisten_checks() -> dict:
    nl_service = _nl_service()
    installed = any(p.exists() for p in _NL_BINS) or get_service_installed(nl_service)
    if not installed:
        return {"ok": True, "installed": False, "status": "info", "badge": "NOT INSTALLED", "checks": [],
                "clients": []}
    cfg, cprob = _nl_read_conf()
    svc = get_service_state(nl_service)
    rows: list = []

    def row(key, enables, status, fix=None):
        rows.append({"key": key, "enables": enables, "status": status, "fix": fix})

    row(f"{nl_service}: {svc}", "Node Talker service running",
        "pass" if svc == "active" else "fail",
        None if svc == "active" else "Press Restart Node Talker below")
    if cprob == "missing":
        row(str(_nl_conf_path()), "Settings file", "info", "Not written yet -- Node Talker uses its defaults")
    elif cprob:
        row(str(_nl_conf_path()), "Settings file", "warn", f"{cprob} -- Node Talker uses its defaults")

    port, uport = cfg["port"], cfg["udp_port"]
    entries = _parse_ss_entries(_ss_tlnpu_fetch())

    def holders(proto, p):
        return [e for e in entries if e["proto"] == proto and e["port"] == str(p)]

    def who(e):
        cmd = _pid_cmdline(e["pid"])
        if "nodelisten" in cmd or "nodetalker" in cmd:
            return "nodetalker"
        return e["process"] or "?"

    def port_row(proto, p, enables, want, want_addr=None, needed=True, fix=None):
        hs = holders(proto, p)
        label = f"{proto.upper()} {p}"
        if not entries:
            row(label, enables, "info", "Can't check: ss gave no output")
            return False
        if not hs:
            row(f"{label}: not listening", enables, "fail" if needed else "info",
                (fix or "Restart Node Talker") if needed else None)
            return False
        names = sorted({who(e) for e in hs})
        addrs = sorted({e["addr"] for e in hs})
        if want not in names:
            row(f"{label}: held by {', '.join(names)}", enables, "fail",
                f"Port conflict -- stop {', '.join(names)} or change this port in Node Talker")
            return False
        if want_addr and not any(a in want_addr for a in addrs):
            row(f"{label}: {want} on {', '.join(addrs)}", enables, "warn",
                f"Expected on {want_addr[0]}")
            return True
        row(f"{label}: {want} on {', '.join(addrs)}", enables, "pass")
        return True

    web_up = port_row("tcp", port, "Web page and API", "nodetalker", ("0.0.0.0", "*", "[::]"))
    port_row("udp", uport, "Node audio in (from the Asterisk feed)", "nodetalker", ("127.0.0.1",))
    port_row("udp", _NL_TX_LISTEN, f"Push-to-talk audio back from node {_NL_TX_NODE}", "nodetalker",
             ("127.0.0.1",))

    scheme, version = "", ""
    if svc == "active" or web_up:
        ok, scheme, info = _nl_health(port)
        if ok:
            version = info
            row(f"{scheme}://127.0.0.1:{port}/api/health: OK" + (f" (v{info})" if info else ""),
                "Web page answers", "pass")
            if cfg["https"] and scheme != "https":
                row("HTTPS on, page served on plain HTTP", "HTTPS (needed for push-to-talk)", "warn",
                    "Node Talker couldn't load its certificate -- see its log")
            elif not cfg["https"]:
                row("HTTPS off", "HTTPS (needed for push-to-talk)", "info",
                    "Listening works; push-to-talk needs HTTPS on")
        else:
            row(f"127.0.0.1:{port}/api/health: no answer", "Web page answers", "fail",
                f"{info} -- restart Node Talker")

    main = _nl_main_node(cfg)
    rpt_text, rerr = read_path_file(_RPT_CONF)
    tx_on = False
    if rerr:
        row(str(_RPT_CONF), "Node audio hook", "warn", f"Can't read it: {rerr}")
    elif not main:
        row("node: (not set)", "Node Talker's node", "warn",
            "Set the node on the Node Talker page (Send its audio here)")
    else:
        nodes = _rpt_scan_full(rpt_text)["nodes"]
        outs = nodes.get(main, {}).get("outstreamcmd", "").replace(" ", "")
        if any(m in outs for m in _NL_FEED_MARKS):
            hp = outs.rsplit(",", 1)[-1]
            if hp == str(uport):
                row(f"[{main}] outstreamcmd -> Node Talker UDP {hp}", "Node audio hook in rpt.conf", "pass")
            else:
                row(f"[{main}] outstreamcmd -> UDP {hp}", "Node audio hook in rpt.conf", "fail",
                    f"Hook sends to UDP {hp} but Node Talker listens on {uport} -- "
                    f"turn Send its audio here off and on in Node Talker")
        elif outs:
            row(f"[{main}] outstreamcmd is another program's", "Node audio hook in rpt.conf", "warn",
                "Node Talker gets no audio while another outstreamcmd is set")
        else:
            row(f"[{main}] no outstreamcmd", "Node audio hook in rpt.conf", "warn",
                "Turn on Send its audio here on the Node Talker page")
        if any(m in outs for m in _NL_FEED_MARKS):
            fp = _nl_feeder_pids()
            ast = get_service_state("asterisk.service")
            row(f"Feeder: {len(fp)} running" if fp else "Feeder: not running", "Audio feed from Asterisk",
                "pass" if fp else ("warn" if ast == "active" else "info"),
                None if fp else ("Asterisk starts it after a restart of Asterisk" if ast == "active"
                                 else "Asterisk is not running"))
        tx_on = _NL_TX_NODE in nodes
        if tx_on:
            rx = nodes[_NL_TX_NODE].get("rxchannel", "").replace(" ", "")
            want_rx = f"USRP/127.0.0.1:{_NL_TX_LISTEN}:{_NL_TX_SEND}"
            row(f"[{_NL_TX_NODE}] rxchannel = {rx or '(none)'}", "Transmit node (push-to-talk)",
                "pass" if rx == want_rx else "warn", None if rx == want_rx else f"Expected {want_rx}")
            port_row("udp", _NL_TX_SEND, f"Push-to-talk audio to node {_NL_TX_NODE}", "asterisk",
                     None, True, "Asterisk opens it when node 1921 loads -- restart Asterisk")
            lok, links = _nl_lstats(main)
            if lok:
                up = _NL_TX_NODE in links
                row(f"Node {_NL_TX_NODE} " + ("linked to" if up else "not linked to") + f" {main}",
                    "Push-to-talk link", "pass" if up else "warn",
                    None if up else "Node Talker links it again within 20 s while it runs")
            else:
                row(f"rpt lstats {main}", "Push-to-talk link", "info", "Can't check: Asterisk did not answer")
        else:
            row(f"No [{_NL_TX_NODE}] stanza", "Transmit node (push-to-talk)", "info",
                "Push-to-talk is off (turn it on in Node Talker)")

    clients, clprob = _nl_web_clients(port)
    if clprob:
        row("Connected browsers", "Who is connected", "info", f"Can't check: {clprob}")
    wan = [c for c in clients if not c["lan"]]
    if cfg["allow_wan"]:
        row("allow_wan = on", "Internet access", "pass" if cfg["https"] else "warn",
            None if cfg["https"] else "Internet logins need HTTPS -- turn HTTPS on")
    else:
        row("allow_wan = off", "Internet access", "pass" if not wan else "warn",
            None if not wan else "Internet clients are connected but get 403")

    statuses = [r["status"] for r in rows]
    status = "fail" if "fail" in statuses else "warn" if "warn" in statuses else "pass"
    return {"ok": True, "installed": True, "status": status,
            "badge": {"pass": "OK", "warn": "WARN", "fail": "DOWN" if svc != "active" else "FAIL"}[status],
            "service": svc, "port": port, "scheme": scheme, "version": version, "main": main,
            "tx": tx_on, "checks": rows, "clients": clients}

def _route_nodelisten_get(h: Handler) -> None:
    h.send_json(_nodelisten_checks())

def _route_nodelisten_post(h: Handler, data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "root required"}); return
    action = str(data.get("action", "")).strip().lower()
    if action == "restart":
        try:
            r = subprocess.run(["systemctl", "restart", _nl_service()],
                               capture_output=True, text=True, timeout=30)
        except Exception as exc:
            h.send_json({"ok": False, "message": str(exc)}); return
        if r.returncode != 0:
            h.send_json({"ok": False, "message": (r.stderr or r.stdout or "restart failed").strip()}); return
        h.send_json({"ok": True, "message": "Node Talker restarted"})
        return
    if action == "disconnect":
        ip = _nl_clean_ip(data.get("ip", ""))
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            h.send_json({"ok": False, "message": "bad address"}, 400); return
        port = _nl_read_conf()[0]["port"]
        before, _ = _nl_web_clients(port)
        if not any(c["ip"] == ip for c in before):
            h.send_json({"ok": False, "message": f"{ip} is not connected"}); return
        dst = f"[{ip}]" if ":" in ip else ip
        out, prob = _cmd_or_problem(["ss", "-K", "-Htn", "state", "established",
                                     f"( sport = :{port} )", "dst", dst], 6)
        if prob:
            h.send_json({"ok": False, "message": prob}); return
        after, _ = _nl_web_clients(port)
        if any(c["ip"] == ip for c in after):
            h.send_json({"ok": False, "message": f"{ip} is still connected (this kernel may not "
                                                 f"allow closing sockets: ss -K)"}); return
        h.send_json({"ok": True, "message": f"Disconnected {ip}"})
        return
    if action == "unlink":
        main = _nl_main_node(_nl_read_conf()[0])
        if not main:
            h.send_json({"ok": False, "message": "Node Talker's node is not set"}); return
        lok, links = _nl_lstats(main)
        if lok and _NL_TX_NODE not in links:
            h.send_json({"ok": True, "message": f"Node {_NL_TX_NODE} is not linked"}); return
        out, err = _run_with_stderr(["asterisk", "-rx", f"rpt cmd {main} ilink 1 {_NL_TX_NODE}"], timeout=8)
        if err and not out:
            h.send_json({"ok": False, "message": err[:200]}); return
        h.send_json({"ok": True, "message": f"Node {_NL_TX_NODE} unlinked from {main}"})
        return
    h.send_json({"ok": False, "message": f"unknown action '{action}'"}, 400)

_SD_MANFID = {
    0x01: "Panasonic", 0x02: "Toshiba", 0x03: "SanDisk", 0x08: "Silicon Power",
    0x18: "Infineon",  0x1b: "Samsung", 0x1c: "Transcend", 0x1d: "ADATA",
    0x27: "Phison",    0x28: "Lexar",   0x31: "Silicon Power", 0x41: "Kingston",
    0x6f: "STMicro",   0x74: "Transcend", 0x76: "Patriot",  0x82: "Sony / Gobe",
    0x89: "Unknown(0x89)", 0x9c: "Angelbird / Hoodman", 0x9f: "Galaxy",
}

def _sd_hbytes(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "n/a"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"

def _sd_sysfs(base: Path, name: str) -> str:
    try:
        return (base / name).read_text().strip()
    except Exception as e:
        log.debug("_sd_sysfs: %s", e)
        return ""

def _sdh_device() -> dict:
    device = {"disk": "", "disk_path": "", "root_source": "", "root_part": ""}
    try:
        root_src = _run(["findmnt", "-n", "-o", "SOURCE", "/"]).strip()
        device["root_source"] = root_src
        disk = ""
        if root_src:
            device["root_part"] = root_src.rsplit("/", 1)[-1]

            pk = _run(["lsblk", "-no", "PKNAME", root_src]).strip().splitlines()
            disk = (pk[0].strip() if pk else "")
            if not disk and device["root_part"]:

                rp = device["root_part"]
                m = re.match(r"^(mmcblk\d+)p\d+$", rp) or re.match(r"^([a-z]+)\d+$", rp)

                disk = m.group(1) if m else rp
        device["disk"]      = disk
        device["disk_path"] = f"/dev/{disk}" if disk else ""
    except Exception as e:
        log.debug("_sdh_device: %s", e)
    return device

def _sdh_identity(disk: str) -> "tuple[dict, list]":
    warnings = []
    try:
        ident = {}
        if disk:
            base = Path(f"/sys/block/{disk}/device")
            for attr in ("cid", "csd", "name", "manfid", "oemid", "serial",
                         "date", "fwrev", "hwrev", "scr", "preferred_erase_size"):
                ident[attr] = _sd_sysfs(base, attr) or "n/a"

            mid_raw = ident.get("manfid", "")
            try:
                mid = int(mid_raw, 16)
                ident["manufacturer"] = _SD_MANFID.get(mid, f"Unknown ({mid_raw})")
            except (TypeError, ValueError):
                ident["manufacturer"] = "n/a"

            lt  = _sd_sysfs(base, "life_time")
            eol = _sd_sysfs(base, "pre_eol_info")
            ident["is_emmc"]      = bool(lt or eol)
            ident["life_time"]    = lt  or "n/a (SD card)"
            ident["pre_eol_info"] = eol or "n/a (SD card)"

            if eol in ("0x02", "0x2", "2"):
                warnings.append("eMMC pre-EOL: WARNING (>80% life consumed)")
            elif eol in ("0x03", "0x3", "3"):
                warnings.append("eMMC pre-EOL: URGENT (replace soon)")
        return ident, warnings
    except Exception as e:
        log.debug("_sdh_identity: %s", e)
        return {}, warnings

def _sdh_capacity(disk_path: str) -> "tuple[dict, list]":
    warnings = []
    try:
        cap = {}
        size_b = 0
        if disk_path:
            raw = _run(["blockdev", "--getsize64", disk_path]).strip()
            size_b = int(raw) if raw.isdigit() else 0
        cap["size_bytes"] = size_b
        cap["size_h"]     = _sd_hbytes(size_b) if size_b else "n/a"

        try:
            st       = os.statvfs("/")
            total_b  = st.f_blocks * st.f_frsize
            avail_b  = st.f_bavail * st.f_frsize
            used_b   = total_b - avail_b
            cap["fs_total_bytes"] = total_b
            cap["fs_used_bytes"]  = used_b
            cap["fs_avail_bytes"] = avail_b
            cap["fs_total_h"]     = _sd_hbytes(total_b)
            cap["fs_used_h"]      = _sd_hbytes(used_b)
            cap["fs_avail_h"]     = _sd_hbytes(avail_b)
            cap["fs_used_pct"]    = round(used_b / total_b * 100) if total_b else None

            tot_i = st.f_files
            free_i = st.f_ffree
            used_i = tot_i - free_i
            cap["inodes_used_pct"] = round(used_i / tot_i * 100) if tot_i else None
            if cap["fs_used_pct"] is not None and cap["fs_used_pct"] >= 90:
                warnings.append(f"Root filesystem {cap['fs_used_pct']}% full")
            if cap["inodes_used_pct"] is not None and cap["inodes_used_pct"] >= 90:
                warnings.append(f"Inodes {cap['inodes_used_pct']}% used")
        except Exception as e:
            log.debug("_sdh_capacity: %s", e)
        return cap, warnings
    except Exception as e:
        log.debug("_sdh_capacity: %s", e)
        return {}, warnings

def _sdh_filesystem(root_source: str) -> "tuple[dict, list]":
    warnings = []
    try:
        fs = {"available": False}
        if root_source:
            stdout, stderr = _run_with_stderr(["tune2fs", "-l", root_source], timeout=6)
            if stdout:
                fs["available"] = True
                def _grab(label):
                    m = re.search(rf"^{re.escape(label)}:\s*(.+)$", stdout, re.M)
                    return m.group(1).strip() if m else "n/a"
                fs["state"]            = _grab("Filesystem state")
                fs["mount_count"]      = _grab("Mount count")
                fs["max_mount_count"]  = _grab("Maximum mount count")
                fs["last_checked"]     = _grab("Last checked")
                fs["lifetime_writes"]  = _grab("Lifetime writes")
                fs["errors_behavior"]  = _grab("Errors behavior")
                if fs["state"] != "n/a" and "clean" not in fs["state"].lower():
                    warnings.append(f"Filesystem state: {fs['state']}")
            else:

                fs["error"] = (stderr or "tune2fs unavailable").splitlines()[0] \
                              if stderr else "tune2fs unavailable"
                if "permission" in fs["error"].lower() or "denied" in fs["error"].lower():
                    fs["error"] = "needs root to read superblock"
        return fs, warnings
    except Exception as e:
        log.debug("_sdh_filesystem: %s", e)
        return {"available": False}, warnings

def _sdh_io(disk: str) -> dict:
    try:
        io = {"available": False}
        if disk:
            raw = _sd_sysfs(Path(f"/sys/block/{disk}"), "stat")
            parts = raw.split()
            if len(parts) >= 7:

                sectors_read    = int(parts[2])
                sectors_written = int(parts[6])
                io["available"]       = True
                io["sectors_read"]    = sectors_read
                io["sectors_written"] = sectors_written
                io["bytes_read_h"]    = _sd_hbytes(sectors_read * 512)
                io["bytes_written_h"] = _sd_hbytes(sectors_written * 512)
        return io
    except Exception as e:
        log.debug("_sdh_io: %s", e)
        return {"available": False}

def _sdh_errors() -> "tuple[dict, list]":
    warnings = []
    try:
        err = {"available": False, "ro_mount": None, "kernel_lines": [], "count": 0}

        ro = get_sd_health()
        err["ro_mount"] = ro
        if ro == "ro":
            warnings.append("Root filesystem mounted READ-ONLY (corruption fallback)")

        dout, derr = _run_with_stderr(["dmesg", "-T"], timeout=6)
        if dout:
            pat = re.compile(r"(mmc|mmcblk|I/O error|EXT4-fs error|"
                             r"remounting filesystem read-only|"
                             r"failed to|timed out)", re.I)
            hits = [ln for ln in dout.splitlines() if pat.search(ln)]
            err["available"]    = True
            err["count"]        = len(hits)
            err["kernel_lines"] = hits[-40:]

            hard = re.compile(r"(I/O error|EXT4-fs error|read-only|"
                              r"timed out|CRC|failed to)", re.I)
            if any(hard.search(ln) for ln in hits):
                warnings.append("Kernel log shows storage I/O errors")
        elif derr and ("permission" in derr.lower() or "denied" in derr.lower()):
            err["note"] = "dmesg needs root (dmesg_restrict)"
        return err, warnings
    except Exception as e:
        log.debug("_sdh_errors: %s", e)
        return {"available": False, "ro_mount": None,
                "kernel_lines": [], "count": 0}, warnings

def get_sdcard_health() -> dict:
    device = _sdh_device()
    identity,   w1 = _sdh_identity(device["disk"])
    capacity,   w2 = _sdh_capacity(device["disk_path"])
    filesystem, w3 = _sdh_filesystem(device["root_source"])
    io             = _sdh_io(device["disk"])
    errors,     w4 = _sdh_errors()

    return {
        "ok":         True,
        "device":     device,
        "identity":   identity,
        "capacity":   capacity,
        "filesystem": filesystem,
        "io":         io,
        "errors":     errors,
        "warnings":   w1 + w2 + w3 + w4,
    }

_SD_TESTS = ("fsck",)

_sd_test_lock = threading.Lock()

_sd_test_job = {
    "status":     "idle",
    "test":       "",
    "target":     "",
    "pct":        None,
    "progress":   "",
    "lines":      [],
    "returncode": None,
    "message":    "",
    "started_at": 0.0,
}

_sd_test_proc = None

_sd_test_cancel = False

def _sd_resolve_targets() -> "tuple[str, str]":
    try:
        root_src = _run(["findmnt", "-n", "-o", "SOURCE", "/"]).strip()
        disk = ""
        if root_src:
            pk = _run(["lsblk", "-no", "PKNAME", root_src]).strip().splitlines()
            disk = pk[0].strip() if pk else ""
        disk_path = f"/dev/{disk}" if disk else root_src
        return root_src, disk_path
    except Exception as e:
        log.debug("_sd_resolve_targets: %s", e)
        return "", ""

def sd_test_status() -> dict:
    with _sd_test_lock:
        j = dict(_sd_test_job)
    j["lines"] = j["lines"][-200:]
    if j["started_at"]:
        j["elapsed"] = round(time.monotonic() - j["started_at"])
    else:
        j["elapsed"] = 0
    return {"ok": True, **j}

_SD_PROGRESS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*done", re.I)

def _sd_test_record(line: str) -> None:
    if not line:
        return
    m = _SD_PROGRESS_RE.search(line)
    with _sd_test_lock:
        if m:
            _sd_test_job["progress"] = line
            try:
                _sd_test_job["pct"] = round(float(m.group(1)))
            except ValueError:
                pass
        else:
            _sd_test_job["lines"].append(line)
            if len(_sd_test_job["lines"]) > 500:
                _sd_test_job["lines"] = _sd_test_job["lines"][-500:]

def _sd_test_worker(test: str, target: str) -> None:
    global _sd_test_proc
    if test == "fsck":
        cmd = ["fsck", "-n", target]
    else:

        return

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, bufsize=0)
    except Exception as exc:
        with _sd_test_lock:
            _sd_test_job.update(status="error", message=f"spawn failed: {exc}")
        return

    with _sd_test_lock:
        _sd_test_proc = proc
    _sd_test_record(f"$ {' '.join(cmd)}")

    try:
        for line in _iter_proc_lines(proc.stdout):
            _sd_test_record(line.rstrip())
    except Exception as exc:
        _sd_test_record(f"[read error: {exc}]")

    try:
        rc = proc.wait(timeout=10)
    except Exception as e:
        log.debug("_sd_test_worker: %s", e)
        rc = None

    with _sd_test_lock:
        cancelled = _sd_test_cancel
        _sd_test_proc = None
        _sd_test_job["returncode"] = rc
        if cancelled:
            _sd_test_job["status"]  = "cancelled"
            _sd_test_job["message"] = "Cancelled by user"
        elif test == "fsck":

            if rc == 0:
                _sd_test_job["status"]  = "done"
                _sd_test_job["message"] = "Clean (advisory — root is mounted)"
            elif rc in (1, 4):
                _sd_test_job["status"]  = "done"
                _sd_test_job["message"] = ("Filesystem errors reported — advisory only on "
                                           "a mounted root; recheck offline to confirm")
            else:
                _sd_test_job["status"]  = "done"
                _sd_test_job["message"] = f"fsck exited {rc}"

def start_sd_test(test: str) -> dict:
    global _sd_test_cancel
    if test not in _SD_TESTS:
        return {"ok": False, "message": f"Unknown test: {test!r}"}
    if os.geteuid() != 0:
        return {"ok": False, "message": "Integrity tests require running sysmon as root"}
    with _sd_test_lock:
        if _sd_test_job["status"] == "running":
            return {"ok": False, "message": "A test is already running"}

    root_src, _disk = _sd_resolve_targets()
    target = root_src
    if not target or not re.match(r"^/dev/[\w/\-]+$", target):
        return {"ok": False, "message": f"Could not resolve a safe target device ({target!r})"}

    with _sd_test_lock:
        _sd_test_cancel = False
        _sd_test_job.update(status="running", test=test, target=target, pct=None,
                            progress="", lines=[], returncode=None, message="",
                            started_at=time.monotonic())
    threading.Thread(target=_sd_test_worker, args=(test, target),
                     daemon=True, name=f"sd-test-{test}").start()
    _log(f"sd_test: started {test} on {target}")
    return {"ok": True, "message": f"{test} started on {target}", "target": target}

def cancel_sd_test() -> dict:
    global _sd_test_cancel
    with _sd_test_lock:
        if _sd_test_job["status"] != "running":
            return {"ok": False, "message": "No test running"}
        _sd_test_cancel = True
        proc = _sd_test_proc
    try:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except Exception as e:
                log.debug("cancel_sd_test: %s", e)
                proc.kill()
    except Exception as exc:
        return {"ok": False, "message": f"Cancel error: {exc}"}
    _log("sd_test: cancel requested")
    return {"ok": True, "message": "Cancelling…"}

def _route_sdcard_get(h: Handler) -> None:
    h.send_json(get_sdcard_health())

def _route_sdcard_test_get(h: Handler) -> None:
    h.send_json(sd_test_status())

def _route_sdcard_test_post(h: Handler, data: dict) -> None:
    action = (data.get("action") or "").strip()
    if action == "start":
        test = (data.get("test") or "").strip()
        h.send_json(start_sd_test(test))
    elif action == "cancel":
        h.send_json(cancel_sd_test())
    else:
        h.send_json({"ok": False, "message": f"Unknown action: {action!r}"}, 400)

def serialize_pinned_services(pinned: list) -> str:
    lines = []
    for entry in pinned:
        if "group" in entry:
            lines.append(f"__GROUP__:{entry['group']}")
        else:
            lines.append(
                f"{entry['unit']} | {entry.get('desc','')} "
                f"| {entry.get('config','-')} "
                f"| {entry.get('port','-')} "
                f"| {entry.get('proto','-')}"
            )
    return "\n".join(lines)

def pin_service(unit: str, group: str, desc: str = "",
                config: str = "-", port: str = "-", proto: str = "-") -> bool:
    if any(e.get("unit") == unit for e in _pinned):
        return False
    if not _validate_unit(unit):
        return False

    new_entry = {"unit": unit, "desc": desc, "config": config,
                 "port": port, "proto": proto}
    result    = list(_pinned)
    in_group  = False
    insert_at = len(result)

    for i, e in enumerate(result):
        if "group" in e and e["group"] == group:
            in_group = True
            continue
        if in_group and "group" in e:
            insert_at = i
            break

    if not in_group:
        result.append({"group": group})
        result.append(new_entry)
    else:
        result.insert(insert_at, new_entry)

    ok = save_config({"services.pinned": serialize_pinned_services(result)})
    if ok:
        reload_config()
    return ok

def unpin_service(unit: str) -> bool:
    if not any(e.get("unit") == unit for e in _pinned):
        return False

    new_list = [e for e in _pinned if e.get("unit") != unit]

    pruned = []
    for i, e in enumerate(new_list):
        if "group" in e:
            found_svc = False
            for r in new_list[i + 1:]:
                if "group" in r:
                    break
                if "unit" in r:
                    found_svc = True
                    break
            if found_svc:
                pruned.append(e)
        else:
            pruned.append(e)

    ok = save_config({"services.pinned": serialize_pinned_services(pruned)})
    if ok:
        reload_config()
    return ok

_ALL_TABS = ("overview", "services", "ports", "journal",
             "asldvs", "reg", "phone", "tune", "hardware", "dvsm", "stfu", "m17", "sdcard",
             "edit")

_LOCKED_TABS = ("overview", "edit")

def _sanitize_enabled_tabs(raw) -> list:
    if isinstance(raw, str):
        items = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        items = raw
    else:
        items = []
    wanted = {str(t).strip().lower() for t in items}
    if "security" in wanted:
        wanted.add("reg")
    wanted.update(_LOCKED_TABS)
    return [t for t in _ALL_TABS if t in wanted]

def _get_enabled_tabs() -> list:
    raw = _cfg.get("ui", "enabled_tabs",
                   fallback=_DEFAULT_CONFIG["ui"]["enabled_tabs"])
    return _sanitize_enabled_tabs(raw)

def validate_config(updates: dict) -> list:
    errors = []
    if "identity.callsign" in updates:
        cs = str(updates["identity.callsign"]).strip().upper()
        if not re.fullmatch(r"[A-Z0-9 /.\-]{1,9}", cs):
            errors.append(f"callsign '{cs}' invalid — use A-Z 0-9 - / . (max 9 chars)")
    if "identity.node" in updates:
        node = str(updates["identity.node"]).strip()
        if not re.fullmatch(r"\d{1,7}", node):
            errors.append(f"node '{node}' invalid — numeric only, 1-7 digits")
    for key in ("server.port",):
        if key in updates:
            try:
                p = int(updates[key])
                if not (1024 <= p <= 65535):
                    raise ValueError
            except (ValueError, TypeError):
                errors.append(f"{key} must be an integer 1024–65535")
    if "server.host" in updates:
        if not str(updates["server.host"]).strip():
            errors.append("server.host must not be empty")
    return errors

def reload_config() -> None:
    global _cfg, _pinned
    _cfg    = load_config()
    _pinned = parse_pinned_services(_get_pinned_raw())

_APPCONF_FILES: "list[Path]" = [
    Path("/etc/asl_dvs/asl_dvs.conf"),
    Path("/etc/sysmon/sysmon.conf"),
]

def _route_config_get(h: Handler) -> None:
    h.send_json({
        "ok":           True,
        "server": {
            "port": _cfg.get("server",   "port", fallback=str(DEFAULT_PORT)),
            "host": _cfg.get("server",   "host", fallback="0.0.0.0"),
        },
        "identity": {
            "callsign": _cfg.get("identity", "callsign", fallback=""),
            "node":     _cfg.get("identity", "node",     fallback=""),
            "label":    _cfg.get("identity", "label",    fallback=""),
        },
        "thresholds": {
            "cpu_warn_pct": _cfg.get("thresholds", "cpu_warn_pct", fallback="50"),
            "rss_warn_mb":  _cfg.get("thresholds", "rss_warn_mb",  fallback="200"),
            "nr_warn":      _cfg.get("thresholds", "nr_warn",      fallback="3"),
            "nr_crit":      _cfg.get("thresholds", "nr_crit",      fallback="10"),
        },
        "services": {
            "pinned": _get_pinned_raw(),
        },
        "asldvs": {
            "hidden_files": _cfg.get("asldvs", "hidden_files", fallback=""),
        },
        "ui": {

            "enabled_tabs": _get_enabled_tabs(),
        },
    })

def _route_pinned_get(h: Handler) -> None:
    groups       = [e["group"] for e in _pinned if "group" in e]
    pinned_units = [e["unit"]  for e in _pinned if "unit"  in e]
    h.send_json({"ok": True, "groups": groups, "pinned_units": pinned_units})

def _route_pinned_post(h: Handler, data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "root required"}); return

    action = str(data.get("action", "")).strip().lower()
    unit   = str(data.get("unit",   "")).strip()

    if not _validate_unit(unit):
        h.send_json({"ok": False, "message": f"Invalid unit: {unit!r}"}, 400)
        return

    if action == "pin":
        group  = str(data.get("group",  "Services")).strip() or "Services"
        desc   = str(data.get("desc",   "")).strip()
        config = str(data.get("config", "-")).strip() or "-"
        port   = str(data.get("port",   "-")).strip() or "-"
        proto  = str(data.get("proto",  "-")).strip() or "-"
        if any(e.get("unit") == unit for e in _pinned):
            h.send_json({"ok": False, "message": f"{unit} is already pinned"})
            return
        ok = pin_service(unit, group, desc, config, port, proto)
        msg = f"Pinned {unit} to '{group}'" if ok else "Save failed"
        _log(msg)
        h.send_json({"ok": ok, "message": msg})

    elif action == "unpin":
        if not any(e.get("unit") == unit for e in _pinned):
            h.send_json({"ok": False, "message": f"{unit} is not pinned"})
            return
        ok = unpin_service(unit)
        msg = f"Unpinned {unit}" if ok else "Save failed"
        _log(msg)
        h.send_json({"ok": ok, "message": msg})

    else:
        h.send_json({"ok": False, "message": f"Unknown action: {action!r}"}, 400)

def _route_config_post(h: Handler, data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "root required"}); return

    errors = validate_config(data)
    if errors:
        h.send_json({"ok": False, "errors": errors}, 400)
        return

    if "ui.enabled_tabs" in data:
        data["ui.enabled_tabs"] = ",".join(_sanitize_enabled_tabs(data["ui.enabled_tabs"]))

    old_port = _cfg.get("server", "port", fallback=str(DEFAULT_PORT))
    old_host = _cfg.get("server", "host", fallback="0.0.0.0")

    ok = save_config(data)
    if not ok:
        h.send_json({"ok": False, "message": "Disk write failed — check log"}); return

    new_port = _cfg.get("server", "port", fallback=str(DEFAULT_PORT))
    new_host = _cfg.get("server", "host", fallback="0.0.0.0")
    if new_port != old_port or new_host != old_host:
        _update_state(needs_restart=True)
        _log("WARN — server address changed; restart required", stderr=True)

    reload_config()
    h.send_json({"ok": True, "message": "Config saved"})

_PATHFILE_APPCONF = {
    "files":    _APPCONF_FILES,
    "readonly": None,
    "descs":    {"asl_dvs.conf": "ASL-DVS Dashboard", "sysmon.conf": "SysMon"},
}

def _route_appconf_list(h: Handler) -> None:
    _pathfile_list(h, _PATHFILE_APPCONF)

def _route_appconf_get(h: Handler) -> None:
    _pathfile_get(h, _PATHFILE_APPCONF)

def _route_appconf_post(h: Handler, data: dict) -> None:
    _pathfile_post(h, data, _PATHFILE_APPCONF)

def _get_hidden_files() -> set:
    raw = _cfg.get("asldvs", "hidden_files", fallback="")
    return {f.strip() for f in raw.split(",") if f.strip()}

_PORT_LINE_RE = re.compile(
    r'^\s*([A-Za-z_][\w]*)\s*[=:]\s*(\d{1,5})\s*(?:[#;].*)?$'
)

_SECTION_RE = re.compile(r'^\s*\[([^\]]+)\]\s*$')

def extract_port_lines(text: str) -> list:
    results = []
    section = ""
    for line in text.splitlines():

        sm = _SECTION_RE.match(line)
        if sm:
            section = sm.group(1)
            continue
        m = _PORT_LINE_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if "port" not in key.lower():
            continue
        try:
            port = int(val)
        except ValueError:
            continue
        if not (1024 <= port <= 65535):
            continue
        results.append({"section": section, "line": line.strip()})
        if len(results) >= 20:
            break
    return results

def _file_by_label(files, label: str) -> "Path | None":
    first_match = None
    for p in files:
        if p.name == label:
            if first_match is None:
                first_match = p
            if p.is_file():
                return p
    return first_match

def _pathfile_list(h: Handler, fam: dict) -> None:
    if "descs" in fam:
        h.send_json({"ok": True, "files": [{
            "label":    p.name,
            "path":     str(p),
            "exists":   p.is_file(),
            "writable": os.geteuid() == 0,
            "desc":     fam["descs"].get(p.name, p.name),
        } for p in fam["files"]]})
        return

    qs          = parse_qs(urlparse(h.path).query)
    include_all = qs.get("all", [""])[0] == "1"
    hidden_set  = _get_hidden_files()
    ro_set      = fam["readonly"]

    best: "dict[str, Path]" = {}
    for p in fam["files"]:
        if p.name not in best:
            best[p.name] = p
        if p.is_file() and not best[p.name].is_file():
            best[p.name] = p

    files = []
    for label, p in best.items():
        is_hidden   = label in hidden_set
        file_exists = p.is_file()
        if not include_all and is_hidden:
            continue
        content, _ = read_path_file(p) if file_exists else ("", None)
        parser     = fam["parsers"].get(label)
        entry = {
            "label":    label,
            "path":     str(p),
            "exists":   file_exists,
            "writable": os.geteuid() == 0,
            "hidden":   is_hidden,
        }
        if ro_set is not None:
            entry["readonly"] = label in ro_set
        entry["checks"]     = parser(content) if (parser and file_exists) else []
        entry["port_lines"] = extract_port_lines(content)
        files.append(entry)

    h.send_json({"ok": True, "files": files})

def _pathfile_get(h: Handler, fam: dict) -> None:
    qs    = parse_qs(urlparse(h.path).query)
    label = qs.get("label", [""])[0].strip()

    p = _file_by_label(fam["files"], label)
    if p is None:
        h.send_json({"ok": False, "message": f"Unknown file: {label!r}"}, 400)
        return

    content, err = read_path_file(p)
    exists = True
    if err and not p.is_file():
        content, exists = "", False
    elif err:
        h.send_json({"ok": False, "message": err}, 500)
        return

    reply = {
        "ok":       True,
        "label":    label,
        "path":     str(p),
        "content":  content,
        "exists":   exists,
        "writable": os.geteuid() == 0,
    }
    if fam["readonly"] is not None:
        reply["readonly"] = label in fam["readonly"]
    h.send_json(reply)

def _pathfile_post(h: Handler, data: dict, fam: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "root required"}); return

    label   = str(data.get("label",   "")).strip()
    content = str(data.get("content", ""))

    if fam["readonly"] and label in fam["readonly"]:
        h.send_json({"ok": False,
                     "message": f"{label!r} {fam['ro_msg']}"}, 403)
        return

    p = _file_by_label(fam["files"], label)
    if p is None:
        h.send_json({"ok": False, "message": f"Unknown file: {label!r}"}, 400)
        return

    ok, msg = write_path_file(p, content)
    _log(msg, stderr=not ok)
    h.send_json({"ok": ok, "message": msg, "path": str(p)},
                200 if ok else 500)

_NET_JOB_LINE_CAP    = 500

_NET_INSTALL_TIMEOUT = 900

_net_proc = None

def _net_job_record(line: str) -> None:
    if line is None:
        return
    with _net_job_lock:
        _net_job["lines"].append(line)
        if len(_net_job["lines"]) > _NET_JOB_LINE_CAP:
            _net_job["lines"] = _net_job["lines"][-_NET_JOB_LINE_CAP:]

def _net_job_worker(action: str, cmd: list, timeout: int, env: "dict | None") -> None:
    global _net_proc
    _log(f"net job start: {action} :: {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=0, env=env,
        )
    except Exception as exc:
        with _net_job_lock:
            _net_job.update(status="done", success=False, returncode=None,
                            finished_at=time.monotonic())
            _net_job["lines"].append(f"failed to start: {exc}")
        _log(f"net job spawn failed: {action}: {exc}", stderr=True)
        return

    with _net_job_lock:
        _net_proc = proc
    _net_job_record(f"$ {' '.join(cmd)}")

    timed_out = {"v": False}
    def _kill():
        timed_out["v"] = True
        try:
            proc.kill()
        except Exception:
            pass
    timer = threading.Timer(timeout, _kill)
    timer.daemon = True
    timer.start()

    try:
        for line in _iter_proc_lines(proc.stdout):
            _net_job_record(line)
    except Exception as exc:
        _net_job_record(f"(read error: {exc})")
    finally:
        proc.wait()
        timer.cancel()

    rc = proc.returncode
    with _net_job_lock:
        if timed_out["v"]:
            _net_job["lines"].append(f"--- timed out after {timeout}s, killed ---")
            _net_job["success"] = False
            _net_job["returncode"] = None
        else:
            _net_job["success"] = (rc == 0)
            _net_job["returncode"] = rc
        _net_job["status"] = "done"
        _net_job["finished_at"] = time.monotonic()
        _net_proc = None
    _log(f"net job {'ok' if (not timed_out['v'] and rc == 0) else 'fail'} "
         f"(exit {rc}): {action}")

def _net_start_job(action: str, label: str, cmd: list, timeout: int,
                   env: "dict | None" = None) -> dict:
    with _net_job_lock:
        if _net_job["status"] == "running":
            return {"ok": False, "message": "A network job is already running"}
        _net_job.update(status="running", action=action, label=label,
                        cmd=" ".join(cmd), lines=[], success=None,
                        returncode=None, started_at=time.monotonic(),
                        finished_at=0.0,
                        finished_key=f"{action}-{time.monotonic():.3f}")
    threading.Thread(target=_net_job_worker, args=(action, cmd, timeout, env),
                     daemon=True).start()
    return {"ok": True, "message": label, "action": action}

def _net_apt_env() -> dict:
    env = dict(os.environ)
    env["DEBIAN_FRONTEND"] = "noninteractive"
    return env

def _ph_signin_choice() -> "tuple[str, str]":
    try:
        doc = json.loads(_PH_PHONE_JSON.read_text())
    except (OSError, ValueError):
        return "all", ""
    if not isinstance(doc, dict) or "signin_mode" not in doc:
        return "all", ""
    if doc.get("signin_mode") == "all":
        return "all", ""
    nets = [n for n in doc.get("networks") or [] if isinstance(n, dict)]
    act = next((n for n in nets if n.get("id") == doc.get("active")), None)
    if act is not None:
        return "picked", (act.get("id", "") if act.get("register") else "")
    first = next((n for n in nets if n.get("register")), None)
    return "picked", (first.get("id", "") if first else "")

def _ph_mask(text: str) -> str:
    text = re.sub(r'("\$\{PIN\}"\s*=\s*)"[^"]*"', r'\1"****"', text)
    text = re.sub(r"(register\s*=>\s*[^:\s]+:)[^@\s]+(@)", r"\1****\2", text, flags=re.I)
    text = re.sub(r"(?i)\b(secret|password)\s*=\s*\S+", r"\1=****", text)
    if re.search(r"(?i)\bPIN\b", text):
        text = re.sub(r"\d{4,}", "****", text)
    return text

def _ph_load_ctx(ast_dir=None) -> dict:
    ctx = {"dir": Path(ast_dir or _AST_DIR), "conf": {}, "files": [], "missing": [], "errors": []}
    for top in ("rpt.conf", "extensions.conf", "iax.conf", "pjsip.conf"):
        ctx["conf"][top] = []
        _ph_parse_file(ctx, top, top, {"sec": None}, 0, False)
    ctx["dialplan"] = _ph_build_dialplan(ctx["conf"]["extensions.conf"])
    ctx["dial_targets"] = _ph_dial_targets(ctx["dialplan"])
    ctx["dash"] = _ph_dash_info()
    return ctx

def _ph_last(sec_list: list) -> dict:
    out: dict = {}
    for s in sec_list:
        for k, v, *_ in s["kv"]:
            out[k.strip().lower()] = v
    return out

_PH_APP_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*(?:\((.*)\))?\s*$", re.S)

def _ph_build_dialplan(secs: list) -> dict:
    plan: dict = {}
    for s in secs:
        if not s["name"] or s["name"] in ("general", "globals") or s["is_template"]:
            continue
        cur = None
        for k, v, n, managed in s["kv"]:
            kl = k.strip().lower()
            if kl not in ("exten", "same"):
                continue
            parts = [p.strip() for p in v.split(",", 2 if kl == "exten" else 1)]
            if kl == "exten":
                if len(parts) < 3:
                    continue
                cur = {"pattern": parts[0], "steps": [], "managed": managed, "file": s["file"]}
                plan.setdefault(s["name"], []).append(cur)
                prio, rest = parts[1], parts[2]
            else:
                if cur is None or len(parts) < 2:
                    continue
                prio, rest = parts[0], parts[1]
            lm = re.search(r"\(([^)]*)\)", prio)
            am = _PH_APP_RE.match(rest)
            cur["steps"].append({"label": lm.group(1) if lm else "",
                                 "app": (am.group(1) if am else rest.split("(")[0]).strip(),
                                 "args": am.group(2) or "" if am else "", "raw": rest})
    return plan

def _ph_dial_targets(plan: dict) -> set:
    out = set()
    for exts in plan.values():
        for e in exts:
            for st in e["steps"]:
                if st["app"].lower() != "dial":
                    continue
                for tech, target in re.findall(r"\b(IAX2|PJSIP)/([^,)\s]+)", st["args"]):
                    seg = target.split("/")[0]
                    if tech == "IAX2":
                        out.add(("iax2", seg))
                    else:
                        out.add(("pjsip", seg.split("@")[-1]))
    return out

def _ph_parse_autopatch(value: str) -> dict:
    parts = [p.strip() for p in value.split(",")]
    opts = {}
    for p in parts[1:]:
        k, eq, v = p.partition("=")
        if eq:
            opts[k.strip().lower()] = v.strip()
    return opts

def _ph_parse_iax_reg(v: str) -> dict:
    v = v.split("/")[0].strip()
    if "@" not in v:
        return None
    left, host = v.rsplit("@", 1)
    user, colon, pw = left.partition(":")
    hname, _c, port = host.partition(":")
    if not user or not hname:
        return None
    return {"user": user, "host": hname, "port": port, "has_password": bool(colon and pw)}

def _ph_uri_host(uri: str) -> "tuple[str, str]":
    u = re.sub(r"^sips?:", "", uri.strip())
    u = u.split("@")[-1].split(";")[0]
    h, _c, p = u.partition(":")
    return h, p

def _ph_source(name: str, managed: bool) -> str:
    return "dashboard" if (managed or name.startswith("dvs")) else "hand-made"

def _ph_ast_running() -> bool:
    return _run(["systemctl", "is-active", "asterisk"], timeout=3).strip() == "active"

def _ph_cli(cmd: str, timeout: int = 6) -> str:
    return _run(["asterisk", "-rx", cmd], timeout=timeout)

def _ph_module_running(out: str, module: str) -> bool:
    return any(l.strip().startswith(module) and re.search(r"(?<!Not )\bRunning\b", l) for l in out.splitlines())

def _ph_pjsip_typed(ctx: dict) -> dict:
    typed: dict = {}
    for s in ctx["conf"]["pjsip.conf"]:
        if s["name"] and not s["is_template"]:
            typed.setdefault(_ph_last([s]).get("type", "").lower(), []).append(s)
    return typed

def _ph_transport_for(typed: dict, name: str) -> "dict | None":
    ts = typed.get("transport", [])
    if name:
        t = next((t for t in ts if t["name"] == name), None)
        return t
    return next((t for t in ts if _ph_last([t]).get("protocol", "udp").lower() == "udp"), None)

def _ph_bind_port(tr: "dict | None") -> int:
    bind = _ph_last([tr]).get("bind", "") if tr else ""
    m = re.search(r":(\d{1,5})$", bind.strip())
    return int(m.group(1)) if m else 5060

def _ph_sip_port(ctx: dict) -> int:
    return _ph_bind_port(_ph_transport_for(_ph_pjsip_typed(ctx), ""))

def _ph_fw_udp_rules() -> dict:
    backend = get_firewall_backend()
    res = {"backend": backend, "filtering": False, "allowed": [], "why": ""}
    def add(spec: str):
        m = re.match(r"^(\d{1,5})(?:[-:](\d{1,5}))?$", spec)
        if m:
            res["allowed"].append((int(m.group(1)), int(m.group(2) or m.group(1))))
    if backend == "firewalld":
        res["filtering"] = True
        for zone in _firewalld_active_zones():
            raw = _run(["firewall-cmd", f"--zone={zone}", "--list-all"], timeout=6)
            if _firewalld_parse_list_all(raw).get("target") == "ACCEPT":
                res.update(filtering=False, why=f"firewalld zone {zone} lets everything in")
                return res
            for r in _firewalld_zone_rules(zone, raw):
                p, _s, proto = r.get("to", "").partition("/")
                if r.get("action") == "ALLOW" and proto == "udp":
                    add(p)
    elif backend == "ufw":
        if get_ufw_status() != "active":
            res["why"] = "ufw is installed but not active"
            return res
        verbose = _run(["ufw", "status", "verbose"], timeout=6)
        if re.search(r"Default:\s*allow\s*\(incoming\)", verbose, re.I):
            res["why"] = "ufw lets all incoming traffic in by default"
            return res
        res["filtering"] = True
        for r in get_ufw_rules():
            if r.get("action") not in ("ALLOW", "LIMIT"):
                continue
            to = r.get("to", "").split()[0] if r.get("to") else ""
            p, _s, proto = to.partition("/")
            if proto in ("", "udp"):
                add(p)
    elif backend == "nft":
        raw = _run(["nft", "list", "ruleset"], timeout=6)
        chains = [b for b in re.findall(r"^\tchain\s+\S+\s*\{\n(.*?)^\t\}", raw, re.M | re.S)
                  if "hook input" in b]
        if not chains:
            res["why"] = "no nftables input chain"
            return res
        if all("policy accept" in b and not re.search(r"\b(drop|reject)\b", b.split("policy accept", 1)[1])
               for b in chains):
            res["why"] = "nftables input chains accept everything"
            return res
        res.update(filtering=None, why="nftables rules sysmon can't read port by port")
    elif backend == "iptables":
        raw = _run(["iptables", "-S", "INPUT"], timeout=6)
        if "-P INPUT ACCEPT" in raw and not re.search(r"-j\s+(DROP|REJECT)", raw):
            res["why"] = "iptables INPUT accepts everything"
            return res
        res.update(filtering=None, why="iptables rules sysmon can't read port by port")
    else:
        res["why"] = "no firewall on the Pi"
    return res

def _ph_fw_cover(rules: dict, lo: int, hi: int) -> dict:
    if rules["filtering"] is False:
        return {"state": "nofilter", "gaps": [], "why": rules["why"]}
    if rules["filtering"] is None:
        return {"state": "unknown", "gaps": [], "why": rules["why"]}
    gaps, cur = [], lo
    for a, b in sorted(rules["allowed"]):
        if b < cur:
            continue
        if a > hi:
            break
        if a > cur:
            gaps.append((cur, min(a - 1, hi)))
        cur = max(cur, b + 1)
        if cur > hi:
            break
    if cur <= hi:
        gaps.append((cur, hi))
    state = "open" if not gaps else ("closed" if gaps == [(lo, hi)] else "partial")
    return {"state": state, "gaps": gaps, "why": rules["backend"]}

def _ph_pat_match(pat: str, num: str) -> bool:
    if not pat.startswith("_"):
        return pat == num
    rx, i = "", 1
    while i < len(pat):
        c = pat[i]
        if c in "Xx":
            rx += "[0-9]"
        elif c in "Zz":
            rx += "[1-9]"
        elif c in "Nn":
            rx += "[2-9]"
        elif c == ".":
            rx += ".+"
        elif c == "!":
            rx += ".*"
        elif c == "[":
            j = pat.find("]", i)
            if j < 0:
                return False
            rx += "[" + re.escape(pat[i + 1:j]).replace("\\-", "-") + "]"
            i = j
        else:
            rx += re.escape(c)
        i += 1
    try:
        return re.fullmatch(rx, num) is not None
    except re.error:
        return False

_RT_HIST_RE = re.compile(r"^\s*(\d+)\s+(\d+)\s+.*?(<==|==>)\s+(\S+)\s+(.*)$")

def _rt_rtp_range() -> "tuple[int, int]":
    lo, hi = 10000, 20000
    try:
        txt = Path("/etc/asterisk/rtp.conf").read_text(errors="replace")
        a = re.search(r"(?m)^\s*rtpstart\s*=\s*(\d+)", txt)
        b = re.search(r"(?m)^\s*rtpend\s*=\s*(\d+)", txt)
        if a and b and 1024 <= int(a.group(1)) <= int(b.group(1)) <= 65535:
            lo, hi = int(a.group(1)), int(b.group(1))
    except OSError:
        pass
    return lo, hi

def _rt_history_rows() -> list:
    rows = []
    for line in _ph_cli("pjsip show history", timeout=6).splitlines():
        m = _RT_HIST_RE.match(line)
        if m:
            rows.append({"n": m.group(1), "ts": int(m.group(2)), "dir": "in" if m.group(3) == "<==" else "out",
                         "addr": m.group(4), "msg": m.group(5).strip()})
    return rows

_STFU_BINARY        = Path("/opt/STFU/STFU")

_STFU_DVS_CANDIDATES = [
    Path("/opt/MMDVM_Bridge/DVSwitch.ini"),
    Path("/etc/MMDVM_Bridge/DVSwitch.ini"),
    Path("/etc/dvswitch/DVSwitch.ini"),
]

def _stfu_check_subscriber_file(sub_file: str) -> "tuple[str, bool, int]":
    sub_ok   = False
    sub_rows = -1
    if sub_file:
        sub_path = Path(sub_file)
        sub_ok   = sub_path.exists() and sub_path.is_file()
        if sub_ok:
            try:

                with open(sub_path, "rb") as fh:
                    sub_rows = sum(1 for _ in fh)
            except Exception as e:
                log.debug("_stfu_check_subscriber_file: %s", e)
                sub_rows = -1
    elif _STFU_BINARY.parent.joinpath("subscriber_ids.csv").exists():

        default_sub = _STFU_BINARY.parent / "subscriber_ids.csv"
        sub_file    = str(default_sub)
        sub_ok      = True
        try:
            with open(default_sub, "rb") as fh:
                sub_rows = sum(1 for _ in fh)
        except Exception as e:
            log.debug("_stfu_check_subscriber_file: %s", e)
            sub_rows = -1
    return sub_file, sub_ok, sub_rows

def _stfu_read_config() -> dict:

    dvs_path = ""
    content  = ""
    for cand in _STFU_DVS_CANDIDATES:
        c, err = read_path_file(cand)
        if not err:
            dvs_path = str(cand)
            content  = c
            break

    if not dvs_path:
        return {
            "raw_ok": False, "dvs_path": "", "error": "DVSwitch.ini not found",
            "stfu_present": False,
            "bm_address": "", "bm_port": "62031", "bm_password": "",
            "dmr_id": "", "dmr_id_source": "", "address": "127.0.0.1",
            "rx_port": "", "tx_port": "", "start_tg": "",
            "subscriber_file": "", "subscriber_ok": False, "subscriber_rows": -1,
            "talker_alias": "", "log_level": "",
        }

    sections      = _dvs_parse_sections(content)
    stfu          = sections.get("STFU", {})
    stfu_present  = bool(stfu)

    bm_address    = stfu.get("BMAddress",     "").strip()
    bm_port       = stfu.get("BMPort",        "").strip() or "62031"
    bm_password   = stfu.get("BMPassword",    "").strip()
    dmr_id        = stfu.get("UserID",        "").strip()
    address       = stfu.get("Address",       "").strip() or "127.0.0.1"

    rx_port       = (stfu.get("rxPort") or stfu.get("RXPort") or "").strip()
    tx_port       = (stfu.get("txPort") or stfu.get("TXPort") or "").strip()
    start_tg      = stfu.get("StartTG",       "").strip()
    sub_file      = stfu.get("subscriberFile","").strip()
    talker_alias  = stfu.get("TalkerAlias",   "").strip()
    log_level     = stfu.get("LogLevel",      "").strip()

    dmr_id, dmr_id_source = _resolve_node_dmr_id(dmr_id)
    sub_file, sub_ok, sub_rows = _stfu_check_subscriber_file(sub_file)

    return {
        "raw_ok":          True,
        "dvs_path":        dvs_path,
        "error":           "",
        "stfu_present":    stfu_present,
        "bm_address":      bm_address,
        "bm_port":         bm_port,
        "bm_password":     bm_password,
        "dmr_id":          dmr_id,
        "dmr_id_source":   dmr_id_source,
        "address":         address,
        "rx_port":         rx_port,
        "tx_port":         tx_port,
        "start_tg":        start_tg,
        "subscriber_file": sub_file,
        "subscriber_ok":   sub_ok,
        "subscriber_rows": sub_rows,
        "talker_alias":    talker_alias,
        "log_level":       log_level,
    }

_DETAIL_PROPS = [
    "Description", "ActiveState", "UnitFileState",
    "MainPID", "NRestarts", "ExecMainStatus", "CanReload",
    "User", "Group", "FragmentPath", "ExecStart",
]

def _invalid_unit_detail(unit: str) -> dict:
    return {
        "unit": unit, "desc": "", "state": "unknown",
        "enabled": "unknown", "pid": 0, "nrestarts": 0,
        "exit_status": 0, "cpu_pct": None, "rss_mb": None,
        "can_reload": False, "installed": False,
        "user_cfg": "", "group_cfg": "", "fragment_path": "",
        "exec_path": "", "euser": "",
        "error": "invalid unit name",
    }

def _not_installed_detail(unit: str) -> dict:
    return {
        "unit": unit, "desc": "", "state": "not-inst",
        "enabled": "unknown", "pid": 0, "nrestarts": 0,
        "exit_status": 0, "cpu_pct": None, "rss_mb": None,
        "can_reload": False, "installed": False,
        "user_cfg": "", "group_cfg": "", "fragment_path": "",
        "exec_path": "", "euser": "",
    }

def _parse_show_block(unit: str, block: str) -> dict:
    values = {}
    for line in block.splitlines():
        if "=" in line:
            key, _, val = line.partition("=")
            if key == "ExecStart" and key in values:
                continue
            values[key] = val

    def _get(key: str, default="") -> str:
        return values.get(key, default).strip()

    desc         = _get("Description")
    state        = _get("ActiveState") or "unknown"
    enabled      = _get("UnitFileState") or "unknown"
    can_reload_s = _get("CanReload", "no")

    try:
        pid = int(_get("MainPID", "0"))
    except ValueError:
        pid = 0
    try:
        nrestarts = int(_get("NRestarts", "0"))
    except ValueError:
        nrestarts = 0
    try:
        exit_status = int(_get("ExecMainStatus", "0"))
    except ValueError:
        exit_status = 0

    can_reload = can_reload_s.strip().lower() == "yes"

    exec_raw  = _get("ExecStart")
    exec_m    = _EXECSTART_PATH_RE.search(exec_raw)
    exec_path = exec_m.group(1) if exec_m else ""

    return {
        "unit":        unit,
        "desc":        desc,
        "state":       state,
        "enabled":     enabled,
        "pid":         pid,
        "nrestarts":   nrestarts,
        "exit_status": exit_status,
        "cpu_pct":     None,
        "rss_mb":      None,
        "can_reload":  can_reload,
        "installed":   True,
        "user_cfg":      _get("User"),
        "group_cfg":     _get("Group"),
        "fragment_path": _get("FragmentPath"),
        "exec_path":     exec_path,
        "euser":         "",
    }

def get_services_details(units: "list[str]") -> "dict[str, dict]":
    result: "dict[str, dict]" = {}

    seen = set()
    valid_units = []
    for u in units:
        if u in seen:
            continue
        seen.add(u)
        if _validate_unit(u):
            valid_units.append(u)
        else:
            result[u] = _invalid_unit_detail(u)

    if not valid_units:
        return result

    installed_raw = _run(
        ["systemctl", "list-unit-files", "--no-pager", "--no-legend"] + valid_units,
        timeout=6,
    )
    installed_set = set()
    for line in installed_raw.splitlines():
        parts = line.split()
        if parts:
            installed_set.add(parts[0])

    installed_units = []
    for u in valid_units:
        if u in installed_set:
            installed_units.append(u)
        else:
            result[u] = _not_installed_detail(u)

    if not installed_units:
        return result

    raw = _run(
        ["systemctl", "show", "-p", ",".join(_DETAIL_PROPS)] + installed_units,
        timeout=8,
    )
    blocks = raw.split("\n\n") if raw else []

    pid_to_unit: "dict[int, str]" = {}
    if len(blocks) == len(installed_units):
        for unit, block in zip(installed_units, blocks):
            detail = _parse_show_block(unit, block)
            result[unit] = detail
            if detail["pid"] > 0:
                pid_to_unit[detail["pid"]] = unit
    else:
        for unit in installed_units:
            single_raw = _run(
                ["systemctl", "show", "-p", ",".join(_DETAIL_PROPS), unit],
                timeout=6,
            )
            detail = _parse_show_block(unit, single_raw)
            result[unit] = detail
            if detail["pid"] > 0:
                pid_to_unit[detail["pid"]] = unit

    if pid_to_unit:
        pid_list = ",".join(str(p) for p in pid_to_unit)
        ps_raw = _run(["ps", "-o", "pid=,%cpu=,rss=,euser:32=", "-p", pid_list],
                      timeout=5)
        for line in ps_raw.splitlines():
            parts = line.split()
            if len(parts) >= 3:
                try:
                    p_pid   = int(parts[0])
                    cpu_pct = float(parts[1])
                    rss_mb  = round(int(parts[2]) / 1024, 1)
                except (ValueError, IndexError):
                    continue
                u = pid_to_unit.get(p_pid)
                if u and u in result:
                    result[u]["cpu_pct"] = cpu_pct
                    result[u]["rss_mb"]  = rss_mb
                    if len(parts) >= 4:
                        result[u]["euser"] = parts[3]

    return result

def get_service_detail(unit: str) -> dict:
    return get_services_details([unit]).get(unit) or _invalid_unit_detail(unit)

_PH_DASH_CONF  = Path("/etc/asl_dvs/asl_dvs.conf")

_PH_PHONE_JSON = Path("/etc/asl_dvs/phone.json")

_PH_BEGIN      = "; >>> dvs-phone"

_PH_END        = "; <<< dvs-phone <<<"

_PH_MAX_BYTES  = 1_000_000

_PH_MAX_DEPTH  = 3

_PH_NAME_RE    = re.compile(r"^[\w.\-]+$")

_PH_INC_RE     = re.compile(r'^#\s*(?:try)?include\s+"?([^"\s>]+)"?', re.I)

_PH_SEC_RE     = re.compile(r"^\[([^\]]+)\]\s*(?:\(([^)]*)\))?")

_PH_ARROW_RE   = re.compile(r"^([^=\s]+)\s*=>\s*(.*)$")

_PH_EQ_RE      = re.compile(r"^([^=]+?)\s*=\s*(.*)$")

_PH_CMT_RE     = re.compile(r"(?<!\\);.*$")

def _ph_parse_file(ctx: dict, top: str, fname: str, state: dict, depth: int, managed: bool) -> None:
    if depth > _PH_MAX_DEPTH or not _PH_NAME_RE.match(fname):
        return
    path = ctx["dir"] / fname
    try:
        if path.stat().st_size > _PH_MAX_BYTES:
            ctx["errors"].append(f"{fname}: too large to read")
            return
        text = path.read_text(errors="replace")
    except FileNotFoundError:
        if fname not in ctx["missing"]:
            ctx["missing"].append(fname)
        return
    except OSError as e:
        ctx["errors"].append(f"{fname}: {e}")
        return
    if fname not in ctx["files"]:
        ctx["files"].append(fname)
    whole = managed or fname.startswith("dvs_phone_")
    in_block = False
    in_cmt = False
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if in_cmt:
            if "--;" in line:
                in_cmt = False
            continue
        if line.startswith(_PH_BEGIN):
            in_block = True
            continue
        if line.startswith(_PH_END):
            in_block = False
            continue
        if line.startswith(";--"):
            in_cmt = "--;" not in line[3:]
            continue
        m = _PH_INC_RE.match(line)
        if m:
            keep = state["sec"]
            _ph_parse_file(ctx, top, m.group(1), state, depth + 1, whole or in_block)
            state["sec"] = keep
            continue
        line = _PH_CMT_RE.sub("", line).strip()
        if not line or line.startswith("#"):
            continue
        managed_now = whole or in_block
        sm = _PH_SEC_RE.match(line)
        if sm:
            tpl = [t.strip() for t in (sm.group(2) or "").split(",") if t.strip()]
            sec = {"name": sm.group(1).strip(), "templates": [t for t in tpl if t != "!"],
                   "is_template": "!" in tpl, "kv": [], "file": fname, "line": n,
                   "managed": managed_now}
            ctx["conf"][top].append(sec)
            state["sec"] = sec
            continue
        if state["sec"] is None:
            sec = {"name": "", "templates": [], "is_template": False, "kv": [], "file": fname,
                   "line": n, "managed": managed_now}
            ctx["conf"][top].append(sec)
            state["sec"] = sec
        am = _PH_ARROW_RE.match(line)
        em = am or _PH_EQ_RE.match(line)
        if not em:
            continue
        state["sec"]["kv"].append((em.group(1).strip(), em.group(2).strip(), n, managed_now))

def _ph_dash_info() -> dict:
    info = {"phone_node": "", "names": {}, "active": "", "asl_node": "", "tone_path": "",
            "bridge_nodes": [], "networks": []}
    try:
        for line in _PH_DASH_CONF.read_text(errors="replace").splitlines():
            m = re.match(r"^\s*bridge_nodes\s*=\s*(.*)$", line)
            if m:
                parts = [p.strip() for p in m.group(1).split(",")]
                info["bridge_nodes"] = [p if p.isdigit() else "" for p in parts[:4]]
                if len(parts) > 2 and parts[2].isdigit():
                    info["phone_node"] = parts[2]
                continue
            m = re.match(r"^\s*asl_node\s*=\s*(\d+)\s*$", line)
            if m:
                info["asl_node"] = m.group(1)
    except OSError:
        pass
    try:
        doc = json.loads(_PH_PHONE_JSON.read_text())
        if isinstance(doc, dict):
            info["active"] = str(doc.get("active", ""))[:40]
            info["tone_path"] = str(doc.get("tone_path", ""))[:12]
            for n in doc.get("networks", []):
                if isinstance(n, dict) and n.get("id"):
                    info["names"][str(n["id"])] = str(n.get("name", ""))[:40]
                    info["networks"].append({"id": str(n["id"])[:40], "name": str(n.get("name", ""))[:40],
                                             "node": str(n.get("node", "") or "")[:7],
                                             "type": str(n.get("type", "") or "")[:12]})
    except (OSError, ValueError):
        pass
    info["phone_nodes"] = {n["node"]: n["name"] for n in info["networks"] if n["node"].isdigit()}
    picked = next((n for n in info["networks"] if n["id"] == info["active"] and n["node"].isdigit()), None)
    info["live_phone_node"] = picked["node"] if picked else info["phone_node"]
    return info

def _ph_resolve(secs: list, name: str, _depth: int = 0) -> "tuple[dict, bool, str]":
    out: dict = {}
    managed = False
    fname = ""
    if _depth > 5:
        return out, managed, fname
    for s in secs:
        if s["name"] != name:
            continue
        for t in s["templates"]:
            o2, m2, _f = _ph_resolve(secs, t, _depth + 1)
            out.update(o2)
            managed = managed or m2
        for k, v, *_ in s["kv"]:
            out[k.strip().lower()] = v
        managed = managed or s["managed"]
        fname = fname or s["file"]
    return out, managed, fname

def get_firewall_backend() -> str:
    
    if shutil.which("firewall-cmd"):
        state = _run(["firewall-cmd", "--state"], timeout=4).strip()
        if state == "running":
            return "firewalld"
    if shutil.which("ufw"):
        return "ufw"
    for tool in ("nft", "iptables"):
        if shutil.which(tool):
            return tool
    return "none"

def get_ufw_rules() -> list:
    raw = _run(["ufw", "status", "numbered"], timeout=6)
    if not raw:
        return []

    rules = []
    for line in raw.splitlines():
        m = re.match(
            r'^\[\s*(\d+)\]\s+'
            r'(.+?)\s+'
            r'(ALLOW|DENY|LIMIT|REJECT)'
            r'(?:\s+IN)?\s+'
            r'(.+?)\s*$',
            line.strip(),
        )
        if not m:
            continue
        num, to, action, from_ = m.groups()
        if "(v6)" in to:
            continue
        rules.append({
            "num":    int(num),
            "to":     to.strip(),
            "action": action,
            "from":   from_.strip(),
        })
    return rules

def _firewalld_active_zones() -> list:
    raw = _run(["firewall-cmd", "--get-active-zones"], timeout=5)
    zones = [ln.split()[0] for ln in raw.splitlines() if ln.strip() and not ln[0].isspace()]
    if not zones:
        dz = _run(["firewall-cmd", "--get-default-zone"], timeout=5).strip()
        zones = [dz] if dz else []
    return zones

_FIREWALLD_SERVICE_DIRS = (Path("/etc/firewalld/services"),
                           Path("/usr/lib/firewalld/services"))

_FWD_SERVICE_RE = re.compile(r'^[\w.+-]{1,64}$')

def _firewalld_service_ports(name: str, _depth: int = 0) -> list:
    if not _FWD_SERVICE_RE.match(name) or _depth > 4:
        return []
    import xml.etree.ElementTree as _ET
    for d in _FIREWALLD_SERVICE_DIRS:
        f = d / f"{name}.xml"
        if not f.is_file():
            continue
        try:
            root = _ET.parse(f).getroot()
        except Exception as e:
            log.debug("_firewalld_service_ports %s: %s", f, e)
            break
        ports = []
        for p in root.findall("port"):
            port, proto = p.get("port", ""), p.get("protocol", "")
            if port and proto:
                ports.append(f"{port}/{proto}")
        for inc in root.findall("include"):
            for sp in _firewalld_service_ports(inc.get("service", ""), _depth + 1):
                if sp not in ports:
                    ports.append(sp)
        return ports
    raw = _run(["firewall-cmd", f"--info-service={name}"], timeout=5)
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("ports:"):
            return [p for p in line.split(":", 1)[1].split() if "/" in p]
    return []

_FWD_RICH_PORT_RE = re.compile(
    r'port\s+port="?([\d-]+)"?\s+protocol="?(tcp|udp)"?.*?\b(accept|reject|drop)\b')

_FWD_RICH_SRC_RE = re.compile(r'source\s+(?:NOT\s+)?address="?([^"\s]+)"?')

def _firewalld_zone_rules(zone: str, raw: "str | None" = None) -> list:
    if raw is None:
        raw = _run(["firewall-cmd", f"--zone={zone}", "--list-all"], timeout=6)
    fields: "dict[str, str]" = {}
    rich: list = []
    in_rich = False
    for raw_line in raw.splitlines():
        if not raw_line.strip():
            continue
        line = raw_line.strip()
        if raw_line.startswith("  ") and not raw_line.startswith("   ") and ":" in line:
            key, _, val = line.partition(":")
            in_rich = key == "rich rules"
            fields[key] = val.strip()
            continue
        if in_rich:
            rich.append(line)

    rules = []
    for spec in fields.get("ports", "").split():
        if "/" in spec:
            rules.append({"num": f"{spec}@{zone}", "to": spec, "action": "ALLOW",
                          "from": f"zone={zone}", "via": "port"})
    for svc in fields.get("services", "").split():
        sports = _firewalld_service_ports(svc)
        for spec in sports or ["(no ports)"]:
            rules.append({"num": f"svc:{svc}@{zone}", "to": spec, "action": "ALLOW",
                          "from": f"zone={zone} · service {svc}", "via": "service",
                          "fw_service": svc, "service_ports": sports})
    for i, rr in enumerate(rich, 1):
        m = _FWD_RICH_PORT_RE.search(rr)
        if not m:
            continue
        port, proto, verdict = m.groups()
        src = _FWD_RICH_SRC_RE.search(rr)
        rules.append({"num": f"rich:{i}@{zone}", "to": f"{port}/{proto}",
                      "action": "ALLOW" if verdict == "accept" else "DENY",
                      "from": f"zone={zone} · {src.group(1) if src else 'rich rule'}",
                      "via": "rich", "deletable": False})
    return rules

def save_config(updates: dict, path: Path = CONFIG_FILE) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        for key, val in updates.items():
            if "." in key:
                sec, k = key.split(".", 1)
                if not _cfg.has_section(sec):
                    _cfg.add_section(sec)
                _cfg.set(sec, k, str(val))
            elif isinstance(val, dict):
                if not _cfg.has_section(key):
                    _cfg.add_section(key)
                for k, v in val.items():
                    _cfg.set(key, k, str(v))
        buf = io.StringIO()
        _cfg.write(buf)
        _atomic_write(path, buf.getvalue())
        _log(f"Config saved to {path}")
        return True
    except Exception as exc:
        _log(f"WARN — config save error: {exc}")
        return False

_NL_SPLIT_RE = re.compile(r"\r\n|\r|\n")

def _iter_proc_lines(stream):
    dec     = codecs.getincrementaldecoder("utf-8")("replace")
    fd      = stream.fileno()
    buf     = ""
    skip_lf = False
    while True:
        chunk = os.read(fd, 4096)
        text  = dec.decode(chunk, final=not chunk)
        if text:
            if skip_lf:
                if text[0] == "\n":
                    text = text[1:]
                skip_lf = False
            buf += text
            *done, buf = _NL_SPLIT_RE.split(buf)
            yield from done
            if not buf and text.endswith("\r"):
                skip_lf = True
        if not chunk:
            break
    if buf:
        yield buf

def _resolve_owner(detail: dict) -> dict:
    if not detail.get("installed"):
        return {"owner": "\u2014", "source": "none", "is_root": False}
    running = (detail.get("euser") or "").strip()
    if running:
        return {"owner": running, "source": "running", "is_root": running == "root"}
    cfg = (detail.get("user_cfg") or "").strip()
    if cfg:
        return {"owner": cfg, "source": "configured", "is_root": cfg == "root"}
    return {"owner": "root", "source": "default", "is_root": True}

_ASL_URL  = "https://allstarlink.org"

_ASL_NOTE = "AllStarLink Node Password"

_AB_DEF_DMR_ID     = "1234567"

_MB_DEF_DMR_ID     = "1234567"

_DVS_DEF_SERVER    = "3102.repeater.net"

_DVS_DEF_DMR_ID    = "1234567"

def write_path_file(path: Path, content: str) -> "tuple[bool, str]":
    if not content.strip():
        return False, "Content must not be empty"
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, content)
        return True, f"Saved {path}"
    except Exception as exc:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception as e:
            log.debug("write_path_file: %s", e)
            pass
        return False, f"Write failed: {exc}"

def get_service_enablement_map() -> dict:
    raw = _run(["systemctl", "list-unit-files", "--type=service",
                "--no-pager", "--no-legend"], timeout=8)
    out = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            out[parts[0].strip()] = parts[1].strip()
    return out

def _all_services_owner_map() -> "dict[str, dict]":
    raw = _run(["systemctl", "show", "--property=Id,User,FragmentPath",
                "--type=service", "*.service"], timeout=8)
    out: "dict[str, dict]" = {}
    if not raw:
        return out
    for block in raw.split("\n\n"):
        kv = {}
        for line in block.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                kv[k.strip()] = v.strip()
        unit = kv.get("Id", "")
        if unit:
            out[unit] = {"user": kv.get("User", ""),
                          "fragment": kv.get("FragmentPath", "")}
    return out

def get_all_services(scope: str = "active", filter_str: str = "",
                     exclude: "set | None" = None) -> list:
    flag = "--state=active" if scope == "active" else "--state=loaded"
    raw  = _run(["systemctl", "list-units", "--type=service",
                 "--no-pager", "--no-legend", flag], timeout=8)
    enablement = get_service_enablement_map()
    items = []
    for line in raw.splitlines():
        parts = line.split()
        if not parts:
            continue
        unit = parts[0].strip()
        if not _validate_unit(unit):
            continue
        if exclude and unit in exclude:
            continue
        if filter_str and filter_str.lower() not in unit.lower():
            continue

        state = parts[2].strip() if len(parts) > 2 else "unknown"
        items.append({
            "unit": unit, "state": state,
            "enabled": enablement.get(unit, "unknown"),
        })
    items.sort(key=lambda it: it["unit"])

    owners = _all_services_owner_map()
    for it in items:
        info = owners.get(it["unit"], {})
        cfg  = (info.get("user") or "").strip()
        it["owner"]         = cfg or "root"
        it["owner_source"]  = "configured" if cfg else "default"
        it["owner_is_root"] = (it["owner"] == "root")
        it["owner_exempt"]  = it["unit"] in _ROOT_EXEMPT_UNITS
        finfo = _stat_mode_info(info.get("fragment", ""))
        verdict, reasons = _perm_verdict(finfo)
        it["mode"]         = finfo["mode"]
        it["unit_path"]    = finfo["path"]
        it["unit_owner"]   = (f"{finfo['owner']}:{finfo['group']}"
                               if finfo["exists"] else "")
        it["perm_verdict"] = verdict
        it["perm_reasons"] = reasons
        it["installed"]    = True
    return items

_STFU_MB_CANDIDATES = [
    Path("/opt/MMDVM_Bridge/MMDVM_Bridge.ini"),
    Path("/etc/MMDVM_Bridge/MMDVM_Bridge.ini"),
]

def _svc_install_state(service: str, unit_paths) -> tuple:
    svc_path = next((str(p) for p in unit_paths if p.exists()), "")
    if not svc_path:
        return "", False, False, False
    props: "dict[str, str]" = {}
    for line in _run(["systemctl", "show", service,
                      "-p", "ActiveState", "-p", "UnitFileState"],
                     timeout=4).splitlines():
        k, sep, v = line.partition("=")
        if sep:
            props[k.strip()] = v.strip()
    return (svc_path, True,
            props.get("ActiveState") == "active",
            props.get("UnitFileState") == "enabled")

def _resolve_node_dmr_id(dmr_id: str) -> "tuple[str, str]":
    dmr_id_source = "DVSwitch.ini" if dmr_id else ""

    if not dmr_id or dmr_id == _DVS_DEF_DMR_ID:
        for cand in _STFU_MB_CANDIDATES:
            c, err = read_path_file(cand)
            if not err:
                mb  = _dvs_parse_sections(c)
                mid = mb.get("GENERAL", {}).get("Id", "").strip()
                if mid and mid != _MB_DEF_DMR_ID:
                    dmr_id        = mid
                    dmr_id_source = "MMDVM_Bridge.ini"
                    break

    if not dmr_id or dmr_id == _DVS_DEF_DMR_ID:
        for cand in _STFU_AB_CANDIDATES:
            c, err = read_path_file(cand)
            if not err:
                ab  = _dvs_parse_sections(c)
                aid = ab.get("AMBE_AUDIO", {}).get("gatewayDmrId", "").strip()
                if aid and aid != _AB_DEF_DMR_ID:
                    dmr_id        = aid
                    dmr_id_source = "Analog_Bridge.ini"
                    break

    return dmr_id, dmr_id_source

def _placeholder(val: str, label: str) -> str:
    return val if val else f"<{label}>"

def _m17_find_rpt_node(rpt: dict, node_id: str) -> "dict | None":
    for n in rpt.get("nodes", []):
        if n.get("id") == node_id:
            return n
    return None

def get_ufw_status() -> str:
    raw = _run(["ufw", "status"], timeout=5)
    if "active" in raw.lower():
        return "active"
    if "inactive" in raw.lower():
        return "inactive"
    return "unknown"

def _firewalld_parse_list_all(raw: str) -> dict:
    info = {"target": "", "interfaces": [], "rich_rules": []}
    in_rich = False
    for raw_line in raw.splitlines():
        if not raw_line.strip():
            continue
        is_field_line = (raw_line.startswith("  ")
                          and not raw_line.startswith("   ")
                          and not raw_line.startswith("\t"))
        line = raw_line.strip()
        if is_field_line:
            in_rich = line.startswith("rich rules:")
            if line.startswith("target:"):
                info["target"] = line.split(":", 1)[1].strip()
            elif line.startswith("interfaces:"):
                info["interfaces"] = line.split(":", 1)[1].split()
            continue
        if in_rich:
            info["rich_rules"].append(line)
    return info

_GET_ROUTES = {
    "/":                       _route_html,
    "/api/ping":               lambda h: h.send_ping(),
    "/api/whoami":             lambda h: h.send_json({"ok": True}),
    "/api/dashboard-status":   lambda h: h.send_json(action_dashboard_status()),
    "/api/status":             _route_status,
    "/api/reg/http":           _route_reg_http_get,
    "/api/reg/iax":            _route_reg_iax_get,
    "/api/config":             _route_config_get,
    "/api/log":                _route_log,
    "/api/overview":           _route_overview,
    "/api/services":           _route_services,
    "/api/services/detail":    _route_service_detail,
    "/api/ports":              _route_ports,
    "/api/ports/probe":        _route_ports_probe,
    "/api/journal/list":       _route_journal_list,
    "/api/journal/fetch":      _route_journal_fetch,
    "/api/logs/list":          _route_logs_list,
    "/api/logs/read":          _route_logs_read,
    "/api/logs/agent":         _route_logs_agent,
    "/api/unit_file":          _route_unit_file_get,
    "/api/asterisk/files":     _route_asterisk_list,
    "/api/asterisk/file":      _route_asterisk_get,
    "/api/allmon3/files":      _route_allmon3_list,
    "/api/allmon3/file":       _route_allmon3_get,
    "/api/dvswitch/files":     _route_dvswitch_list,
    "/api/dvswitch/file":      _route_dvswitch_get,
    "/api/simpleusb/tune":     _route_simpleusb_tune_get,
    "/api/rpt/nodesettings":   _route_rpt_nodes_get,
    "/api/radio/presets":      _route_radio_presets_get,
    "/api/radio/driver":       _route_radio_driver_get,
    "/api/radio/stack_status": _route_radio_stack_status,
    "/api/appconf/files":      _route_appconf_list,
    "/api/appconf/file":       _route_appconf_get,
    "/api/pinned":             _route_pinned_get,
    "/api/abinfo":             _route_abinfo,
    "/api/hardware":           _route_hardware_get,
    "/api/hardware/diag":      _route_hardware_diag,
    "/api/health":             _route_health,
    "/healthz":                lambda h: h.send_ping(),
    "/api/phone":              _route_phone_get,
    "/api/dvsm":               _route_dvsm,
    "/api/stfu":               _route_stfu_get,
    "/api/m17":                _route_m17_get,
    "/api/dstar-gw":           _route_dstar_gw_get,
    "/api/nodelisten":         _route_nodelisten_get,
    "/api/sdcard":             _route_sdcard_get,
    "/api/sdcard/test":        _route_sdcard_test_get,
    "/api/net/job":            _route_net_job_get,
}

_POST_ROUTES = {
    "/api/svc":             _route_svc,
    "/api/reboot":          _route_reboot,
    "/api/shutdown":        _route_shutdown,
    "/api/config":          _route_config_post,
    "/api/unit_file":       _route_unit_file_post,
    "/api/asterisk/file":   _route_asterisk_post,
    "/api/allmon3/file":    _route_allmon3_post,
    "/api/dvswitch/file":   _route_dvswitch_post,
    "/api/simpleusb/tune":  _route_simpleusb_tune_post,
    "/api/rpt/nodesettings": _route_rpt_nodes_post,
    "/api/radio/presets":   _route_radio_presets_post,
    "/api/radio/tune/save": _route_radio_tune_save_post,
    "/api/appconf/file":    _route_appconf_post,
    "/api/pinned":          _route_pinned_post,
    "/api/hardware":        _route_hardware_post,
    "/api/stfu":            _route_stfu_post,
    "/api/m17":             _route_m17_post,
    "/api/dstar-gw":        _route_dstar_gw_post,
    "/api/nodelisten":      _route_nodelisten_post,
    "/api/sdcard/test":     _route_sdcard_test_post,
    "/api/phone/modules":   _route_phone_modules_post,
    "/api/phone/routertest": _route_phone_routertest_post,
}

def _lan_ip() -> str:
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception as e:
        log.debug("_lan_ip: %s", e)
        return "your-pi-ip"

def startup() -> None:
    _update_state(
        hostname   = get_hostname(),
        kernel     = get_kernel(),
        uptime     = get_uptime(),
        load       = get_load(),
        memory     = get_memory(),
        swap       = get_swap(),
        cpu_temp   = get_cpu_temp(),
        pi_voltage     = get_pi_voltage(),
        throttle_state = get_throttle_state(),
        disk       = get_disk_usage(),
        sd_health  = get_sd_health(),
        proc_count = get_proc_count(),
        start_time = time.monotonic(),
    )
    threading.Thread(target=_bg_poll_loop, daemon=True, name="bg-poll").start()
    _log(f"sysmon v{VERSION} (build {BUILD_DATE}) started")

_INSTALL_DIR   = "/usr/local/lib/asl_dvs/sysmon"
_LEGACY_INSTALL_DIR = "/usr/local/lib/asl_dvs_sysmon"
_INSTALL_LINK  = "/usr/local/bin/sysmon.py"
_SERVICE_PATH  = "/etc/systemd/system/sysmon.service"
_LAUNCHER_PATH = "/usr/local/bin/asl_dvs_launch.py"
_SYSTEMD_UNIT_DIR = "/etc/systemd/system"
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
_SERVICE_CONTENT = f"""[Unit]
Description=ASL-DVS SYSMON
After=network.target

[Service]
Type=notify
NotifyAccess=main
ExecStart=/usr/bin/python3 {_LAUNCHER_PATH} {_INSTALL_LINK}
Restart=always
RestartSec=3s
WatchdogSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""

def _write_launcher() -> None:
    tmp = _LAUNCHER_PATH + ".tmp"
    with open(tmp, "w") as f:
        f.write(_LAUNCHER_CODE)
    os.chmod(tmp, 0o755)
    os.replace(tmp, _LAUNCHER_PATH)
    print(f"  [+] Wrote launcher {_LAUNCHER_PATH}")

def _pyc_for(src: str) -> list:
    name = os.path.splitext(os.path.basename(src))[0]
    return _glob_pyc(os.path.dirname(src), name)

def _glob_pyc(dir_path: str, name: str = "*") -> list:
    import glob as _g
    return _g.glob(os.path.join(dir_path, "__pycache__", f"{name}.*.pyc"))

def _prune_pyc(dir_path: str) -> None:
    for pyc in _glob_pyc(dir_path):
        name = os.path.basename(pyc).split(".", 1)[0]
        if not os.path.exists(os.path.join(dir_path, name + ".py")):
            try:
                os.remove(pyc)
            except OSError:
                pass

def _remove_launcher_if_unused() -> None:
    if not os.path.exists(_LAUNCHER_PATH):
        return
    unit_dir = _SYSTEMD_UNIT_DIR
    try:
        names = os.listdir(unit_dir)
    except OSError:
        return
    for n in names:
        p = os.path.join(unit_dir, n)
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

def install_service() -> None:
    if os.geteuid() != 0:
        print("ERROR: install requires root  →  sudo python3 sysmon.py --install",
              file=sys.stderr)
        sys.exit(1)

    current_script = os.path.realpath(__file__)
    print("Installing sysmon...")

    service_present = os.path.exists(_SERVICE_PATH)
    os.makedirs(_INSTALL_DIR, exist_ok=True)
    dest = os.path.join(_INSTALL_DIR, os.path.basename(current_script))
    if current_script != dest:
        tmp = dest + ".tmp"
        shutil.copy2(current_script, tmp)
        os.chmod(tmp, 0o755)
        os.replace(tmp, dest)
        print(f"  [+] Copied {os.path.basename(current_script)} -> {dest}")
    os.chmod(dest, 0o755)

    tmp_link = _INSTALL_LINK + ".tmp"
    if os.path.lexists(tmp_link):
        os.remove(tmp_link)
    os.symlink(dest, tmp_link)
    os.replace(tmp_link, _INSTALL_LINK)
    print(f"  [+] Symlinked {_INSTALL_LINK} -> {dest}")

    for name in os.listdir(_INSTALL_DIR):
        old = os.path.join(_INSTALL_DIR, name)
        if old != dest and name.endswith(".py") and os.path.isfile(old) and not os.path.islink(old):
            os.remove(old)
            print(f"  [-] Removed the previous version {old}")
    if os.path.isdir(_LEGACY_INSTALL_DIR):
        for name in os.listdir(_LEGACY_INSTALL_DIR):
            old = os.path.join(_LEGACY_INSTALL_DIR, name)
            if name.startswith("sysmon") and name.endswith(".py") and os.path.isfile(old):
                os.remove(old)
                print(f"  [-] Removed the old copy {old}")
        for pyc in _glob_pyc(_LEGACY_INSTALL_DIR, "sysmon*"):
            try:
                os.remove(pyc)
            except OSError:
                pass
        for d in (os.path.join(_LEGACY_INSTALL_DIR, "__pycache__"), _LEGACY_INSTALL_DIR):
            try:
                os.rmdir(d)
            except OSError:
                pass
        if not os.path.exists(_LEGACY_INSTALL_DIR):
            print(f"  [-] Removed the old folder {_LEGACY_INSTALL_DIR}")
    _write_launcher()
    _prune_pyc(_INSTALL_DIR)
    try:
        put_back = _bootcfg_reapply_saved(service_present)
    except Exception as e:
        put_back = []
        print(f"  [!] Could not put back your HDMI/GPU memory choices: {e}")
    if put_back:
        print(f"  [+] Put back in {BOOT_CONFIG}: {', '.join(put_back)} (they were set before this update)")

    with open(_SERVICE_PATH, "w") as f:
        f.write(_SERVICE_CONTENT)
    print(f"  [+] Wrote service file at {_SERVICE_PATH}")

    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "sysmon.service"], check=True)
    
    subprocess.run(["systemctl", "restart", "sysmon.service"], check=True)
    print("  [+] Enabled and started sysmon.service")
    print(f"\nInstall complete. {CONFIG_FILE} was not touched.")
    print("View logs anytime using:  journalctl -u sysmon -f")

def uninstall_service() -> None:
    if os.geteuid() != 0:
        print("ERROR: uninstall requires root  →  sudo python3 sysmon.py --uninstall",
              file=sys.stderr)
        sys.exit(1)

    print("Uninstalling sysmon...")

    subprocess.run(["systemctl", "disable", "--now", "sysmon.service"],
                    stderr=subprocess.DEVNULL)
    print("  [-] Stopped and disabled sysmon.service")

    if os.path.exists(_SERVICE_PATH):
        os.remove(_SERVICE_PATH)
        print(f"  [-] Removed {_SERVICE_PATH}")

    subprocess.run(["systemctl", "daemon-reload"], stderr=subprocess.DEVNULL)

    if os.path.islink(_INSTALL_LINK) or os.path.exists(_INSTALL_LINK):
        target = None
        if os.path.islink(_INSTALL_LINK):
            target = os.path.realpath(_INSTALL_LINK)
        os.remove(_INSTALL_LINK)
        print(f"  [-] Removed {_INSTALL_LINK}")
        if target and os.path.basename(target).startswith("sysmon_") and os.path.isfile(target):
            os.remove(target)
            print(f"  [-] Removed {target}")
        for pyc in _pyc_for(target or _INSTALL_LINK):
            try:
                os.remove(pyc)
            except FileNotFoundError:
                pass
    for d in (os.path.join(_INSTALL_DIR, "__pycache__"), _INSTALL_DIR, os.path.dirname(_INSTALL_DIR),
              os.path.join(_LEGACY_INSTALL_DIR, "__pycache__"), _LEGACY_INSTALL_DIR):
        try:
            os.rmdir(d)
        except OSError:
            pass
    _remove_launcher_if_unused()

    try:
        saved_for_update = _bootcfg_save_for_update()
        if _bootcfg_restore_all():
            print(f"  [-] Restored HDMI/video driver and GPU memory in {BOOT_CONFIG} (reboot to apply)")
            if saved_for_update:
                print("  [i] Your choices are kept for 30 minutes: installing SysMon again in that time puts them back")
    except OSError as e:
        print(f"  [!] Could not restore {BOOT_CONFIG}: {e}")

    print(f"\nUninstall complete. {CONFIG_FILE} was not touched.")

def main() -> None:
    parser = argparse.ArgumentParser(description="ASL-DVS SYSMON")
    parser.add_argument("--install", action="store_true", help="Install sysmon as a systemd service")
    parser.add_argument("--uninstall", action="store_true", help="Remove sysmon systemd service")
    parser.add_argument("--usrp-pairs", action="store_true",
                        help="Print the USRP pairing of rpt.conf, Analog_Bridge.ini and USRP2M17.ini as JSON, then exit")
    args = parser.parse_args()

    if args.usrp_pairs:
        print("USRP-PAIRS-JSON:" + json.dumps(_usrp_pairs_scan()))
        return
    if args.install:
        install_service()
        return
    if args.uninstall:
        uninstall_service()
        return

    if os.geteuid() != 0:
        print(
            "ERROR: sysmon must run as root  →  sudo python3 sysmon.py",
            file=sys.stderr,
        )
        sys.exit(1)

    startup()

    port = int(_cfg.get("server", "port", fallback=str(DEFAULT_PORT)))
    host = _cfg.get("server", "host", fallback="0.0.0.0")

    server = _ThreadingHTTPServer((host, port), Handler)

    def _sigterm(sig, frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _sigterm)

    global _http_ok_at
    probe_host = server.server_address[0]
    if probe_host in ("0.0.0.0", ""):
        probe_host = "127.0.0.1"
    _http_ok_at = time.monotonic()
    threading.Thread(target=_health_probe_loop, args=(probe_host, server.server_address[1]),
                     name="health-probe", daemon=True).start()
    threading.Thread(target=_sd_heartbeat_loop, name="sd-heartbeat", daemon=True).start()
    _sd_notify("READY=1")

    ip = _lan_ip()
    cs = _cfg.get("identity", "callsign", fallback="")
    nd = _cfg.get("identity", "node",     fallback="")

    print(f"""
╔══════════════════════════════════════════════╗
║           SYSMON  v{VERSION:<25}║
╠══════════════════════════════════════════════╣
║  Callsign : {cs:<32}║
║  Node     : {nd:<32}║
║  Build    : {BUILD_DATE:<32}║
╠══════════════════════════════════════════════╣
║  Local    : http://localhost:{port:<15}║
║  Network  : http://{ip}:{port:<6}          ║
╚══════════════════════════════════════════════╝
""")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()

if __name__ == "__main__":
    main()
