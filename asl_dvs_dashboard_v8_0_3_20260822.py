#!/usr/bin/env python3

import argparse
import gzip
import glob as _glob
import hashlib
import json
import logging
import os
import re
import shutil
import signal
import socket as _socket
import subprocess
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field, replace as _dc_replace
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Set, Tuple
from urllib.parse import urlparse

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

VERSION      = "8.0.3"
BUILD_DATE   = "2026-08-22"

ASL_NODE        = "652702"
ASL_BRIDGE_NODE = "1999"
ASL_PARROT_NODE = "55553"
ASL_CONF        = "/etc/asterisk/rpt.conf"
DVS_PATH        = "/opt/MMDVM_Bridge/dvswitch.sh"

_MAX_CONCURRENT_CONNECTIONS = 24

_DVS_SEARCH_PATHS = [
    "/opt/MMDVM_Bridge/dvswitch.sh",
    "/usr/local/sbin/dvswitch.sh",
    "/var/lib/dvswitch/dvswitch.sh",
]
PORT            = 8989

M17_NODE      = "1917"
M17_INI_PATH  = "/opt/USRP2M17/USRP2M17.ini"
M17_SERVICE   = "usrp2m17"

BRIDGE_SLOT_DIGITAL    = 0
BRIDGE_SLOT_M17        = 1
BRIDGE_SLOT_RESERVED_2 = 2
BRIDGE_SLOT_RESERVED_3 = 3
BRIDGE_SLOT_COUNT      = 4
BRIDGE_SLOT_LABELS     = ("Digital Voice Bridge", "M17 Bridge", "Reserved", "Reserved")
DEFAULT_BRIDGE_NODES   = [ASL_BRIDGE_NODE, M17_NODE, "", ""]

_M17_USRP_DST_PORT   = 32008
_M17_USRP_LOCAL_PORT = 34008
_M17_NET_LOCAL_PORT  = 32010
_M17_NET_DST_PORT    = 17000
_M17_GAIN_DB         = 3

AMI_USER   = ""
AMI_SECRET = ""

_DVS_SETTLE_MS = 400

TG_BLANK_NAME  = "blank"
TG_BLANK_ADDR  = "000000"
TG_DISCONNECT  = "disconnect"

DSTAR_UNLINK   = "       U"

ASL_DVS_CONF = "/etc/asl_dvs/asl_dvs.conf"

_BOOT_MARKER_PATH = "/run/asl_dvs/boot_marker"

_INSTALL_DIR      = "/usr/local/lib/asl_dvs"
_INSTALL_LINK     = "/usr/local/bin/asl_dvs_dashboard.py"
_SERVICE_PATH     = "/etc/systemd/system/asl_dvs_dashboard.service"
_SERVICE_CONTENT  = f"""[Unit]
Description=ASL-DVS Node Control Dashboard
After=network.target

[Service]
Type=notify
ExecStart=/usr/bin/python3 {_INSTALL_LINK}
Restart=always
RestartSec=3s
WatchdogSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""

def _sd_notify(state: str) -> None:
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr[0] == "@":
        addr = "\0" + addr[1:]
    try:
        sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_DGRAM)
        try:
            sock.connect(addr)
            sock.sendall(state.encode())
        finally:
            sock.close()
    except Exception as e:
        log.warning("_sd_notify: failed to notify systemd (%s): %s", state, e)

DIGITAL_MODES    = ("DMR", "STFU", "YSF", "P25", "NXDN", "DSTAR")
ALL_PAGES        = ("ASL", "ECHO") + DIGITAL_MODES + ("FCS", "XLX", "M17")
VALID_CONF_MODES = {"DMR", "STFU", "YSF", "FCS", "P25", "NXDN", "DSTAR"}
TUNE_MODES       = set(DIGITAL_MODES) | {"FCS"}

BRIDGE_SLOT_PAGES = {
    BRIDGE_SLOT_DIGITAL: TUNE_MODES | {"XLX"},
    BRIDGE_SLOT_M17:     {"M17"},
}

@dataclass
class Config:
    asl_node:            str      = ASL_NODE
    bridge_nodes:        List[str] = field(default_factory=lambda: list(DEFAULT_BRIDGE_NODES))
    port:                int      = PORT
    callsign:            str      = ""
    enabled_tabs:        Set[str] = field(default_factory=lambda: set(ALL_PAGES))
    enabled_tabs_sorted: list     = field(default_factory=lambda: list(ALL_PAGES))

_cfg = Config()

def _refresh_tabs_cache() -> None:
    _cfg.enabled_tabs_sorted = [p for p in ALL_PAGES if p in _cfg.enabled_tabs]

def _apply_config(cfg: dict) -> None:
    with _cfg_lock:
        if "asl_node" in cfg:
            v = str(cfg["asl_node"]).strip()
            if v.isdigit():
                _cfg.asl_node = v
        if "bridge_nodes" in cfg:

            items = cfg["bridge_nodes"]
            items = list(items) if isinstance(items, (list, tuple)) else str(items).split(",")
            items = [str(x).strip() for x in items][:BRIDGE_SLOT_COUNT]
            while len(items) < BRIDGE_SLOT_COUNT:
                items.append("")
            items = [v if v.isdigit() else "" for v in items]
            _cfg.bridge_nodes = items
        elif "bridge_node" in cfg:

            v = str(cfg["bridge_node"]).strip()
            if v.isdigit():
                _cfg.bridge_nodes[BRIDGE_SLOT_DIGITAL] = v
        if "port" in cfg:
            try:
                p = int(cfg["port"])
                if 1024 <= p <= 65535:
                    _cfg.port = p
            except (ValueError, TypeError):
                pass
        if "callsign" in cfg:
            _cfg.callsign = str(cfg["callsign"]).strip().upper()[:16]
            set_state(callsign=_cfg.callsign)
        if "enabled_tabs" in cfg:
            val   = cfg["enabled_tabs"]
            items = val if isinstance(val, (list, tuple)) else str(val).split(",")
            _cfg.enabled_tabs = {str(t).strip().upper() for t in items
                                 if str(t).strip().upper() in ALL_PAGES}
            _refresh_tabs_cache()

@dataclass
class AppState:
    page:        str                        = "ASL"
    status:      str                        = "Initializing…"
    current_fav: Optional[str]              = None
    current_fav_node: Optional[str]         = None
    talkgroups:  List[Tuple[str, str, str, str]] = field(default_factory=list)
    asl_nodes:   List[Tuple[str, str]]      = field(default_factory=list)
    keyed:       bool                       = False
    linked_node: Optional[str]              = None
    bridge_linked: bool                     = False
    bridge_linked_nodes: frozenset          = field(default_factory=frozenset)
    has_asl:     bool                       = True
    has_dvs:     bool                       = True
    has_stfu:    bool                       = False
    has_echo:    bool                       = False
    echo_nodes:  List[Tuple[str, str]]      = field(default_factory=list)
    echo_fav:    Optional[str]              = None
    stfu_server:        dict                = field(default_factory=dict)
    dmr_servers:        list                = field(default_factory=list)
    active_dmr_server:  str                 = ""
    dmr_server_tgs:     dict                = field(default_factory=dict)
    callsign:           str                 = ""
    xlx_reflectors:     list                = field(default_factory=list)
    current_dvs_mode:   str                 = ""
    perm_link_nodes:    frozenset           = field(default_factory=frozenset)
    mode_net_urls:      Dict[str, str]      = field(default_factory=dict)
    conf_warnings:      list                = field(default_factory=list)
    m17_reflectors:     list                = field(default_factory=list)
    has_m17:            bool                = False

_lock        = threading.Lock()
_cfg_lock    = threading.Lock()

_dvs_settle_until: float = 0.0
_state       = AppState()
_start_time  = time.monotonic()
_status_etag: str   = ""

def get_state() -> AppState:
    with _lock:
        return _dc_replace(_state)

def get_state_fields(*names: str) -> dict:
    with _lock:
        return {n: getattr(_state, n) for n in names}

def set_state(**kw) -> None:
    with _lock:
        for k, v in kw.items():
            if hasattr(_state, k):
                setattr(_state, k, v)
            else:
                raise AttributeError(f"AppState has no field '{k}'")

def _snap(attr: str) -> list:
    with _lock:
        return list(getattr(_state, attr))

def _sf(d: dict, key: str, fallback: str = "") -> str:
    return str(d.get(key, fallback)).strip().replace("|", "-")

def run(cmd: list, timeout: int = 10) -> Tuple[str, int]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "timeout", 1
    except Exception as e:
        return str(e), 1

_ASTERISK_RX_MIN_INTERVAL = 1.0
_asterisk_rx_lock         = threading.Lock()
_asterisk_rx_next_ok: float = 0.0

_asterisk_rx_ctrl_lock      = threading.Lock()
_asterisk_rx_ctrl_next_ok: float = 0.0

def _asterisk_rx(cmd_str: str, timeout: int = 10, priority: bool = False) -> Tuple[str, int]:
    global _asterisk_rx_next_ok, _asterisk_rx_ctrl_next_ok
    now = time.monotonic()
    if priority:
        with _asterisk_rx_ctrl_lock:
            if now < _asterisk_rx_ctrl_next_ok:
                return "asterisk -rx throttled -- link-control fallback rate-limited", 1
            _asterisk_rx_ctrl_next_ok = now + _ASTERISK_RX_MIN_INTERVAL
    else:
        with _asterisk_rx_lock:
            if now < _asterisk_rx_next_ok:
                return "asterisk -rx throttled -- AMI subprocess fallback rate-limited", 1
            _asterisk_rx_next_ok = now + _ASTERISK_RX_MIN_INTERVAL
    return run(["asterisk", "-rx", cmd_str], timeout=timeout)

def _has_ctrl_chars(s: str) -> bool:
    return any(ord(c) < 0x20 or ord(c) == 0x7f for c in s)

def _clip_label(s: str, limit: int = 64) -> str:
    return s[:limit]

_AMI_HOST    = "127.0.0.1"
_AMI_PORT    = 5038
_AMI_TIMEOUT = 4.0
_AMI_MANAGER_CONF = "/etc/asterisk/manager.conf"
_AMI_TERMINATOR_MAXLEN = len("--END COMMAND--")
_AMI_RPT_SHOW_VARS = "rpt show variables"

_ami_sock:      Optional[object] = None
_ami_lock       = threading.Lock()
_ami_available  = False
_ami_perm_fail  = False

_ami_reconnect_next_try: float = 0.0
_AMI_RECONNECT_COOLDOWN  = 5.0

def _ami_read_conf() -> Tuple[str, str]:
    if AMI_USER and AMI_SECRET:
        return AMI_USER, AMI_SECRET
    try:
        text = Path(_AMI_MANAGER_CONF).read_text(errors="replace")
    except OSError:
        return "", ""
    username = ""
    secret   = ""
    section  = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and "]" in line:
            if username and secret and section.lower() != "general":
                return username, secret
            section  = line[1:line.index("]")].strip()
            username = section
            secret   = ""
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            if k.strip().lower() == "secret":
                secret = v.strip()
    if username and secret and section.lower() != "general":
        return username, secret
    return "", ""

def _ami_connect() -> bool:
    global _ami_sock, _ami_available, _ami_perm_fail
    username, secret = _ami_read_conf()
    if not username or not secret:
        log.warning("AMI: no credentials found in %s — using subprocess fallback",
                    _AMI_MANAGER_CONF)
        return False
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.settimeout(_AMI_TIMEOUT)
        s.connect((_AMI_HOST, _AMI_PORT))
        banner = s.recv(256).decode("utf-8", errors="replace")
        if "Asterisk Call Manager" not in banner:
            s.close()
            log.warning("AMI: unexpected banner: %s", banner.strip())
            return False
        login = (
            f"Action: Login\r\n"
            f"Username: {username}\r\n"
            f"Secret: {secret}\r\n"
            f"Events: off\r\n"
            f"\r\n"
        )
        s.sendall(login.encode())
        resp = _ami_recv_block(s)
        if "Response: Success" not in resp:
            s.close()
            if "Response: Error" in resp:
                log.warning(
                    "AMI: login failed for user %r — credentials rejected by Asterisk. "
                    "Set AMI_USER/AMI_SECRET in USER CONFIGURATION or check "
                    "/etc/asterisk/manager.conf. Switching permanently to subprocess fallback.",
                    username,
                )
                _ami_perm_fail = True
            else:
                log.warning("AMI: login got no definitive response (%r) — will retry later",
                            resp[:80])
            return False
        _ami_sock      = s
        _ami_available = True
        log.info("AMI: connected as %s", username)
        return True
    except Exception as e:
        log.warning("AMI: connection failed: %s — using subprocess fallback", e)
        return False

def _ami_recv_block(sock) -> str:
    chunks: list = []
    tail = ""
    while True:
        try:
            chunk = sock.recv(4096).decode("utf-8", errors="replace")
        except Exception:
            break
        if not chunk:
            break
        chunks.append(chunk)
        window = tail + chunk
        if "\r\n\r\n" in window or "\n\n" in window:
            break
        tail = window[-(_AMI_TERMINATOR_MAXLEN - 1):]
    return "".join(chunks)

def _ami_recv_command(sock) -> str:
    chunks: list = []
    tail = ""
    while True:
        try:
            chunk = sock.recv(4096).decode("utf-8", errors="replace")
        except Exception:
            break
        if not chunk:
            break
        chunks.append(chunk)
        window = tail + chunk
        if "--END COMMAND--" in window:
            break
        if "\r\n\r\n" in window or "\n\n" in window:
            break
        tail = window[-(_AMI_TERMINATOR_MAXLEN - 1):]
    buf = "".join(chunks)
    lines = buf.splitlines()
    out_lines = []
    in_output = False
    for line in lines:
        if line.startswith("Output:") or line.startswith("Response:"):
            in_output = True
            if line.startswith("Output:"):
                out_lines.append(line[7:].lstrip())
            continue
        if line == "--END COMMAND--":
            break
        if in_output:
            out_lines.append(line)
    return "\n".join(out_lines).strip()

def ami_command(cmd_str: str, timeout: int = 4, priority: bool = False) -> Tuple[str, bool]:
    global _ami_sock, _ami_available, _ami_reconnect_next_try
    if _has_ctrl_chars(cmd_str):
        log.warning("AMI: rejected command with control characters: %r", cmd_str)
        return "rejected: illegal characters in command", False
    if _ami_perm_fail:
        out, rc = _asterisk_rx(cmd_str, timeout=timeout, priority=priority)
        return out, rc == 0

    action = (
        f"Action: Command\r\n"
        f"Command: {cmd_str}\r\n"
        f"\r\n"
    )

    with _ami_lock:
        if not _ami_available:
            now = time.monotonic()
            if now >= _ami_reconnect_next_try:
                _ami_reconnect_next_try = now + _AMI_RECONNECT_COOLDOWN
                _ami_connect()

        if _ami_available:
            try:
                _ami_sock.settimeout(timeout)
                _ami_sock.sendall(action.encode())
                out = _ami_recv_command(_ami_sock)
                return out, True
            except Exception as e:
                log.warning("AMI: socket error on command %r: %s — reconnecting", cmd_str, e)
                try:
                    _ami_sock.close()
                except Exception:
                    pass
                _ami_sock      = None
                _ami_available = False
                if _ami_connect():
                    try:
                        _ami_sock.settimeout(timeout)
                        _ami_sock.sendall(action.encode())
                        out = _ami_recv_command(_ami_sock)
                        return out, True
                    except Exception as e2:
                        log.warning("AMI: retry failed: %s — falling back to subprocess", e2)
                        _ami_available = False
    out, rc = _asterisk_rx(cmd_str, timeout=timeout, priority=priority)
    return out, rc == 0

_LEGACY_SECTION_URL_MODES = {"P25", "NXDN"}

def _parse_conf(path: str) -> Tuple[list, list, list, dict, list, dict, list, list, list, dict, list]:
    KNOWN_SECTIONS = {"ASL", "ECHO", "CONFIG", "XLX", "M17"} | VALID_CONF_MODES
    nodes, tgs, echo_nodes, cfg, section = [], [], [], {}, None
    xlx_reflectors = []
    xlx_legacy_skipped = []
    mode_net_urls: Dict[str, str] = {}
    legacy_section_url_found: list = []
    dmr_servers: list = []
    dmr_server_tgs = defaultdict(list)
    m17_reflectors = []

    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and "]" in line:
            section = line[1:line.index("]")].strip().upper()
            continue

        if section == "DMR_SERVERS":
            parts_full = line.split("|")
            if len(parts_full) >= 3:
                s_name = parts_full[0].strip()
                s_net_url = parts_full[3].strip() if len(parts_full) >= 4 else ""
                if not s_net_url:
                    s_net_url = _dmr_server_default_url(s_name)
                dmr_servers.append({"name": s_name,
                                    "password": parts_full[1].strip(),
                                    "address":  parts_full[2].strip(),
                                    "net_url":  s_net_url})
            continue
        if section and section.startswith("DMR_") and section != "DMR_SERVERS":
            parts_full = line.split("|", 1)
            if len(parts_full) == 2:
                name_key = section[4:]
                dmr_server_tgs[name_key].append(
                    ("DMR", parts_full[0].strip(), parts_full[1].strip(), ""))
            continue

        if section not in KNOWN_SECTIONS:
            continue

        if section == "CONFIG":
            if "=" in line:
                k, _, v = line.partition("=")
                cfg[k.strip().lower()] = v.strip()
            continue

        if section in _MODE_NET_URL_DEFAULTS and "=" in line and "|" not in line:
            k, _, v = line.partition("=")
            if k.strip().lower() == "network_url":
                mode_net_urls[section] = v.strip()
            continue

        if section in _LEGACY_SECTION_URL_MODES and "=" in line and "|" not in line:
            k, _, _v = line.partition("=")
            if k.strip().lower() == "network_url" and section not in legacy_section_url_found:
                legacy_section_url_found.append(section)
            continue

        parts = line.split("|", 1)
        if len(parts) < 2:
            continue
        name, val = parts[0].strip(), parts[1].strip()
        if not name or not val:
            continue

        if section == "ASL":
            raw_parts = line.split("|")
            node_val  = raw_parts[1].strip() if len(raw_parts) >= 2 else val
            nodes.append((name, node_val))
        elif section == "ECHO":
            raw_parts = line.split("|")
            node_val  = raw_parts[1].strip() if len(raw_parts) >= 2 else val
            echo_nodes.append((name, node_val))
        elif section == "XLX":
            raw_parts = line.split("|")
            if len(raw_parts) >= 4:
                skipped_name = raw_parts[0].strip()
                log.warning("XLX conf: skipping legacy 4-field row '%s'", skipped_name)
                xlx_legacy_skipped.append(skipped_name)
            else:
                xlx_name = raw_parts[0].strip()
                xlx_tg   = raw_parts[1].strip()
                xlx_tg   = xlx_tg.upper()
                xlx_url  = raw_parts[2].strip() if len(raw_parts) >= 3 else ""
                if xlx_name and xlx_tg and xlx_tg != TG_BLANK_ADDR:
                    xlx_reflectors.append((xlx_name, xlx_tg, xlx_url))
        elif section == "M17":

            raw_parts = line.split("|")
            if len(raw_parts) >= 4:
                m17_name   = raw_parts[0].strip()
                m17_base   = raw_parts[1].strip()
                m17_module = raw_parts[2].strip() or "@ALL"
                m17_ip     = raw_parts[3].strip()
                m17_url    = raw_parts[4].strip() if len(raw_parts) >= 5 else ""
            else:
                m17_name   = raw_parts[0].strip()
                m17_ip     = raw_parts[1].strip() if len(raw_parts) >= 2 else val
                m17_url    = raw_parts[2].strip() if len(raw_parts) >= 3 else ""
                m17_base   = m17_name
                m17_module = "@ALL"
            if m17_name and m17_ip and m17_ip != TG_BLANK_ADDR:
                m17_reflectors.append((m17_name, m17_base, m17_module, m17_ip, m17_url))
        elif section == "DSTAR":
            raw_parts = line.split("|")
            tg_val  = raw_parts[1].strip() if len(raw_parts) >= 2 else val
            row_url = raw_parts[2].strip() if len(raw_parts) >= 3 else ""
            if tg_val == TG_BLANK_ADDR or name == TG_BLANK_NAME:
                tgs.append(("DSTAR", name, tg_val, ""))
                continue
            if tg_val.strip() == DSTAR_UNLINK.strip():
                continue
            if " " in tg_val:
                parts2 = tg_val.rsplit(" ", 1)
                if len(parts2) == 2 and len(parts2[1]) == 1 and parts2[1].isalpha():
                    tg_val = parts2[0].strip() + parts2[1].upper() + "L"
                    log.warning("DSTAR conf shim: '%s' → '%s'", name, tg_val)
            elif len(tg_val) >= 2 and tg_val[-1].upper() != "L":
                tg_val = tg_val + "L"
                log.warning("DSTAR conf shim: appended L → '%s'", tg_val)
            tg_val = tg_val.upper()
            tgs.append(("DSTAR", name, tg_val, row_url))
        else:
            raw_parts = line.split("|")
            tg_val  = raw_parts[1].strip() if len(raw_parts) >= 2 else val
            row_url = raw_parts[2].strip() if len(raw_parts) >= 3 else ""
            tgs.append((section, name, tg_val, row_url))

    return (nodes, tgs, echo_nodes, cfg, xlx_reflectors, mode_net_urls,
            xlx_legacy_skipped, legacy_section_url_found,
            dmr_servers, dict(dmr_server_tgs), m17_reflectors)

def _blank_nodes(n=10):   return [(TG_BLANK_NAME, TG_BLANK_ADDR)] * n
def _blank_tgs(m, n=10):  return [(m, TG_BLANK_NAME, TG_BLANK_ADDR, "")] * n

def _pad_conf(nodes: list, tgs: list, echo_nodes: list) -> Tuple[list, list, list]:
    nodes      = (nodes      + _blank_nodes())[:10]
    echo_nodes = (echo_nodes + _blank_nodes())[:10]
    counts: Dict[str, int] = defaultdict(int)
    for t in tgs:
        counts[t[0]] += 1
    for m in DIGITAL_MODES:
        deficit = 10 - counts[m]
        if deficit > 0:
            tgs.extend(_blank_tgs(m, deficit))
    fcs_deficit = 10 - counts["FCS"]
    if fcs_deficit > 0:
        tgs.extend(_blank_tgs("FCS", fcs_deficit))
    return nodes, tgs, echo_nodes

_DEFAULT_DMR_SERVERS = [
    ("TGIF",     "passw0rd", "tgif.network:62031"),
    ("DMR+",     "passw0rd", "87.98.234.22:62030"),
    ("AmComm",   "passw0rd", "amcomm.example.com:62031"),
    ("ORM",      "passw0rd", "orm.example.com:62031"),
    ("FreeDMR",  "passw0rd", "freedmr.example.com:62031"),
    ("System X", "passw0rd", "sysx.example.com:62031"),
]

_MODE_NET_URL_DEFAULTS: Dict[str, str] = {
    "ASL":   "https://stats.allstarlink.org/",
    "ECHO":  "",
    "STFU":  "https://hose.brandmeister.network/",
}
_ROW_NET_URL_DEFAULTS: Dict[str, str] = {
    "YSF":   "https://register.ysfreflector.de/last_heard",
    "FCS":   "https://fcs00.xreflector.net/last_heard",
    "DSTAR": "https://dstarusers.org/lastheard.php",
    "XLX":   "https://xlx.ham-digital.net/status.php",
    "P25":   "https://p25.mwtelemetry.com/last_heard",
    "NXDN":  "https://nxdn.mwtelemetry.com/last_heard",
}
_DMR_NET_URL_DEFAULTS: Dict[str, str] = {
    "brandmeister": "https://hose.brandmeister.network/",
    "tgif":         "https://tgif.network/activetg.php",
    "freedmr":      "https://freedmr.uk/global-last-heard/",
    "quadnet":      "https://openquad.net/last.php",
    "amcomm":       "https://amcomm.network/dashboards",
    "qrm":          "https://kc3ol.net/last_heard",
    "freestar":     "https://dmr.freestar.network/dashboard",
    "system x":     "https://dmr.freestar.network/dashboard",
}

def _dmr_server_default_url(name: str) -> str:
    key = name.strip().lower()
    for k, url in _DMR_NET_URL_DEFAULTS.items():
        if k in key:
            return url
    return ""

def _server_key(name: str) -> str:
    return name.upper().replace(" ", "_").replace("+", "PLUS")

def _parse_dmr_servers(lines: list) -> list:
    servers = []
    section = None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and "]" in line:
            section = line[1:line.index("]")].strip().upper()
            continue
        if section != "DMR_SERVERS":
            continue
        parts = line.split("|")
        if len(parts) >= 3:
            name = parts[0].strip()
            net_url = parts[3].strip() if len(parts) >= 4 else ""
            if not net_url:
                net_url = _dmr_server_default_url(name)
            servers.append({"name": name,
                            "password": parts[1].strip(),
                            "address":  parts[2].strip(),
                            "net_url":  net_url})
    return servers

def _parse_dmr_server_tgs(lines: list) -> dict:
    tgs = defaultdict(list)
    section = None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and "]" in line:
            section = line[1:line.index("]")].strip().upper()
            continue
        if not section or not section.startswith("DMR_") or section == "DMR_SERVERS":
            continue
        parts = line.split("|", 1)
        if len(parts) == 2:
            name_key = section[4:]
            tgs[name_key].append(("DMR", parts[0].strip(), parts[1].strip(), ""))
    return dict(tgs)

def _atomic_write(path: Path, data: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    os.replace(tmp, path)
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception as exc:
        log.warning("_atomic_write: directory fsync failed for %s: %s", path.parent, exc)

def _generate_default_conf() -> None:

    bn = TG_BLANK_NAME
    ba = TG_BLANK_ADDR
    try:
        conf_dir = Path(ASL_DVS_CONF).parent
        conf_dir.mkdir(parents=True, exist_ok=True)
        conf_path = Path(ASL_DVS_CONF)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"# asl_dvs.conf — generated by ASL-DVS Node Control {ts}\n\n",
            "[CONFIG]\n",
            f"asl_node={_cfg.asl_node}\n",
            f"bridge_node={_cfg.bridge_nodes[BRIDGE_SLOT_DIGITAL]}\n",
            f"bridge_nodes={','.join(_cfg.bridge_nodes)}\n",
            f"port={_cfg.port}\n",
            f"callsign={_cfg.callsign}\n",
            f"enabled_tabs={chr(44).join(_cfg.enabled_tabs_sorted)}\n\n",
            "[ASL]\n",
        ]
        lines.append(f"network_url={_MODE_NET_URL_DEFAULTS['ASL']}\n")
        for _ in range(10):
            lines.append(f"{bn}|{ba}\n")
        lines.append("\n[ECHO]\n")
        lines.append(f"network_url={_MODE_NET_URL_DEFAULTS['ECHO']}\n")
        for _ in range(10):
            lines.append(f"{bn}|{ba}\n")
        for m in DIGITAL_MODES:
            lines.append(f"\n[{m}]\n")
            if m in _MODE_NET_URL_DEFAULTS:
                lines.append(f"network_url={_MODE_NET_URL_DEFAULTS[m]}\n")
            for _ in range(10):
                lines.append(f"{bn}|{ba}\n")
        lines.append("\n[FCS]\n")
        for _ in range(10):
            lines.append(f"{bn}|{ba}\n")
        lines.append("\n[DMR_SERVERS]\n")
        for name, pwd, addr in _DEFAULT_DMR_SERVERS:
            url = _dmr_server_default_url(name)
            lines.append(f"{name}|{pwd}|{addr}|{url}\n")
        for name, _, _ in _DEFAULT_DMR_SERVERS:
            lines.append(f"\n[DMR_{_server_key(name)}]\n")
            for _ in range(10):
                lines.append(f"{bn}|{ba}\n")
        lines.append("\n[XLX]\n")
        lines.append("# name|tg  (tg = D-Star tune string, e.g. XLX334AL)\n")
        for _ in range(10):
            lines.append(f"{bn}|{ba}\n")
        lines.append("\n[M17]\n")
        lines.append("# name|base|module|ip|url  (module = A-Z or the literal @ALL wildcard;\n")
        lines.append("# base+module get written into the USRP2M17.ini Name= field, e.g.\n")
        lines.append("# \"M17-USA A\" or \"M17-USA @ALL\" to join every module on that reflector)\n")
        for _ in range(10):
            lines.append(f"{bn}|{bn}|@ALL|{ba}\n")
        _atomic_write(conf_path, "".join(lines))
        log.info("Generated default config: %s", ASL_DVS_CONF)
    except Exception as exc:
        log.warning("Could not write default config: %s", exc)

def _migrate_legacy_conf() -> None:
    new_conf = Path(ASL_DVS_CONF)
    old_conf = Path("/etc/dvswitch/dvswitch.conf")

    if new_conf.is_file():
        return
    if not old_conf.is_file():
        return

    try:
        new_conf.parent.mkdir(parents=True, exist_ok=True)

        bak_files = sorted(_glob.glob(str(old_conf) + ".*.bak"))
        moved_baks = 0
        for bak in bak_files:
            dest = new_conf.parent / Path(bak).name
            try:
                dest.write_bytes(Path(bak).read_bytes())
                moved_baks += 1
                log.info("migration: copied bak %s → %s", bak, dest)
            except Exception as exc:
                log.warning("migration: could not copy bak %s: %s", bak, exc)

        new_conf.write_bytes(old_conf.read_bytes())
        log.info(
            "migration: copied %s → %s  (%d bak file(s) moved)",
            old_conf, new_conf, moved_baks,
        )

        _rotate_backup(new_conf)

    except Exception as exc:
        log.warning("migration: failed: %s", exc)

def _try_load_conf_from(path: Path) -> Optional[tuple]:
    try:
        (nodes, tgs, echo_nodes, cfg, xlx_refs, net_urls,
         xlx_skipped, legacy_sec_url, servers, srv_tgs, m17_refs) = _parse_conf(str(path))
        _apply_config(cfg)
        if servers:
            set_state(dmr_servers=servers,
                      active_dmr_server=servers[0]["name"],
                      dmr_server_tgs=srv_tgs)
        merged_urls = dict(_MODE_NET_URL_DEFAULTS)
        merged_urls.update(net_urls)
        set_state(xlx_reflectors=xlx_refs, mode_net_urls=merged_urls,
                  m17_reflectors=m17_refs)
        return nodes, tgs, echo_nodes, xlx_skipped, legacy_sec_url
    except Exception as exc:
        log.warning("load_conf: could not load %s: %s", path, exc)
        return None

def load_conf() -> Tuple[list, list, list]:
    if not Path(ASL_DVS_CONF).is_file():
        _generate_default_conf()
    nodes, tgs, echo_nodes = [], [], []
    conf_path = Path(ASL_DVS_CONF)
    if conf_path.is_file():
        result = _try_load_conf_from(conf_path)
        source_label = None
        if result is None:
            for bak in sorted(conf_path.parent.glob(f"{conf_path.name}.*.bak"), reverse=True):
                result = _try_load_conf_from(bak)
                if result is not None:
                    source_label = bak.name
                    log.warning("load_conf: primary config unusable, running from backup %s",
                                bak.name)
                    break
        if result is not None:
            nodes, tgs, echo_nodes, xlx_skipped, legacy_sec_url = result
            warnings = []
            if source_label:
                warnings.append(
                    f"Primary config failed to load — running from backup "
                    f"'{source_label}'. Review asl_dvs.conf and re-save when convenient."
                )
            if xlx_skipped:
                names = ", ".join(xlx_skipped)
                warnings.append(
                    f"XLX: {len(xlx_skipped)} legacy row(s) skipped on load and will be "
                    f"dropped on next save ({names}) — check .bak backups if needed"
                )
            if legacy_sec_url:
                modes = ", ".join(legacy_sec_url)
                warnings.append(
                    f"{modes}: legacy section-wide 'network_url=' line found and will be "
                    f"dropped on next save — Last Heard links now live on each talkgroup "
                    f"row (Edit tab); set them there if needed"
                )
            if warnings:
                set_state(conf_warnings=warnings)
        else:
            log.warning("load_conf: primary config and all backups failed to load — "
                        "starting with empty defaults; %s left untouched", ASL_DVS_CONF)
            set_state(conf_warnings=[
                "No usable config found (primary and all backups failed to load). "
                "Dashboard is running with empty defaults — asl_dvs.conf was left "
                "untouched; open the Edit tab or restore a .bak file to recover."
            ])
    return _pad_conf(nodes, tgs, echo_nodes)

def _validate_tg_entries(entries: list) -> Tuple[Optional[list], Optional[str]]:
    out = []
    for i, e in enumerate(entries):
        mode = str(e.get("mode", "")).strip().upper()
        name = str(e.get("name", "")).strip()
        tg   = str(e.get("tg",   "")).strip()
        url  = str(e.get("url",  "")).strip().rstrip("/")
        if mode not in VALID_CONF_MODES:
            return None, f"TG row {i+1}: invalid mode '{mode}'"
        if not name:
            return None, f"TG row {i+1}: name is empty"
        if not tg:
            return None, f"TG row {i+1}: tg/address is empty"
        out.append((mode,
                    name.replace("|", "-"), tg.replace("|", "-"),
                    url.replace("|", "%7C")))
    return out, None

def _validate_node_entries(entries: list) -> Tuple[Optional[list], Optional[str]]:
    out = []
    for i, e in enumerate(entries):
        name = _sf(e, "name")
        node = str(e.get("node", "")).strip()
        if name.lower() == TG_BLANK_NAME or node == TG_BLANK_ADDR:
            out.append((name or TG_BLANK_NAME, node or TG_BLANK_ADDR))
            continue
        if not name:
            return None, f"Node row {i+1}: name is empty"
        if not node or not node.isdigit():
            return None, f"Node row {i+1}: node must be a number (got '{node}')"
        out.append((name, node))
    return out, None

def _validate_echo_entries(entries: list) -> Tuple[Optional[list], Optional[str]]:
    out = []
    for i, e in enumerate(entries):
        name = _sf(e, "name")
        node = str(e.get("node", "")).strip()
        if name.lower() == TG_BLANK_NAME or node == TG_BLANK_ADDR:
            out.append((name or TG_BLANK_NAME, node or TG_BLANK_ADDR))
            continue
        if not name:
            return None, f"Echo row {i+1}: name is empty"
        if not node or not node.isdigit():
            return None, f"Echo row {i+1}: node must be a number (got '{node}')"
        if len(node) > 6:
            return None, f"Echo row {i+1}: EchoLink node numbers are 1-6 digits (got '{node}')"
        out.append((name, node))
    return out, None

_BAK_KEEP = 3

def _rotate_backup(conf_path: Path) -> None:
    if not conf_path.is_file():
        return
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = conf_path.with_name(conf_path.name + f".{ts}.bak")
    try:
        bak.write_bytes(conf_path.read_bytes())
    except Exception as e:
        log.warning("backup write failed: %s", e)
        return
    try:
        baks = sorted(conf_path.parent.glob(f"{conf_path.name}.*.bak"))
        for old in baks[:-_BAK_KEEP]:
            old.unlink(missing_ok=True)
    except Exception as e:
        log.warning("backup prune failed: %s", e)

def _write_conf(node_entries: list, tg_entries: list, echo_entries: list):
    conf_dir  = Path(ASL_DVS_CONF).parent
    conf_dir.mkdir(parents=True, exist_ok=True)
    conf_path = Path(ASL_DVS_CONF)
    try:
        _rotate_backup(conf_path)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"# asl_dvs.conf — saved by ASL-DVS Node Control {ts}\n\n",
            "[CONFIG]\n",
            f"asl_node={_cfg.asl_node}\n",
            f"bridge_node={_cfg.bridge_nodes[BRIDGE_SLOT_DIGITAL]}\n",
            f"bridge_nodes={','.join(_cfg.bridge_nodes)}\n",
            f"port={_cfg.port}\n",
            f"callsign={_cfg.callsign}\n",
            f"enabled_tabs={','.join(_cfg.enabled_tabs_sorted)}\n\n",
            "[ASL]\n",
        ]
        _st_urls = get_state().mode_net_urls
        lines.append(f"network_url={_st_urls.get('ASL', _MODE_NET_URL_DEFAULTS['ASL'])}\n")
        for name, node, *_rest in node_entries:
            lines.append(f"{name}|{node}\n")
        lines.append("\n[ECHO]\n")
        lines.append(f"network_url={_st_urls.get('ECHO', _MODE_NET_URL_DEFAULTS['ECHO'])}\n")
        for name, node, *_rest in echo_entries:
            lines.append(f"{name}|{node}\n")
        for m in DIGITAL_MODES:
            mode_tgs = [(n, t, u) for mode, n, t, u in tg_entries if mode == m]
            if mode_tgs:
                lines.append(f"\n[{m}]\n")
                if m in _MODE_NET_URL_DEFAULTS:
                    sec_url = get_state().mode_net_urls.get(m, _MODE_NET_URL_DEFAULTS[m])
                    lines.append(f"network_url={sec_url}\n")
                for n, t, u in mode_tgs:
                    lines.append(f"{n}|{t}|{u}\n" if u else f"{n}|{t}\n")
        fcs_tgs = [(n, t, u) for mode, n, t, u in tg_entries if mode == "FCS"]
        if fcs_tgs:
            lines.append("\n[FCS]\n")
            for n, t, u in fcs_tgs:
                lines.append(f"{n}|{t}|{u}\n" if u else f"{n}|{t}\n")
        xlx_refs = get_state().xlx_reflectors
        lines.append("\n[XLX]\n")
        lines.append("# name|tg[|url]  (tg = D-Star tune string, e.g. XLX334AL)\n")
        bn, ba = TG_BLANK_NAME, TG_BLANK_ADDR
        for xname, xtg, xurl in xlx_refs:
            lines.append(f"{xname}|{xtg}|{xurl}\n" if xurl else f"{xname}|{xtg}\n")
        for _ in range(max(0, 10 - len(xlx_refs))):
            lines.append(f"{bn}|{ba}\n")
        m17_refs = get_state().m17_reflectors
        lines.append("\n[M17]\n")
        lines.append("# name|base|module|ip[|url]  (module = A-Z or the literal @ALL wildcard;\n")
        lines.append("# base+module get written into the USRP2M17.ini Name= field)\n")
        for mname, mbase, mmodule, mip, murl in m17_refs:
            lines.append(f"{mname}|{mbase}|{mmodule}|{mip}|{murl}\n" if murl
                         else f"{mname}|{mbase}|{mmodule}|{mip}\n")
        for _ in range(max(0, 10 - len(m17_refs))):
            lines.append(f"{bn}|{bn}|@ALL|{ba}\n")
        _REGENERATED = {"CONFIG", "ASL", "ECHO", "XLX", "M17", "FCS"} | set(DIGITAL_MODES)
        if conf_path.is_file():
            try:
                existing = conf_path.read_text(errors="replace")
                in_keep = False
                for raw in existing.splitlines(keepends=True):
                    stripped = raw.strip()
                    if stripped.startswith("[") and "]" in stripped:
                        sec = stripped[1:stripped.index("]")].strip().upper()
                        in_keep = sec not in _REGENERATED
                    if in_keep:
                        lines.append(raw)
            except Exception as exc:
                log.warning("_write_conf: could not preserve extra sections: %s", exc)
        _atomic_write(conf_path, "".join(lines))
        return True, (f"Saved {len(node_entries)} ASL nodes, "
                      f"{len(echo_entries)} Echo nodes and "
                      f"{len(tg_entries)} talkgroups")
    except Exception as e:
        return False, f"Write failed: {e}"

def action_get_config() -> dict:
    st = get_state()
    merged_mode_urls = dict(_MODE_NET_URL_DEFAULTS)
    merged_mode_urls.update(st.mode_net_urls)
    return {
        "asl_node":             _cfg.asl_node,
        "bridge_node":          _cfg.bridge_nodes[BRIDGE_SLOT_DIGITAL],
        "bridge_nodes":         list(_cfg.bridge_nodes),
        "bridge_slot_labels":   list(BRIDGE_SLOT_LABELS),
        "port":                 _cfg.port,
        "callsign":             _cfg.callsign,
        "enabled_tabs":         _cfg.enabled_tabs_sorted,
        "mode_net_urls":        merged_mode_urls,
        "row_net_url_defaults": _ROW_NET_URL_DEFAULTS,
    }

def _validate_bridge_nodes(raw) -> Tuple[Optional[List[str]], Optional[str]]:
    items = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
    items = [str(x).strip() for x in items][:BRIDGE_SLOT_COUNT]
    while len(items) < BRIDGE_SLOT_COUNT:
        items.append("")
    for i, v in enumerate(items):
        if v and not v.isdigit():
            return None, f"Bridge slot {i+1} ({BRIDGE_SLOT_LABELS[i]}) must be numeric or blank (got '{v}')"
    return items, None

def action_save_config(cfg: dict) -> Tuple[bool, str]:
    asl_node    = str(cfg.get("asl_node",    _cfg.asl_node)).strip()
    bridge_node = str(cfg.get("bridge_node", _cfg.bridge_nodes[BRIDGE_SLOT_DIGITAL])).strip()
    port_str    = str(cfg.get("port",        _cfg.port)).strip()
    callsign    = str(cfg.get("callsign",    _cfg.callsign)).strip().upper()[:16]

    if not asl_node.isdigit():
        return False, f"ASL node must be numeric (got '{asl_node}')"
    if bridge_node and not bridge_node.isdigit():
        return False, f"Bridge node must be numeric or blank (got '{bridge_node}')"

    bridge_nodes = None
    if "bridge_nodes" in cfg:
        bridge_nodes, err = _validate_bridge_nodes(cfg["bridge_nodes"])
        if err:
            return False, err

    try:
        port = int(port_str)
        if not (1024 <= port <= 65535):
            raise ValueError
    except (ValueError, TypeError):
        return False, f"Port must be 1024–65535 (got '{port_str}')"

    nodes, tgs, echo_nodes = [], [], []
    if Path(ASL_DVS_CONF).is_file():
        try:
            nodes, tgs, echo_nodes, _, _xlx, _nurls, _xlx_skipped, _leg, _dsrv, _dtgs, _m17 = _parse_conf(ASL_DVS_CONF)
        except Exception:
            pass
    nodes, tgs, echo_nodes = _pad_conf(nodes, tgs, echo_nodes)

    tabs_raw = cfg.get("enabled_tabs")
    if tabs_raw is not None:
        with _cfg_lock:
            items = tabs_raw if isinstance(tabs_raw, list) else str(tabs_raw).upper().split(",")
            _cfg.enabled_tabs = {str(t).strip().upper() for t in items
                                 if str(t).strip().upper() in ALL_PAGES}
            _refresh_tabs_cache()
        if get_state().page not in _cfg.enabled_tabs:
            _st2     = get_state()
            _srv_lbl = _st2.active_dmr_server or "Disconnected"
            set_state(page="DMR", status=f"DMR | {_srv_lbl}", current_fav=None, current_fav_node=None)
            _seed_dmr_tgs()

    with _cfg_lock:
        prev_port = _cfg.port
    apply_cfg = {"asl_node": asl_node, "bridge_node": bridge_node,
                 "port": port_str, "callsign": callsign}
    if bridge_nodes is not None:
        apply_cfg["bridge_nodes"] = bridge_nodes
    _apply_config(apply_cfg)
    _write_event_script()

    net_urls_raw = cfg.get("mode_net_urls")
    if isinstance(net_urls_raw, dict):
        merged = dict(get_state().mode_net_urls)
        for k, v in net_urls_raw.items():
            if k in _MODE_NET_URL_DEFAULTS and isinstance(v, str):
                merged[k] = v.strip().rstrip("/")
        set_state(mode_net_urls=merged)

    ok, msg = _write_conf(nodes, tgs, echo_nodes)
    if ok and port != prev_port:
        msg += f" (port {port} takes effect after restart)"
    return ok, msg

def action_save_dmr_server_tgs(srv_tgs: dict, server_list: Optional[list] = None) -> Tuple[bool, str]:
    st = get_state()
    new_tgs: dict = {}
    for key, entries in srv_tgs.items():
        rows = []
        for e in entries:
            name = _sf(e, "name") or TG_BLANK_NAME
            tg   = _sf(e, "tg")   or TG_BLANK_ADDR
            rows.append(("DMR", name, tg, ""))
        _blank_dmr4 = [("DMR", TG_BLANK_NAME, TG_BLANK_ADDR, "")]
        rows = (rows + _blank_dmr4 * 10)[:10]
        new_tgs[key] = rows
    new_servers = server_list if isinstance(server_list, list) else st.dmr_servers
    for srv in (new_servers or []):
        n = _sf(srv, "name")
        if not n:
            continue
        a = _sf(srv, "address")
        host, sep, port = a.rpartition(":")
        if not sep or not host or not port.isdigit() or not (1 <= int(port) <= 65535):
            return False, f"DMR network '{n}': address must be host:port (got '{a}')"
    try:
        conf_path = Path(ASL_DVS_CONF)
        text = conf_path.read_text(errors="replace")
        lines_out = []
        skip = False
        for raw in text.splitlines(keepends=True):
            stripped = raw.strip()
            if stripped.startswith("[") and "]" in stripped:
                sec = stripped[1:stripped.index("]")].strip().upper()
                skip = sec.startswith("DMR_")
            if not skip:
                lines_out.append(raw)
        lines_out.append("\n[DMR_SERVERS]\n")
        for s in new_servers:
            n = _sf(s, "name")
            p = _sf(s, "password")
            a = _sf(s, "address")
            u = _sf(s, "net_url") or ""
            if n:
                lines_out.append(f"{n}|{p}|{a}|{u}\n")
        for key, rows in new_tgs.items():
            lines_out.append(f"\n[DMR_{key}]\n")
            for _, name, tg, _u in rows:
                lines_out.append(f"{name}|{tg}\n")
        _rotate_backup(conf_path)
        _atomic_write(conf_path, "".join(lines_out))
        set_state(dmr_server_tgs=new_tgs, dmr_servers=new_servers)
        if new_servers:
            current = get_state().active_dmr_server
            names   = [s["name"] for s in new_servers]
            set_state(active_dmr_server=current if current in names else names[0])
        return True, f"Saved {len(new_servers)} DMR networks, {len(new_tgs)} TG sections"
    except Exception as e:
        return False, f"Save failed: {e}"

def action_save_all(node_entries: list, tg_entries: list, echo_entries: list) -> Tuple[bool, str]:

    nd_san, err = _validate_node_entries(node_entries)
    if err:
        return False, err
    ec_san, err = _validate_echo_entries(echo_entries)
    if err:
        return False, err
    tg_san, err = _validate_tg_entries(tg_entries)
    if err:
        return False, err
    ok, msg = _write_conf(nd_san, tg_san, ec_san)
    if ok:
        set_state(asl_nodes=nd_san, echo_nodes=ec_san, talkgroups=tg_san)
    return ok, msg

def action_save_xlx(rows: list) -> Tuple[bool, str]:
    bn, ba = TG_BLANK_NAME, TG_BLANK_ADDR
    sanitized = []
    for i, e in enumerate(rows):
        name = _sf(e, "name") or bn
        tg   = _sf(e, "tg")   or ba
        url  = (_sf(e, "url") or "").strip().rstrip("/")
        sanitized.append((name, tg, url))
    while len(sanitized) < 10:
        sanitized.append((bn, ba, ""))
    sanitized = sanitized[:10]
    set_state(xlx_reflectors=sanitized)
    st = get_state()
    nodes      = list(st.asl_nodes)
    tgs        = list(st.talkgroups)
    echo_nodes = list(st.echo_nodes)
    ok, msg = _write_conf(nodes, tgs, echo_nodes)
    if ok:
        return True, f"Saved {len(sanitized)} XLX reflectors"
    return False, msg

def _norm_m17_module(raw: str) -> str:
    
    v = (raw or "").strip().upper()
    if v == "@ALL":
        return "@ALL"
    if len(v) == 1 and v.isalpha():
        return v
    return "@ALL"

def action_save_m17(rows: list) -> Tuple[bool, str]:
    bn, ba = TG_BLANK_NAME, TG_BLANK_ADDR
    sanitized = []
    for e in rows:
        ip   = _sf(e, "ip")   or ba
        base = _sf(e, "base") or (_sf(e, "name") if ip != ba else "") or bn
        name = _sf(e, "name") or base
        module = _norm_m17_module(str(e.get("module", "")))
        url  = (_sf(e, "url") or "").strip().rstrip("/")
        sanitized.append((name, base, module, ip, url))
    while len(sanitized) < 10:
        sanitized.append((bn, bn, "@ALL", ba, ""))
    sanitized = sanitized[:10]
    set_state(m17_reflectors=sanitized)
    st = get_state()
    nodes      = list(st.asl_nodes)
    tgs        = list(st.talkgroups)
    echo_nodes = list(st.echo_nodes)
    ok, msg = _write_conf(nodes, tgs, echo_nodes)
    if ok:
        return True, f"Saved {len(sanitized)} M17 reflectors"
    return False, msg

def _asterisk(cmd_str: str) -> None:
    if _has_ctrl_chars(cmd_str):
        log.warning("asterisk: rejected command with control characters: %r", cmd_str)
        return
    out, ok = ami_command(cmd_str, timeout=5, priority=True)
    if not ok:
        log.warning("asterisk: link-control command failed: %r -> %r", cmd_str, out)
    time.sleep(0.1)

def _dvs(subcmd: str, arg=None):
    if not get_state().has_dvs:
        return False, "dvswitch.sh not found"
    if arg is not None and _has_ctrl_chars(str(arg)):
        log.warning("dvswitch: rejected %s arg with control characters: %r", subcmd, arg)
        return False, "rejected: illegal characters in argument"
    if subcmd == "mode":
        _invalidate_dmr_net_tune()
    cmd = ["bash", DVS_PATH, subcmd]
    if arg is not None:
        cmd.append(str(arg))
    out, rc = run(cmd, timeout=15 if subcmd in ("mode", "tune") else 10)
    return rc == 0, out

def _echolink_to_asl(node: str) -> str:
    return "3" + str(node).strip().zfill(6)

def _connect(node: str) -> None:
    _asterisk(f"rpt cmd {_cfg.asl_node} ilink 3 {node}")

def _disconnect(node: str) -> None:
    _asterisk(f"rpt cmd {_cfg.asl_node} ilink 1 {node}")

def _disconnect_all() -> None:
    _asterisk(f"rpt cmd {_cfg.asl_node} ilink 6")
    time.sleep(0.2)
    _asterisk(f"rpt cmd {_cfg.asl_node} ilink 6")
    time.sleep(0.2)

_detection_cache: Dict[str, Tuple[Optional[bool], float]] = {
    "stfu":   (None, 0.0),
    "echo":   (None, 0.0),
    "sysmon": (None, 0.0),
    "m17":    (None, 0.0),
}
_STFU_CACHE_TTL   = 60.0
_ECHO_CACHE_TTL   = 120.0
_SYSMON_PORT      = 9999
_SYSMON_CACHE_TTL = 15.0
_M17_CACHE_TTL    = 60.0
_detection_lock = threading.Lock()

_YSF_HOSTS_PATH  = "/var/lib/mmdvm/YSFHosts.txt"
_YSF_HOSTS_TTL   = 300.0
_ysf_hosts_cache: "dict[str, str] | None" = None
_ysf_hosts_ts    = 0.0
_ysf_hosts_lock  = threading.Lock()
_ysf_hosts_warned = False

def _cached_detect(key: str, ttl: float, probe_fn) -> bool:
    with _detection_lock:
        cached_val, cached_at = _detection_cache[key]
        if cached_val is not None and (time.monotonic() - cached_at) < ttl:
            return cached_val
    result = probe_fn()
    with _detection_lock:
        _detection_cache[key] = (result, time.monotonic())
    return result

def _detect_asl() -> bool:
    return bool(run(["which", "asterisk"], timeout=4)[0]) and Path(ASL_CONF).is_file()

def _detect_dvs() -> bool:
    return Path(DVS_PATH).is_file()

def _find_dvs_path() -> "str | None":
    for p in _DVS_SEARCH_PATHS:
        if Path(p).is_file():
            return p
    return None

def _detect_stfu() -> bool:
    def _probe_stfu() -> bool:
        if shutil.which("systemctl") and                run(["systemctl", "is-active", "stfu.service"], timeout=3)[1] == 0:
            return True
        if Path("/opt/STFU/STFU").is_file():
            out, _ = run(["pgrep", "-x", "STFU"], timeout=3)
            if out.strip():
                return True
        return False
    return _cached_detect("stfu", _STFU_CACHE_TTL, _probe_stfu)

def _detect_echo() -> bool:
    def _probe():
        out, ok = ami_command("module show like chan_echolink", timeout=3)
        return ok and "chan_echolink" in out.lower() and "0 modules loaded" not in out
    return _cached_detect("echo", _ECHO_CACHE_TTL, _probe)

def _detect_sysmon() -> bool:
    import socket as _socket
    def _probe():
        try:
            s = _socket.create_connection(("127.0.0.1", _SYSMON_PORT), timeout=1.0)
            s.close()
            return True
        except OSError:
            return False
    return _cached_detect("sysmon", _SYSMON_CACHE_TTL, _probe)

def _detect_m17() -> bool:

    def _probe_m17() -> bool:
        if shutil.which("systemctl") and                run(["systemctl", "status", M17_SERVICE], timeout=3)[1] in (0, 3):
            return True
        if Path("/opt/USRP2M17/USRP2M17").is_file():
            return True
        return False
    return _cached_detect("m17", _M17_CACHE_TTL, _probe_m17)

def action_sysmon_status() -> dict:
    return {"running": _detect_sysmon(), "port": _SYSMON_PORT}

def _load_ysf_hosts() -> "dict[str, str]":
    global _ysf_hosts_cache, _ysf_hosts_ts, _ysf_hosts_warned
    with _ysf_hosts_lock:
        if _ysf_hosts_cache is not None and                (time.monotonic() - _ysf_hosts_ts) < _YSF_HOSTS_TTL:
            return _ysf_hosts_cache
    result: "dict[str, str]" = {}
    try:
        with open(_YSF_HOSTS_PATH, "r", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(";")
                if len(parts) >= 2:
                    room_id   = parts[0].strip()
                    room_name = parts[1].strip()
                    if room_id and room_name:
                        result[room_id]   = room_name
                        result[room_name] = room_name
    except OSError:
        if not _ysf_hosts_warned:
            _ysf_hosts_warned = True
            st = get_state()
            set_state(conf_warnings=list(st.conf_warnings) + [
                f"YSFHosts.txt not found at {_YSF_HOSTS_PATH} — room names will show as raw TG IDs"
            ])
    with _ysf_hosts_lock:
        _ysf_hosts_cache = result
        _ysf_hosts_ts    = time.monotonic()
    return result

def _resolve_ysf_name(tg: str, ambe_mode: str) -> str:
    if ambe_mode.upper() in ("YSFN", "YSFW") and tg.startswith("9"):
        return ""
    return _load_ysf_hosts().get(tg, "")

def _read_abinfo() -> "dict | None":
    try:
        files = _glob.glob("/tmp/ABInfo_*.json")
        if not files:
            return None
        newest = max(files, key=os.path.getmtime)
        return json.loads(Path(newest).read_text())
    except Exception:
        return None

_CALLSIGN_SEARCH_PATHS = [
    "/opt/MMDVM_Bridge/DVSwitch.ini",
    "/etc/dvswitch/DVSwitch.ini",
    "/etc/dvswitch/MMDVM.ini",
    "/opt/MMDVM_Bridge/MMDVM.ini",
    "/etc/dvswitch/MMDVM_Bridge.ini",
    "/opt/MMDVM_Bridge/MMDVM_Bridge.ini",
    "/etc/dvswitch/DMRGateway.ini",
    "/opt/MMDVM_Bridge/DMRGateway.ini",
]

def _read_callsign() -> str:
    for path in _CALLSIGN_SEARCH_PATHS:
        try:
            f = open(path, "r", errors="replace")
        except OSError:
            continue
        with f:
            in_general = False
            for raw in f:
                line = raw.strip()
                if not line or line[0] in ("#", ";"):
                    continue
                if line.startswith("[") and "]" in line:
                    in_general = line[1:line.index("]")].strip().upper() == "GENERAL"
                    continue
                if in_general and "=" in line:
                    key, _, val = line.partition("=")
                    if key.strip().lower() == "callsign":
                        cs = val.split(";")[0].split("#")[0].strip()
                        if cs:
                            return cs.upper()
    return ""

_DVSWITCH_INI = "/opt/MMDVM_Bridge/DVSwitch.ini"

def detect_stfu_server() -> dict:
    try:
        text = Path(_DVSWITCH_INI).read_text(errors="replace")
    except OSError as exc:
        return {"name": None, "address": "", "port": "", "extra": [],
                "error": f"DVSwitch.ini not readable: {exc}"}

    kv: Dict[str, str] = {}
    in_stfu = False
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and "]" in line:
            section = line[1:line.index("]")].strip().upper()
            in_stfu = section in ("STFU", "BRANDMEISTER")
            continue
        if in_stfu and "=" in line:
            k, _, v = line.partition("=")
            kv[k.strip().lower()] = v.strip()

    address = kv.get("bmaddress", "")
    if not address:
        return {"name": None, "address": "", "port": "", "extra": [],
                "error": "[STFU] section not found or missing BMAddress in DVSwitch.ini"}

    extra = []
    if kv.get("userid"):
        extra.append(f"ID {kv['userid']}")
    if kv.get("starttg"):
        extra.append(f"TG {kv['starttg']}")

    return {
        "name":    "BrandMeister",
        "address": address,
        "port":    kv.get("bmport", ""),
        "extra":   extra,
        "error":   None,
    }

_perm_links_cache: frozenset        = frozenset()
_perm_links_ts:    float            = 0.0
_perm_links_lock                    = threading.Lock()
_PERM_LINKS_TTL                     = 30.0

def _read_perm_links() -> frozenset:
    global _perm_links_cache, _perm_links_ts
    with _perm_links_lock:
        if time.monotonic() - _perm_links_ts < _PERM_LINKS_TTL:
            return _perm_links_cache
    try:
        node_id = _cfg.asl_node
        in_node  = False
        result   = set()
        with open(ASL_CONF, "r", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith(";") or line.startswith("#"):
                    continue
                if line.startswith("[") and "]" in line:
                    sec = line[1:line.index("]")].strip()
                    in_node = (sec == node_id)
                    continue
                if not in_node:
                    continue
                if "=" in line:
                    k, _, v = line.partition("=")
                    if k.strip().lower() == "nodes":
                        for tok in re.split(r"[,\s]+", v.strip()):
                            tok = tok.strip()
                            if tok.isdigit():
                                result.add(tok)
                        break
        fresh = frozenset(result)
    except Exception:
        fresh = frozenset()
    with _perm_links_lock:
        _perm_links_cache = fresh
        _perm_links_ts    = time.monotonic()
    return fresh

_KEYED_RE    = re.compile(r"RPT_(?:RX|TX)KEYED\s*=\s*1", re.IGNORECASE)
_LINKS_RE    = re.compile(r"RPT_LINKS\s*=\s*(.+)", re.IGNORECASE)
_NUMLINKS_RE = re.compile(r"RPT_NUMLINKS\s*=\s*(\d+)", re.IGNORECASE)

_connecting_lock  = threading.Lock()
_connecting       = False
_multi_link_count = 0

_poll_ok = True

def _poll_asl_state() -> "Tuple[bool, Optional[str], bool, FrozenSet[str]]":
    global _multi_link_count, _poll_ok
    out, ok = ami_command(f"{_AMI_RPT_SHOW_VARS} {_cfg.asl_node}", timeout=2)
    _poll_ok = ok
    if not ok or not out:
        return False, None, False, frozenset()
    keyed = bool(_KEYED_RE.search(out))
    linked_node: Optional[str] = None

    bridge_set = set(filter(None, _cfg.bridge_nodes))
    bridge_linked_nodes: Set[str] = set()
    m = _LINKS_RE.search(out)
    if m:
        raw = m.group(1).strip()
        if "," in raw:
            raw = raw[raw.index(",")+1:].strip()
        raw_tokens = re.split(r"[,\s]+", raw)
        for tok in raw_tokens:
            tok = tok.strip()
            if not tok or tok == "(none)":
                continue
            if tok[0] in ("T", "R") and len(tok) > 1 and tok[1:].isdigit():
                tok = tok[1:]
            if not tok.isdigit() or tok == "0":
                continue
            if tok in bridge_set:
                bridge_linked_nodes.add(tok)
                continue
            if linked_node is None:
                linked_node = tok
    bridge_linked = bool(bridge_linked_nodes)
    nm = _NUMLINKS_RE.search(out)
    page = get_state_fields("page")["page"]
    with _connecting_lock:
        connecting_now = _connecting
    if nm and page in ("ASL", "ECHO") and not connecting_now:
        if int(nm.group(1)) > 1:
            _multi_link_count += 1
            if _multi_link_count >= 2:
                _multi_link_count = 0
                log.warning("RPT_NUMLINKS > 1 — disconnecting extra links")
                _keep = linked_node
                def _drop_extras(keep=_keep):
                    global _connecting
                    with _connecting_lock:
                        _connecting = True
                    try:
                        st2 = get_state()
                        _bridge_set = set(filter(None, _cfg.bridge_nodes))
                        for _, nd, *_r in st2.asl_nodes:
                            if nd and nd != TG_BLANK_ADDR and nd != keep and nd not in _bridge_set:
                                log.warning("multi-link cleanup: dropping %s (keeping %s)", nd, keep)
                                _disconnect(nd)
                        for _, nd, *_r in st2.echo_nodes:
                            if nd and nd != TG_BLANK_ADDR:
                                asl_nd = _echolink_to_asl(nd)
                                if asl_nd != keep:
                                    log.warning("multi-link cleanup: dropping echolink %s (keeping %s)", asl_nd, keep)
                                    _disconnect(asl_nd)
                        _disconnect(ASL_PARROT_NODE)
                        time.sleep(1.0)
                    finally:
                        with _connecting_lock:
                            _connecting = False
                threading.Thread(target=_drop_extras, daemon=True).start()
        else:
            _multi_link_count = 0
    else:
        _multi_link_count = 0
    return keyed, linked_node, bridge_linked, frozenset(bridge_linked_nodes)

def _dvs_settle() -> None:
    global _dvs_settle_until
    _dvs_settle_until = time.monotonic() + _DVS_SETTLE_MS / 1000.0

_bridge_slot_last_reconnect = {BRIDGE_SLOT_DIGITAL: 0.0, BRIDGE_SLOT_M17: 0.0}
_bridge_slot_down_polls     = {BRIDGE_SLOT_DIGITAL: 0,   BRIDGE_SLOT_M17: 0}
_BRIDGE_RECONNECT_COOLDOWN = 8.0
_BRIDGE_DOWN_THRESHOLD     = 3

def _bridge_watchdog(bridge_linked_nodes: "FrozenSet[str]") -> None:

    st = get_state_fields("page", "has_asl", "has_m17")
    page = st["page"]

    active_slot = None
    for slot, pages in BRIDGE_SLOT_PAGES.items():
        if page in pages:
            active_slot = slot
            break

    for slot in _bridge_slot_down_polls:
        if slot != active_slot:
            _bridge_slot_down_polls[slot] = 0

    if active_slot is None or not st["has_asl"]:
        return
    if active_slot == BRIDGE_SLOT_M17 and not st["has_m17"]:
        return

    node = _cfg.bridge_nodes[active_slot] if active_slot < len(_cfg.bridge_nodes) else ""
    if not node:

        _bridge_slot_down_polls[active_slot] = 0
        return

    if node in bridge_linked_nodes:
        _bridge_slot_down_polls[active_slot] = 0
        return

    _bridge_slot_down_polls[active_slot] += 1
    if _bridge_slot_down_polls[active_slot] < _BRIDGE_DOWN_THRESHOLD:
        return
    if (time.monotonic() - _bridge_slot_last_reconnect[active_slot]) < _BRIDGE_RECONNECT_COOLDOWN:
        return

    with _connecting_lock:
        busy = _connecting
    if busy:
        return

    _bridge_slot_last_reconnect[active_slot] = time.monotonic()
    log.warning("watchdog: %s (slot %d, node %s) not linked on %s tab — reconnecting",
                BRIDGE_SLOT_LABELS[active_slot], active_slot, node, page)
    _connect(node)

def _link_poll_loop() -> None:
    INTERVAL     = 1.0
    fails        = 0
    last_detect  = time.monotonic()
    while True:
        t0 = time.monotonic()
        _sd_notify("WATCHDOG=1")
        try:
            keyed, linked_node, bridge_linked, bridge_linked_nodes = _poll_asl_state()
            set_state(keyed=keyed, linked_node=linked_node, bridge_linked=bridge_linked,
                      bridge_linked_nodes=bridge_linked_nodes,
                      perm_link_nodes=_read_perm_links())
            fails = 0 if _poll_ok else fails + 1
            if _poll_ok:
                try:
                    _bridge_watchdog(bridge_linked_nodes)
                except Exception as e:
                    log.warning("_link_poll_loop: watchdog error: %s", e)
        except Exception as e:
            log.warning("_link_poll_loop: poll error: %s", e)
            fails += 1

        if time.monotonic() - last_detect >= 60.0:
            last_detect = time.monotonic()
            try:
                set_state(has_stfu=_detect_stfu(), has_echo=_detect_echo())
            except Exception as e:
                log.warning("_link_poll_loop: capability re-detect error: %s", e)

        interval = INTERVAL if fails == 0 else (5.0 if fails < 5 else 10.0)
        time.sleep(max(0.1, interval - (time.monotonic() - t0)))

def _active_bridge_node(page: str) -> Optional[str]:
    for slot, pages in BRIDGE_SLOT_PAGES.items():
        if page in pages:
            node = _cfg.bridge_nodes[slot] if slot < len(_cfg.bridge_nodes) else ""
            return node or None
    return None

def _enter_digital(page: str, dvs_mode: str = None) -> None:
    dvs_mode = dvs_mode or page
    st = get_state()
    prev_page = st.page

    if prev_page != page:
        _gateway_svc_leave(prev_page, page)

    new_bridge = _cfg.bridge_nodes[BRIDGE_SLOT_DIGITAL] or None
    if st.has_asl:
        if st.page in ("ASL", "ECHO") and st.current_fav and st.current_fav != _cfg.bridge_nodes[BRIDGE_SLOT_DIGITAL]:
            _disconnect(st.current_fav)
        if st.echo_fav and st.echo_fav.strip() and st.echo_fav != TG_BLANK_ADDR:
            _disconnect(_echolink_to_asl(st.echo_fav))

        prev_bridge = _active_bridge_node(prev_page)
        if prev_bridge and prev_bridge != new_bridge:
            _disconnect(prev_bridge)

    if not _gateway_svc_enter(page):
        set_state(page=page, current_fav=None, current_fav_node=None, echo_fav=None,
                  status=f"{page} | Gateway service failed to start — check systemctl",
                  current_dvs_mode=dvs_mode)
        return

    _dvs("tune", TG_DISCONNECT)
    _dvs_settle()
    _dvs("mode", dvs_mode)
    if st.has_asl and new_bridge:
        _connect(new_bridge)
    set_state(page=page, current_fav=None, current_fav_node=None, echo_fav=None,
              status=f"{page} | Ready — pick a TG",
              current_dvs_mode=dvs_mode)

def _enter_asl() -> None:
    _gateway_svc_leave(get_state().page, "ASL")
    _dvs("tune", TG_DISCONNECT)
    if get_state().has_asl:
        _disconnect_all()
        time.sleep(1.0)
    set_state(page="ASL", current_fav=None, current_fav_node=None, echo_fav=None, status="ASL | Ready")

def _enter_echo() -> None:
    _gateway_svc_leave(get_state().page, "ECHO")
    _dvs("tune", TG_DISCONNECT)
    if get_state().has_asl:
        _disconnect_all()
        time.sleep(1.0)
    set_state(page="ECHO", current_fav=None, current_fav_node=None, echo_fav=None, status="Echo | Ready")

def _enter_m17() -> None:
    st = get_state()
    prev_page = st.page

    if prev_page != "M17":
        _gateway_svc_leave(prev_page, "M17")

    new_bridge = _cfg.bridge_nodes[BRIDGE_SLOT_M17] or None
    if st.has_asl:

        bridge_set = set(filter(None, _cfg.bridge_nodes))
        if st.page in ("ASL", "ECHO") and st.current_fav and st.current_fav not in bridge_set:
            _disconnect(st.current_fav)
        if st.echo_fav and st.echo_fav.strip() and st.echo_fav != TG_BLANK_ADDR:
            _disconnect(_echolink_to_asl(st.echo_fav))

        prev_bridge = _active_bridge_node(prev_page)
        if prev_bridge and prev_bridge != new_bridge:
            _disconnect(prev_bridge)

    _dvs("tune", TG_DISCONNECT)

    m17_node = new_bridge
    if st.has_asl and st.has_m17 and m17_node:
        _connect(m17_node)

    set_state(page="M17", current_fav=None, current_fav_node=None, echo_fav=None,
              status="M17 | Ready — pick a reflector")

def _clear_links(
    target_node: Optional[str] = None,
    target_is_echo: bool = False,
    skip_bridge: bool = False,
) -> None:

    st = get_state()
    paced = target_node is not None
    asl_target = (_echolink_to_asl(target_node) if target_is_echo else target_node)                 if target_node else None
    bridge_node = _cfg.bridge_nodes[BRIDGE_SLOT_DIGITAL]
    bridge_set = set(filter(None, _cfg.bridge_nodes))

    if paced and not target_is_echo and st.current_fav and            st.current_fav != bridge_node and st.current_fav != target_node:
        _disconnect(st.current_fav)
        time.sleep(0.3)

    for _, nd, *_r in st.asl_nodes:
        if nd != TG_BLANK_ADDR and nd.strip() and nd not in bridge_set:
            _disconnect(nd)
            if paced:
                time.sleep(0.25)

    for _, nd, *_r in st.echo_nodes:
        if nd != TG_BLANK_ADDR and nd.strip():
            _disconnect(_echolink_to_asl(nd))
            if paced:
                time.sleep(0.25)

    if not paced:
        if st.echo_fav and st.echo_fav.strip() and st.echo_fav != TG_BLANK_ADDR:
            _disconnect(_echolink_to_asl(st.echo_fav))

    if asl_target and asl_target != bridge_node:
        _disconnect(asl_target)
        time.sleep(0.3)

    if not paced or target_node != ASL_PARROT_NODE:
        _disconnect(ASL_PARROT_NODE)
        if paced:
            time.sleep(0.3)

    if not skip_bridge and not paced:
        _disconnect(bridge_node)

    if not paced:
        _asterisk(f"rpt cmd {_cfg.asl_node} ilink 6")
        time.sleep(0.2)
        _asterisk(f"rpt cmd {_cfg.asl_node} ilink 6")
        time.sleep(0.2)

def _clear_foreign_link() -> Optional[str]:
    st = get_state()
    node = st.linked_node
    if not node or node == "0":
        return None

    _dash = st.current_fav_node or (
        _echolink_to_asl(st.echo_fav)
        if st.echo_fav and st.echo_fav.strip() and st.echo_fav != TG_BLANK_ADDR
        else None
    )
    if node == _dash:
        return None
    log.info("Auto-clearing foreign link: node %s", node)
    _disconnect(node)
    set_state(linked_node=None)
    time.sleep(0.3)
    return node

def _fcs_to_tune(room_id: str) -> str:
    s = str(room_id).strip().upper()
    if s.startswith("FCS"):
        s = s[3:]
    if not s.isdigit():
        raise ValueError(f"FCS room ID must be numeric, got: {room_id!r}")
    if s.startswith("9") and len(s) == 6:
        return s
    if len(s) > 5:
        raise ValueError(
            f"FCS room ID too long (max 5 digits or 9xxxxx format), got: {room_id!r}")
    return "9" + s.zfill(5)

def action_switch_tab(page: str) -> Tuple[bool, str]:
    page = page.upper()
    if page in DIGITAL_MODES:
        _enter_digital(page)
        if page == "STFU":
            threading.Thread(
                target=lambda: set_state(stfu_server=detect_stfu_server()),
                daemon=True,
            ).start()
        return True, f"{page} ready — pick a TG"
    if page == "XLX":
        _enter_digital("XLX", dvs_mode="DSTAR")
        set_state(status="XLX | Ready — pick a reflector")
        return True, "XLX ready — pick a reflector"
    if page == "FCS":
        _enter_digital("FCS", dvs_mode="YSF")
        set_state(status="FCS | Ready — pick a room")
        return True, "FCS ready — pick a room"
    if page == "ASL":
        _enter_asl()
        return True, "ASL | Ready"
    if page == "ECHO":
        _enter_echo()
        return True, "Echo | Ready"
    if page == "M17":
        _enter_m17()
        return True, "M17 ready — pick a reflector"
    return False, f"Unknown page '{page}'"

def action_retune_tab(page: str, server_name: str = "") -> Tuple[bool, str]:
    page = page.upper()
    st   = get_state()

    if page == "DMR":
        _enter_digital("DMR")
        target = server_name.strip() or st.active_dmr_server
        if target:
            ok, msg = action_switch_dmr_server(target)
            if not ok:
                return False, msg
            return True, f"DMR re-tuned → {target}"
        return True, "DMR mode re-tuned"

    if page == "STFU":
        _svc_restart("stfu.service")
        _svc_restart("mmdvm_bridge")
        _enter_digital("STFU")
        threading.Thread(
            target=lambda: set_state(stfu_server=detect_stfu_server()),
            daemon=True,
        ).start()
        return True, "STFU mode re-tuned — services restarted"

    if page == "DSTAR":
        _dvs("tune", DSTAR_UNLINK)
        _enter_digital("DSTAR")
        return True, "DSTAR mode re-tuned"

    if page in DIGITAL_MODES:
        _enter_digital(page)
        return True, f"{page} mode re-tuned"

    if page == "XLX":
        _dvs("tune", DSTAR_UNLINK)
        _dvs("tune", TG_DISCONNECT)
        _dvs_settle()
        _dvs("mode", "DSTAR")
        set_state(page="XLX", current_fav=None, current_fav_node=None, echo_fav=None,
                  status="XLX | Ready — pick a reflector",
                  current_dvs_mode="DSTAR")
        return True, "XLX re-tuned"

    if page == "FCS":
        _dvs("tune", TG_DISCONNECT)
        _dvs_settle()
        _dvs("mode", "YSF")
        set_state(page="FCS", current_fav=None, current_fav_node=None, echo_fav=None,
                  status="FCS | Ready — pick a room",
                  current_dvs_mode="YSF")
        return True, "FCS re-tuned"

    if page == "ASL":
        _enter_asl()
        return True, "ASL re-tuned"

    if page == "ECHO":
        _enter_echo()
        return True, "Echo re-tuned"

    if page == "M17":

        _enter_m17()
        return True, "M17 re-tuned"

    return False, f"Unknown page '{page}'"

def action_tune(mode: str, tg: str, name: str) -> Tuple[bool, str]:
    global _connecting
    st = get_state()

    if not tg.strip():
        return False, "TG/address must not be empty"
    if len(tg) > 64:
        return False, f"TG/address too long ({len(tg)} chars; max 64)"
    if _has_ctrl_chars(tg):
        return False, "TG/address contains illegal characters"

    remaining = _dvs_settle_until - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)

    if tg == TG_DISCONNECT or tg == "*88":
        if mode == "DSTAR":
            _dvs("tune", DSTAR_UNLINK)
        _dvs("tune", TG_DISCONNECT)
        _dvs_settle()
        if st.has_asl:
            _clear_foreign_link()
        set_state(page=mode, current_fav=None, current_fav_node=None, echo_fav=None,
                  status=f"{mode} | DISCONNECTED")
        return True, f"{mode} | Disconnected"

    dvs_mode = "YSF" if mode == "FCS" else mode
    try:
        tune_str = _fcs_to_tune(tg) if mode == "FCS" else tg
    except ValueError as exc:
        return False, str(exc)

    _clear_foreign_link()

    if st.has_asl and st.linked_node != _cfg.bridge_nodes[BRIDGE_SLOT_DIGITAL]:
        with _connecting_lock:
            _connecting = True
        try:
            _connect(_cfg.bridge_nodes[BRIDGE_SLOT_DIGITAL])
        finally:
            with _connecting_lock:
                _connecting = False

    _dvs("tune", TG_DISCONNECT)
    _dvs_settle()

    mode_changed = (dvs_mode != st.current_dvs_mode)
    if mode_changed:
        ok_mode, _ = _dvs("mode", dvs_mode)
        if not ok_mode:
            log.warning("action_tune: mode switch to %s failed", dvs_mode)

    remaining = _dvs_settle_until - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)

    ok_tune, out = _dvs("tune", tune_str)
    if not ok_tune:
        return False, f"Tune failed ({tune_str}): {out}"

    bridge_lbl = " | BRIDGE LINKED" if st.has_asl else ""
    label = f"{mode} | {name} | {tg}{bridge_lbl}"
    set_state(
        page=mode,
        status=label,
        current_fav=tune_str if mode == "FCS" else tg,
        current_fav_node=None,
        **({"current_dvs_mode": dvs_mode} if mode_changed else {}),
    )
    return True, f"Tuned: {name} ({tg})"

def action_quick_tune(mode: str, tg: str) -> Tuple[bool, str]:
    tg = tg.strip()
    if not tg:
        return False, "TG/address must not be empty"
    if len(tg) > 64:
        return False, f"TG/address too long ({len(tg)} chars; max 64)"
    return action_tune(mode, tg, f"{mode} {tg}")

def _do_dstar_family_connect(page: str, base: str, module: str, name: str) -> Tuple[bool, str]:
    base   = base.strip().upper()
    module = module.strip().upper()[:1]
    is_xlx = (page == "XLX")
    if not base:
        return False, ("XLX reflector base must not be empty" if is_xlx
                        else "Reflector base must not be empty")
    if not module or not module.isalpha():
        return False, f"Invalid module letter: '{module}'"
    tune_str = f"{base}{module}L"
    st = get_state()
    _clear_foreign_link()
    _dvs("tune", DSTAR_UNLINK)
    _dvs("tune", TG_DISCONNECT)
    _dvs_settle()
    if st.has_asl:
        _connect(_cfg.bridge_nodes[BRIDGE_SLOT_DIGITAL])
    _dvs("mode", "DSTAR")
    remaining = _dvs_settle_until - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)
    ok, out = _dvs("tune", tune_str)
    if not ok:
        fail_label = "XLX" if is_xlx else "D-STAR"
        return False, f"{fail_label} tune failed ({tune_str}): {out}"
    bridge_lbl = " | BRIDGE LINKED" if st.has_asl else ""
    label = f"{page} | {name} | {tune_str}{bridge_lbl}"
    set_state(page=page, status=label, current_fav=tune_str, current_fav_node=None)
    conn_label = "XLX" if is_xlx else "D-STAR"
    return True, f"{conn_label} connected: {name} ({tune_str})"

def action_dstar_connect(base: str, module: str, name: str) -> Tuple[bool, str]:
    return _do_dstar_family_connect("DSTAR", base, module, name)

def action_xlx_connect(name: str, base: str, module: str) -> Tuple[bool, str]:
    return _do_dstar_family_connect("XLX", base, module, name)

def action_dstar_disconnect() -> Tuple[bool, str]:
    _dvs("tune", DSTAR_UNLINK)
    _dvs("tune", TG_DISCONNECT)
    _dvs_settle()
    set_state(current_fav=None, current_fav_node=None, status="DSTAR | Ready")
    return True, "D-STAR disconnected"

def action_xlx_disconnect() -> Tuple[bool, str]:
    _dvs("tune", DSTAR_UNLINK)
    _dvs("tune", TG_DISCONNECT)
    _dvs_settle()
    set_state(current_fav=None, current_fav_node=None, status="XLX | Ready")
    return True, "XLX disconnected"

def _m17_ini_content(callsign: str, refl_name: str, ip: str, module: str) -> str:
    
    return (
        "[M17 Network]\n"
        f"Callsign={callsign}\n"
        f"Address={ip}\n"
        f"Name={refl_name} {module}\n"
        f"LocalPort={_M17_NET_LOCAL_PORT}\n"
        f"DstPort={_M17_NET_DST_PORT}\n"
        f"GainAdjustdB={_M17_GAIN_DB}\n"
        "Daemon=1\n"
        "Debug=0\n"
        "\n"
        "[USRP Network]\n"
        "Address=127.0.0.1\n"
        f"DstPort={_M17_USRP_DST_PORT}\n"
        f"LocalPort={_M17_USRP_LOCAL_PORT}\n"
        f"GainAdjustdB={_M17_GAIN_DB}\n"
        "Debug=0\n"
        "\n"
        "[Log]\n"
        "DisplayLevel=0\n"
        "FileLevel=0\n"
        "FilePath=/var/log/usrp\n"
        "FileRoot=USRP2M17\n"
    )

def _m17_ini_placeholder(callsign: str) -> str:

    return _m17_ini_content(callsign, "DISCONNECTED", "0.0.0.0", "A")

def _effective_callsign(st: "AppState") -> str:
    
    return st.callsign or _cfg.callsign or ""

def _write_m17_ini(content: str) -> Tuple[bool, str]:
    try:
        p = Path(M17_INI_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(content)
        os.replace(tmp, p)
        return True, ""
    except Exception as e:
        return False, str(e)

def action_m17_connect(name: str, base: str, ip: str, module: str) -> Tuple[bool, str]:
    ip     = ip.strip()
    module = module.strip().upper()
    base   = base.strip() or ip
    name   = name.strip() or base

    if not ip:
        return False, "Reflector IP must not be empty"
    if not base:
        return False, "Reflector base must not be empty"
    if _has_ctrl_chars(ip) or _has_ctrl_chars(name) or _has_ctrl_chars(base):
        return False, "Illegal characters in reflector name/base/IP"
    if not (module == "@ALL" or (len(module) == 1 and module.isalpha())):
        return False, f"Invalid module: '{module}' (must be A-Z or @ALL)"

    st = get_state()
    if not st.has_m17:
        return False, "USRP2M17 bridge not detected on this host"

    _clear_foreign_link()

    _dvs("tune", TG_DISCONNECT)

    callsign = _effective_callsign(st)
    ok, err = _write_m17_ini(_m17_ini_content(callsign, base, ip, module))
    if not ok:
        return False, f"Could not write {M17_INI_PATH}: {err}"
    _svc_restart(M17_SERVICE)

    m17_node = _cfg.bridge_nodes[BRIDGE_SLOT_M17]
    if st.has_asl and m17_node:
        _connect(m17_node)
        time.sleep(1.5)

    fav = f"{base}|{module}"
    label = f"M17 | {name} | {base} Mod-{module} ({ip})"
    set_state(page="M17", status=label, current_fav=fav, current_fav_node=(m17_node or None))
    return True, f"M17 connected: {name} ({base} Mod-{module})"

def action_m17_disconnect() -> Tuple[bool, str]:
    
    st = get_state()
    callsign = _effective_callsign(st)
    ok, err = _write_m17_ini(_m17_ini_placeholder(callsign))
    if ok:
        _svc_restart(M17_SERVICE)
    m17_node = _cfg.bridge_nodes[BRIDGE_SLOT_M17]
    if st.has_asl and m17_node:
        _disconnect(m17_node)
    set_state(current_fav=None, current_fav_node=None, status="M17 | Ready — pick a reflector")
    if not ok:
        return False, f"Disconnected link, but ini write failed: {err}"
    return True, "M17 disconnected"

def _do_asl_connect(node: str, name: str):
    node = str(node).strip()
    if not node.isdigit():
        return False, f"Invalid node number: {node}"
    _clear_foreign_link()
    global _connecting
    with _connecting_lock:
        _connecting = True
    try:
        _clear_links(node, target_is_echo=False)
        _connect(node)
        time.sleep(1.5)
        set_state(current_fav=node, current_fav_node=node, echo_fav=None, status=f"ASL | {name} | {node}")
    finally:
        with _connecting_lock:
            _connecting = False
    return True, f"Connected {name} ({node})"

def action_connect_by_number(node: str) -> Tuple[bool, str]:
    node = str(node).strip()
    if not node.isdigit():
        return False, f"Invalid node number: {node}"
    return _do_asl_connect(node, f"Node {node}")

def action_asl_connect(node: str, name: str) -> Tuple[bool, str]:
    return _do_asl_connect(str(node).strip(), name)

def action_asl_disconnect_current() -> Tuple[bool, str]:
    st = get_state()
    if st.current_fav and st.current_fav not in set(filter(None, _cfg.bridge_nodes)):
        _disconnect(st.current_fav)
    _clear_foreign_link()
    set_state(current_fav=None, current_fav_node=None, status="ASL | Ready")
    return True, "ASL disconnected"

def action_disc_perm_link() -> Tuple[bool, str]:
    st = get_state()
    node = st.linked_node
    if not node:
        return False, "No active link to disconnect"
    _disconnect(node)
    set_state(linked_node=None)
    return True, f"Link to node {node} disconnected"

def _do_echo_connect(node: str, name: str):
    node = str(node).strip()
    if not node.isdigit():
        return False, f"Invalid node number: {node}"
    _clear_foreign_link()
    global _connecting
    with _connecting_lock:
        _connecting = True
    try:
        asl_node = _echolink_to_asl(node)
        _clear_links(node, target_is_echo=True)
        _connect(asl_node)
        time.sleep(1.5)
        set_state(echo_fav=node, status=f"Echo | {name} | {node}")
    finally:
        with _connecting_lock:
            _connecting = False
    return True, f"Echo connected {name} ({node})"

def action_echo_connect(node: str, name: str) -> Tuple[bool, str]:
    return _do_echo_connect(str(node).strip(), name)

def action_echo_connect_by_number(node: str) -> Tuple[bool, str]:
    node = str(node).strip()
    if not node.isdigit():
        return False, f"Invalid node number: {node}"
    if len(node) > 6:
        return False, f"EchoLink node numbers are 1-6 digits (got '{node}')"
    return _do_echo_connect(node, f"Node {node}")

def action_echo_disconnect() -> Tuple[bool, str]:
    st = get_state()
    if st.echo_fav and st.echo_fav.strip() and st.echo_fav != TG_BLANK_ADDR:
        _disconnect(_echolink_to_asl(st.echo_fav))
    _clear_foreign_link()
    set_state(echo_fav=None, status="Echo | Ready")
    return True, "Echo disconnected"

def _svc_restart(name: str) -> None:
    rc = run(["systemctl", "restart", name], timeout=15)[1]
    if rc != 0:
        log.warning("_svc_restart: systemctl restart %s failed (rc=%d) — trying pkill", name, rc)
        proc = name.replace(".service", "")
        run(["pkill", "-x", proc], timeout=5)

_GATEWAY_SERVICE_MAP = {
    "DSTAR": "ircddbgatewayd.service",
    "XLX":   "ircddbgatewayd.service",
    "YSF":   "ysfgateway.service",
    "FCS":   "ysfgateway.service",
    "P25":   "p25gateway.service",
    "NXDN":  "nxdngateway.service",
    "STFU":  "stfu.service",
}

_GATEWAY_READY_TIMEOUT = 5.0
_GATEWAY_READY_POLL    = 0.25

_gateway_svc_locks: Dict[str, threading.Lock] = {}
_gateway_svc_locks_guard = threading.Lock()

def _gateway_svc_lock(name: str) -> threading.Lock:
    with _gateway_svc_locks_guard:
        lock = _gateway_svc_locks.get(name)
        if lock is None:
            lock = threading.Lock()
            _gateway_svc_locks[name] = lock
        return lock

def _svc_is_active(name: str) -> bool:
    rc = run(["systemctl", "is-active", "--quiet", name], timeout=3)[1]
    return rc == 0

def _svc_stop(name: str) -> None:
    rc = run(["systemctl", "stop", name], timeout=10)[1]
    if rc != 0:
        log.warning("_svc_stop: systemctl stop %s failed (rc=%d)", name, rc)
    else:
        log.info("_svc_stop: stopped %s (tab left)", name)

def _svc_start_and_wait(name: str, timeout: float = _GATEWAY_READY_TIMEOUT) -> bool:
    rc = run(["systemctl", "start", name], timeout=10)[1]
    if rc != 0:
        log.warning("_svc_start_and_wait: systemctl start %s failed (rc=%d)", name, rc)
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _svc_is_active(name):
            return True
        time.sleep(_GATEWAY_READY_POLL)
    log.warning("_svc_start_and_wait: %s did not report active within %.1fs", name, timeout)
    return False

def _gateway_svc_leave(prev_page: str, next_page: str) -> None:
    svc = _GATEWAY_SERVICE_MAP.get(prev_page)
    if not svc or _GATEWAY_SERVICE_MAP.get(next_page) == svc:
        return
    def _worker():
        with _gateway_svc_lock(svc):
            _svc_restart(svc)
    threading.Thread(target=_worker, daemon=True, name=f"svc-restart-{svc}").start()

def _gateway_svc_enter(page: str) -> bool:
    svc = _GATEWAY_SERVICE_MAP.get(page)
    if not svc:
        return True
    with _gateway_svc_lock(svc):
        if _svc_is_active(svc):
            return True
        log.info("_gateway_svc_enter: starting %s for %s tab", svc, page)
        return _svc_start_and_wait(svc)

def _graceful_notify(st) -> None:
    if st.page in ("DSTAR", "XLX"):
        _dvs("tune", DSTAR_UNLINK)
    _dvs("tune", TG_DISCONNECT)
    time.sleep(0.1)

    if st.has_asl:
        _asterisk(f"rpt cmd {_cfg.asl_node} ilink 6")
        time.sleep(0.15)
        _asterisk(f"rpt cmd {_cfg.asl_node} ilink 6")
        time.sleep(0.15)

def _hard_restart_stack(st) -> None:
    _svc_restart("analog_bridge")
    _svc_restart("mmdvm_bridge")
    _invalidate_dmr_net_tune()
    if st.has_asl:
        _svc_restart("asterisk")

    time.sleep(2.0)

    mode = st.current_dvs_mode or "DMR"
    dvs_mode = "YSF" if mode == "FCS" else mode
    if dvs_mode in DIGITAL_MODES:
        _dvs("mode", dvs_mode)

def action_disconnect_all() -> Tuple[bool, str]:
    st = get_state()
    _graceful_notify(st)
    _hard_restart_stack(st)
    set_state(current_fav=None, current_fav_node=None, echo_fav=None, linked_node=None,
              status=f"{st.page} | RESET")
    return True, "Emergency disconnect — services restarted"

def _seed_dmr_tgs() -> None:
    global _status_etag
    st  = get_state()
    srv = st.active_dmr_server
    if not srv:
        with _lock:
            _status_etag = ""
        return
    key        = _server_key(srv)
    server_tgs = st.dmr_server_tgs.get(key, [])
    _blank_dmr4 = [("DMR", TG_BLANK_NAME, TG_BLANK_ADDR, "")]
    padded     = (server_tgs + _blank_dmr4 * 10)[:10]
    new_tgs    = [t for t in st.talkgroups if t[0] != "DMR"] + padded
    set_state(talkgroups=new_tgs)
    with _lock:
        _status_etag = ""

def action_switch_dmr_server(server_name: str) -> Tuple[bool, str]:
    global _dmr_switch_time, _dmr_last_net_tune, _status_etag
    st = get_state()
    if st.page not in ("DMR", "STFU"):
        return False, (f"Server switch rejected — current page is {st.page!r}, "
                       f"not DMR/STFU")
    srv = next((s for s in st.dmr_servers if s["name"] == server_name), None)
    if not srv:
        return False, f"Unknown DMR server '{server_name}'"
    tune_str = f"{srv['password']}@{srv['address']}"

    with _lock:
        _same_net = bool(_dmr_last_net_tune) and tune_str == _dmr_last_net_tune
    key = _server_key(server_name)
    server_tgs = st.dmr_server_tgs.get(key, [])
    _blank_dmr4 = [("DMR", TG_BLANK_NAME, TG_BLANK_ADDR, "")]
    padded = (server_tgs + _blank_dmr4 * 10)[:10]
    new_tgs = [t for t in st.talkgroups if t[0] != "DMR"] + padded
    tgs_empty = all(t[2] == TG_BLANK_ADDR for t in padded)
    if _same_net:
        set_state(active_dmr_server=server_name,
                  talkgroups=new_tgs, current_dvs_mode="DMR")
        with _lock:
            _status_etag = ""
        log.info("DMR switch skipped — '%s' resolves to the network already "
                 "tuned", server_name)
        return True, (f"Already connected — {server_name}|same_net"
                      + ("|tgs_empty" if tgs_empty else ""))

    _dvs("tune", TG_DISCONNECT)
    time.sleep(0.5)
    with _lock:
        _dmr_switch_time = time.monotonic()
    ok, out = _dvs("tune", tune_str)
    if not ok:
        _invalidate_dmr_net_tune()
        return False, f"Server switch failed: {out}"
    with _lock:
        _dmr_last_net_tune = tune_str
    set_state(active_dmr_server=server_name, current_fav=None, current_fav_node=None,
              talkgroups=new_tgs, current_dvs_mode="DMR")
    with _lock:
        _status_etag = ""
    return True, f"Switched to {server_name}" + ("|tgs_empty" if tgs_empty else "")

_REMOTE_CMD_PATH = "/opt/MMDVM_Bridge/RemoteCommand"
_REMOTE_CMD_HOST = "127.0.0.1"
_REMOTE_CMD_PORT = "54321"

_dmr_switch_time: float = 0.0

_dmr_last_net_tune: str = ""

def _invalidate_dmr_net_tune() -> None:
    global _dmr_last_net_tune
    with _lock:
        _dmr_last_net_tune = ""

_DMR_OPTIMISTIC_SECS = 14.0

def _proc_udp_has_foreign(port_hex_set: set) -> bool:
    for path in ("/proc/net/udp6", "/proc/net/udp"):
        try:
            with open(path) as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 4:
                        continue
                    local = parts[1]
                    remote = parts[2]
                    lport = local.rsplit(":", 1)[-1].upper()
                    raddr = remote.split(":")[0]
                    if lport in port_hex_set and raddr not in ("00000000", "0" * 32, ""):
                        return True
        except OSError:
            continue
    return False

def _dmr_remote_port_hex() -> set:
    ports = set()
    try:
        text = Path(_DVSWITCH_INI).read_text(errors="replace")
        section = None
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("[") and "]" in line:
                section = line[1:line.index("]")].strip().upper()
            if section in ("DMR", "STFU", "BRANDMEISTER") and "=" in line:
                k, _, v = line.partition("=")
                k = k.strip().lower()
                v = v.split(";")[0].strip()
                if k == "bmport" and v.isdigit():
                    ports.add(format(int(v), "04X"))
    except Exception:
        pass
    for p in (62030, 62031, 54006):
        ports.add(format(p, "04X"))
    return ports

def _probe_remote_command() -> Optional[bool]:
    if not Path(_REMOTE_CMD_PATH).is_file():
        return None
    try:
        out, rc = run(
            [_REMOTE_CMD_PATH, _REMOTE_CMD_HOST, _REMOTE_CMD_PORT, "show"],
            timeout=3,
        )
        if rc == 0 and out.strip():
            return True
        return None
    except Exception:
        return None

def action_dmr_server_ready() -> dict:
    port_hexes = _dmr_remote_port_hex()
    if _proc_udp_has_foreign(port_hexes):
        return {"ready": True, "method": "proc"}

    rc_result = _probe_remote_command()
    if rc_result is True:
        return {"ready": True, "method": "remote"}

    with _lock:
        elapsed = time.monotonic() - _dmr_switch_time
        dmr_time = _dmr_switch_time
    if dmr_time > 0 and elapsed >= _DMR_OPTIMISTIC_SECS:
        return {"ready": True, "method": "timeout_optimistic"}

    return {"ready": False, "method": "waiting"}

_EVENT_SCRIPT_PATH   = "/usr/local/bin/asl_dvs_event.sh"
_EVENT_SCRIPT_COMPAT = "/tmp/asl_dvs_event.sh"

def _write_event_script() -> None:
    script = (
        "#!/bin/sh\n"
        f"curl -s -m 2 http://127.0.0.1:{_cfg.port}/api/event > /dev/null 2>&1 &\n"
    )
    for path in (_EVENT_SCRIPT_PATH, _EVENT_SCRIPT_COMPAT):
        try:
            p = Path(path)
            if path == _EVENT_SCRIPT_PATH and p.is_file() and p.read_text() == script:
                log.info("Event script up to date at %s — write skipped", path)
                continue
            p.write_text(script)
            p.chmod(0o755)
            log.info("Event script written to %s", path)
        except Exception as e:
            log.warning("Could not write event script %s: %s", path, e)

def action_handle_event() -> None:
    global _status_etag
    try:
        keyed, linked_node, bridge_linked, bridge_linked_nodes = _poll_asl_state()
        set_state(keyed=keyed, linked_node=linked_node, bridge_linked=bridge_linked,
                  bridge_linked_nodes=bridge_linked_nodes)
    except Exception as e:
        log.warning("action_handle_event poll failed: %s", e)
    with _lock:
        _status_etag = ""

def action_get_keyed() -> dict:
    st = get_state()
    _dashboard_linked = st.current_fav or (
        _echolink_to_asl(st.echo_fav)
        if st.echo_fav and st.echo_fav.strip() and st.echo_fav != TG_BLANK_ADDR
        else None
    )
    on_perm  = bool(st.linked_node and st.linked_node != _dashboard_linked)
    is_known = bool(on_perm and st.linked_node in st.perm_link_nodes)
    return {
        "keyed":          st.keyed,
        "linked_node":    st.linked_node,
        "on_perm_link":   on_perm,
        "perm_link_node": st.linked_node if on_perm else None,
        "is_known_perm":  is_known,
    }

def build_status() -> dict:
    st = get_state_fields(
        "page", "status", "current_fav", "has_asl", "has_dvs", "has_stfu",
        "has_echo", "echo_fav", "linked_node", "asl_nodes", "echo_nodes",
        "callsign", "stfu_server", "dmr_servers", "active_dmr_server",
        "conf_warnings", "has_m17",
    )

    return {
        "page":              st["page"],
        "status":            st["status"],
        "current_fav":       st["linked_node"] if (st["page"] == "ASL" and not st["current_fav"] and st["linked_node"]) else st["current_fav"],
        "has_asl":           st["has_asl"],
        "has_dvs":           st["has_dvs"],
        "has_stfu":          st["has_stfu"],
        "has_echo":          st["has_echo"],
        "has_m17":           st["has_m17"],
        "echo_fav":          st["echo_fav"],
        "asl_node":          _cfg.asl_node,
        "enabled_tabs":      _cfg.enabled_tabs_sorted,
        "asl":               [{"name": n, "node": nd} for n, nd, *_ in st["asl_nodes"]],
        "echo":              [{"name": n, "node": nd} for n, nd, *_ in st["echo_nodes"]],
        "uptime_seconds":    int(time.monotonic() - _start_time),
        "callsign":          st["callsign"],
        "stfu_server":       dict(st["stfu_server"]),
        "dmr_servers":       list(st["dmr_servers"]),
        "active_dmr_server": st["active_dmr_server"],
        "conf_warnings":     list(st["conf_warnings"]),
    }

def action_get_dmr_servers() -> list:
    return list(get_state().dmr_servers)

def action_get_dmr_server_tgs() -> dict:
    st = get_state()
    return {k: [{"name":n,"tg":t} for _,n,t,_u in v]
            for k, v in st.dmr_server_tgs.items()}

def action_get_talkgroups() -> list:

    tgs = _snap("talkgroups")
    return [{"mode": m, "name": n, "tg": t, "url": u} for m, n, t, u in tgs]

def action_get_asl_nodes() -> list:
    nodes = _snap("asl_nodes")
    return [{"name": n, "node": nd} for n, nd, *_ in nodes]

def action_get_echo_nodes() -> list:
    nodes = _snap("echo_nodes")
    return [{"name": n, "node": nd} for n, nd, *_ in nodes]

def action_get_xlx_reflectors() -> list:
    refs = _snap("xlx_reflectors")
    return [{"name": n, "tg": t, "url": u} for n, t, u in refs]

def action_get_m17_reflectors() -> list:
    refs = _snap("m17_reflectors")
    return [{"name": n, "base": b, "module": m, "ip": i, "url": u}
            for n, b, m, i, u in refs]

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>ASL-DVS Node Control</title>
<style>
/* ── :root variables ── */
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
  --lime: #d4ff00;
  --lime-dim: #425200;
  --pink: #ff44cc;
  --pink-dim: #700050;
  --fcs: #00c4a0;
  --fcs-dim: #004840;
  --text: #d0dff0;
  --text-bright: #f0f8ff;
  --muted: #4a6080;
  --mono: 'Courier New', Courier, monospace;
  --sans: Arial, Helvetica, sans-serif;
}

/* ── Body + background ── */
* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}
body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--sans);
  min-height: 100vh;
  padding-bottom: 3rem;
}

/* ── Header + logo ── */
header {
  background: linear-gradient(90deg, #0f1a2e, #161e2e 50%, #0f1a2e);
  border-bottom: 2px solid var(--amber);
  padding: .45rem 1rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .5rem;
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: 0 2px 0 rgba(255,208,64,.25), 0 6px 30px rgba(0,0,0,.7);
}
.hdr-left {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex-shrink: 1;
}
.hdr-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  flex-shrink: 0;
  white-space: nowrap;
  line-height: 1.4;
}
.logo {
  font-family: var(--mono);
  font-size: 1.21rem;
  color: var(--amber);
  letter-spacing: .1em;
  text-shadow: 0 0 10px rgba(255,208,64,.9), 0 0 30px rgba(255,208,64,.5), 0 0 60px rgba(255,208,64,.2);
}
.logo-sub {
  font-size: .715rem;
  letter-spacing: .22em;
  text-transform: uppercase;
  color: var(--amber);
  margin-top: .1rem;
}
#hdr-uptime {
  font-family: var(--mono);
  font-size: .792rem;
  color: var(--amber);
  letter-spacing: .08em;
  text-shadow: 0 0 8px rgba(255,208,64,.5);
  white-space: nowrap;
}
/* ── Offline bar ── */
body.offline header {
  opacity: .4;
  transition: opacity .5s;
}
#offline-bar {
  display: none;
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 1000;
  background: #3a0a0a;
  border-bottom: 1px solid #8b1a1a;
  color: #ff6b6b;
  font-family: var(--mono);
  font-size: .858rem;
  text-align: center;
  padding: .35rem 1rem;
  letter-spacing: .06em;
}
body.offline #offline-bar {
  display: block;
}
#perm-link-bar {
  display: none;
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 999;
  background: rgba(255,170,34,.12);
  border-bottom: 1px solid rgba(255,170,34,.35);
  color: var(--amber);
  font-family: var(--mono);
  font-size: .78rem;
  text-align: center;
  padding: .32rem 1rem;
  letter-spacing: .07em;
}
body.perm-linked #perm-link-bar {
  display: block;
}
body.offline.perm-linked #perm-link-bar {
  top: 1.65rem;   /* slide below the offline bar when both are visible */
}

/* ── Layout ── */
.wrap {
  max-width: 860px;
  margin: 0 auto;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: .55rem;
}
/* Flex children must be allowed to shrink below content width so the
   tab bar's overflow-x:auto creates a local scroll context rather than
   expanding the page width and causing the whole page to scroll. */
.wrap > div { min-width: 0; }
.sec-lbl {
  font-size: .66rem;
  letter-spacing: .28em;
  text-transform: uppercase;
  color: #5a7898;
}
.sec-lbl-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: .2rem;
  border-bottom: 1px solid var(--border);
  margin-bottom: .3rem;
  min-height: 2.4rem;
}

/* ── TG indicator ── */
#tg-indicator {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  font-family: var(--mono);
  font-size: 1.21rem;
  font-weight: bold;
  padding: .1rem .3rem;
  border-radius: 3px;
  border: 1px solid var(--border2);
  color: #3a5278;
  background: transparent;
  letter-spacing: .04em;
  line-height: 1.2;
  transition: color .2s, border-color .2s, background .2s, box-shadow .2s, text-shadow .2s;
  display: flex;
  flex-direction: row;
  align-items: center;
  white-space: nowrap;
  max-width: min(60vw, 340px);
  gap: .3rem;
}
#tg-value {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #fff;
}
#tg-indicator.ind-rx #tg-value { color: #ffd700; }
/* confirmed: one-shot glow animation */
#tg-indicator.ind-confirmed {
  animation: confirm-flash .65s ease-out forwards;
}
@keyframes confirm-flash {
  0%   { box-shadow: 0 0 18px rgba(0,255,176,.85), inset 0 0 10px rgba(0,255,176,.2); }
  100% { box-shadow: none; }
}
#tg-indicator.ind-idle{color:#3a5278;border-color:var(--border2)}
#tg-indicator.ind-asl,#tg-indicator.ind-dmr,#tg-indicator.ind-stfu,#tg-indicator.ind-ysf,#tg-indicator.ind-fcs,#tg-indicator.ind-p25,#tg-indicator.ind-nxdn,#tg-indicator.ind-dstar,#tg-indicator.ind-xlx,#tg-indicator.ind-m17,#tg-indicator.ind-echo{color:var(--mc);border-color:rgba(var(--mc-rgb),.4);background:rgba(var(--mc-rgb),.07);text-shadow:0 0 8px rgba(var(--mc-rgb),.5)}
#tg-indicator.ind-asl{--mc:var(--teal);--mc-rgb:0,255,229}
#tg-indicator.ind-echo{--mc:var(--amber);--mc-rgb:255,208,64}
#tg-indicator.ind-dmr{--mc:var(--blue);--mc-rgb:34,212,255}
#tg-indicator.ind-stfu{--mc:var(--green);--mc-rgb:0,255,176}
#tg-indicator.ind-ysf{--mc:var(--purple);--mc-rgb:212,102,255}
#tg-indicator.ind-fcs{--mc:var(--fcs);--mc-rgb:0,196,160}
#tg-indicator.ind-p25{--mc:var(--orange);--mc-rgb:255,170,34}
#tg-indicator.ind-nxdn{--mc:var(--lime);--mc-rgb:212,255,0}
#tg-indicator.ind-dstar{--mc:var(--pink);--mc-rgb:255,68,204}
#tg-indicator.ind-xlx{--mc:var(--teal);--mc-rgb:0,255,229}
#tg-indicator.ind-m17{--mc:var(--purple);--mc-rgb:212,102,255}
#tg-indicator.ind-rx{color:#ffd700;border-color:rgba(220,60,60,.6);background:rgba(200,20,20,.22);box-shadow:0 0 10px rgba(220,30,30,.35),inset 0 0 8px rgba(220,30,30,.12);text-shadow:0 0 10px rgba(255,215,0,.8)}

/* ── Tabs ── */
.tabs {
  display: flex;
  flex-wrap: nowrap;
  overflow-x: auto;
  overflow-y: hidden;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
  gap: .3rem;
  padding-bottom: 1px;
}
.tabs::-webkit-scrollbar { display: none; }
.tab {
  font-family: var(--mono);
  font-size: .992rem;
  font-weight: bold;
  letter-spacing: .08em;
  text-transform: uppercase;
  padding: .52rem 1.1rem;
  border-radius: 5px 5px 0 0;
  border: 1px solid var(--border2);
  border-bottom: none;
  background: var(--surface2);
  color: #ffffff;
  cursor: pointer;
  transition: all .15s;
  user-select: none;
  flex-shrink: 0;
}
.tab:hover { color: var(--text-bright); border-color: #5a7898; background: #253550; }
.tab.t-asl,.tab.t-echo,.tab.t-dmr,.tab.t-stfu,.tab.t-ysf,.tab.t-fcs,.tab.t-p25,.tab.t-nxdn,.tab.t-dstar,.tab.t-xlx,.tab.t-m17,.tab.t-edit{color:var(--mc);border-color:var(--mc);background:rgba(var(--mc-rgb),.18);box-shadow:0 -2px 18px rgba(var(--mc-rgb),.35);text-shadow:0 0 14px rgba(var(--mc-rgb),1)}
.tab.t-asl{--mc:var(--teal);--mc-rgb:0,255,229}
.tab.t-echo{--mc:var(--amber);--mc-rgb:255,208,64}
.tab.t-dmr{--mc:var(--blue);--mc-rgb:34,212,255}
.tab.t-stfu{--mc:var(--green);--mc-rgb:0,255,176}
.tab.t-ysf{--mc:var(--purple);--mc-rgb:212,102,255}
.tab.t-fcs{--mc:var(--fcs);--mc-rgb:0,196,160}
.tab.t-p25{--mc:var(--orange);--mc-rgb:255,170,34}
.tab.t-nxdn{--mc:var(--lime);--mc-rgb:212,255,0}
.tab.t-dstar{--mc:var(--pink);--mc-rgb:255,68,204}
.tab.t-xlx{--mc:var(--teal);--mc-rgb:0,255,229}
.tab.t-m17{--mc:var(--purple);--mc-rgb:212,102,255}
.tab.t-edit{--mc:var(--amber);--mc-rgb:184,134,11}

/* Hide mode tabs until first poll resolves — prevents flash of all tabs on load */
body:not(.tabs-ready) .tab:not(#tab-edit) { display: none; }
.tab-panel {
  border: 1px solid var(--border2);
  border-radius: 0 5px 5px 5px;
  background: var(--surface);
  overflow-y: auto;
  box-shadow: 0 4px 20px rgba(0,0,0,.4);
}
[id$="-grid"] { flex: 1; }
[id$="-grid"].grid-busy {
  opacity: .25;
  pointer-events: none;
  transition: opacity .15s;
}

/* ── Talkgroup rows ── */
.row-grid {
  display: grid;
  grid-template-columns: 2.1rem 9px 1fr;
  align-items: center;
  gap: .7rem;
  padding: .62rem .9rem;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background .1s;
  user-select: none;
}
.row-grid:last-child { border-bottom: none; }
.row-grid:hover      { background: var(--surface2); }

/* ── Active states ── */
.row-grid.active-asl,.row-grid.active-echo,.row-grid.active-dmr,.row-grid.active-stfu,.row-grid.active-ysf,.row-grid.active-fcs,.row-grid.active-p25,.row-grid.active-nxdn,.row-grid.active-dstar,.row-grid.active-xlx{background:rgba(var(--mc-rgb),.1);border-left:3px solid var(--mc);padding-left:calc(.9rem - 3px);box-shadow:inset 3px 0 12px rgba(var(--mc-rgb),.1)}
.row-grid.active-asl{--mc:var(--teal);--mc-rgb:0,255,229}
.row-grid.active-echo{--mc:var(--amber);--mc-rgb:255,208,64}
.row-grid.active-dmr{--mc:var(--blue);--mc-rgb:34,212,255}
.row-grid.active-stfu{--mc:var(--green);--mc-rgb:0,255,176}
.row-grid.active-ysf{--mc:var(--purple);--mc-rgb:212,102,255}
.row-grid.active-fcs{--mc:var(--fcs);--mc-rgb:0,196,160}
.row-grid.active-p25{--mc:var(--orange);--mc-rgb:255,170,34}
.row-grid.active-nxdn{--mc:var(--lime);--mc-rgb:212,255,0}
.row-grid.active-dstar{--mc:var(--pink);--mc-rgb:255,68,204}
.row-grid.active-xlx{--mc:var(--teal);--mc-rgb:0,255,229}

.row-grid.disc .row-name { color: #6b1825; }
/* ── DMR network-select header ── */
.net-sel-hdr {
  padding: .55rem .9rem .4rem;
  font-family: var(--mono);
  font-size: .78rem;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--blue);
  border-bottom: 1px solid var(--border);
  opacity: .75;
}

/* ── Reflector rows (DSTAR / XLX) ── */
.ref-row {
  display: grid;
  grid-template-columns: 2.1rem 9px 1fr auto auto;
  align-items: center;
  gap: .6rem;
  padding: .62rem .9rem;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background .1s;
  user-select: none;
}
.ref-row:last-child { border-bottom: none; }
.ref-row:hover      { background: var(--surface2); }
.ref-row.active-dstar,.ref-row.active-xlx,.ref-row.active-m17{background:rgba(var(--mc-rgb),.1);border-left:3px solid var(--mc);padding-left:calc(.9rem - 3px);box-shadow:inset 3px 0 12px rgba(var(--mc-rgb),.1)}
.ref-row.active-dstar{--mc:var(--pink);--mc-rgb:255,68,204}
.ref-row.active-xlx{--mc:var(--teal);--mc-rgb:0,255,229}
.ref-row.active-m17{--mc:var(--purple);--mc-rgb:212,102,255}
body.radio-keyed .ref-row.active-dstar,body.radio-keyed .ref-row.active-xlx,body.radio-keyed .ref-row.active-m17{background:rgba(200,20,20,.22);border-left:3px solid #e03030;padding-left:calc(.9rem - 3px);box-shadow:inset 3px 0 14px rgba(220,30,30,.18)}
.ref-info { display: flex; flex-direction: column; gap: .15rem; min-width: 0; }
.ref-name { font-family: var(--sans); font-weight: 700; font-size: 1.045rem; color: var(--text-bright); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ref-host { font-family: var(--mono); font-size: .77rem; color: #5a7898; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ref-mod-sel {
  font-family: var(--mono);
  font-size: .858rem;
  padding: .28rem .4rem;
  background: var(--surface2);
  color: var(--text-bright);
  border: 1px solid var(--border2);
  border-radius: 3px;
  outline: none;
  cursor: pointer;
  width: 5.5rem;
  flex-shrink: 0;
}
.ref-mod-sel:focus { border-color: var(--amber); }
.ref-mod-sel option { background: var(--surface2); }
.btn-conn  { color: var(--teal); border-color: var(--teal-dim); }
.btn-conn-pink { color: var(--pink); border-color: var(--pink-dim); }
.btn-conn-fcs  { color: var(--fcs);  border-color: var(--fcs-dim);  }
.btn-disconn { color: var(--red);  border-color: var(--red-dim);  }

/* ── Keyed states ── */
body.radio-keyed .row-grid.active-asl,body.radio-keyed .row-grid.active-echo,body.radio-keyed .row-grid.active-dmr,body.radio-keyed .row-grid.active-stfu,body.radio-keyed .row-grid.active-ysf,body.radio-keyed .row-grid.active-fcs,body.radio-keyed .row-grid.active-p25,body.radio-keyed .row-grid.active-nxdn,body.radio-keyed .row-grid.active-dstar,body.radio-keyed .row-grid.active-xlx{background:rgba(200,20,20,.22);border-left:3px solid #e03030;padding-left:calc(.9rem - 3px);box-shadow:inset 3px 0 14px rgba(220,30,30,.18)}
body.radio-keyed .row-grid[class*="active-"] .row-name{color:#ffd700;text-shadow:0 0 8px rgba(255,215,0,.7)}

.row-num  { font-family: var(--mono); font-size: .902rem; color: #5a7898; text-align: right; }
.row-name {
  font-family: var(--sans);
  font-weight: 700;
  font-size: 1.188rem;
  color: var(--text-bright);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  min-width: 0;
}
.pvt-chip {
  justify-self: end;
  font-family: var(--mono);
  font-size: .62rem;
  font-weight: 700;
  letter-spacing: .08em;
  color: var(--green);
  border: 1px solid rgba(0,255,176,.45);
  border-radius: 3px;
  padding: .08rem .3rem;
  flex-shrink: 0;
  align-self: center;
}
.dot     { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.dot-on  { background: var(--green); box-shadow: 0 0 8px var(--green), 0 0 16px rgba(0,255,176,.5); }
.dot-off { background: #3a5a7a; }                /* muted blue — idle */

/* ── Action bar + buttons ── */
.act-bar {
  padding: .65rem .9rem;
  display: flex;
  flex-wrap: wrap;
  gap: .4rem;
  border-top: 1px solid var(--border);
  background: #131c2d;
  position: sticky;
  bottom: 0;
}
.act-bar .btn { flex: 1; min-width: 8rem; text-align: center; }
@media (max-width: 560px) { .act-bar { flex-direction: column; } .act-bar .btn { min-width: 0; } }
.btn {
  font-family: var(--mono);
  font-size: .902rem;
  font-weight: bold;
  letter-spacing: .05em;
  text-transform: uppercase;
  padding: .48rem 1rem;
  border-radius: 4px;
  border: 1px solid;
  background: transparent;
  cursor: pointer;
  transition: all .14s;
  white-space: nowrap;
}
.btn:hover  { filter: brightness(1.6); box-shadow: 0 0 12px currentColor; }
.btn:active { transform: scale(.95); }
.btn-red    { color: var(--red);    border-color: #6b0e20; }
.btn-teal   { color: var(--teal);   border-color: #004840; }
.btn-amber  { color: var(--amber);  border-color: #6b4800; }
.btn-muted  { color: #7a9ec0;       border-color: var(--border2); }
.btn-blue   { color: var(--blue);   border-color: var(--blue-dim); }
.btn-purple { color: var(--purple); border-color: var(--purple-dim); }
.btn-orange { color: var(--orange); border-color: var(--orange-dim); }
.btn-lime   { color: var(--lime);   border-color: var(--lime-dim); }
.btn-green  { color: var(--green);  border-color: var(--green-dim); }
.lnk-sysmon {
  display: none;
  font-family: var(--mono);
  font-size: .792rem;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
  text-decoration: none;
  padding: .18rem .55rem;
  border: 1px solid var(--green-dim);
  border-radius: 3px;
  color: var(--green);
  background: rgba(0,255,176,.05);
  white-space: nowrap;
  flex-shrink: 0;
  transition: background .15s, box-shadow .15s;
}
.lnk-sysmon:hover {
  background: rgba(0,255,176,.12);
  box-shadow: 0 0 8px rgba(0,255,176,.3);
}

/* ── Toast ── */
#toast-stack {
  position: fixed;
  bottom: 1.5rem;
  right: 1.2rem;
  display: flex;
  flex-direction: column-reverse;
  gap: .45rem;
  z-index: 1200;
  pointer-events: none;
  max-width: 92vw;
}
.toast-item {
  background: #1a2438;
  border: 1px solid var(--border2);
  border-radius: 8px;
  padding: .7rem 1.4rem;
  font-family: var(--mono);
  font-size: 1.05rem;
  color: var(--text-bright);
  box-shadow: 0 8px 40px rgba(0,0,0,.8);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  opacity: 0;
  transform: translateX(2rem);
  transition: opacity .2s, transform .2s;
  pointer-events: none;
}
.toast-item.show { opacity: 1; transform: translateX(0); }
.toast-item.ok        { border-color: var(--green-dim);  color: var(--green);  box-shadow: 0 0 20px rgba(0,255,176,.2); }
.toast-item.err       { border-color: var(--red-dim);    color: var(--red);    box-shadow: 0 0 20px rgba(255,61,90,.2); }
.toast-item.info      { border-color: var(--amber-dim);  color: var(--amber);  box-shadow: 0 0 20px rgba(255,208,64,.2); }
.toast-item.toast-dmr { border-color: var(--blue-dim);   color: var(--blue);   box-shadow: 0 0 20px rgba(34,212,255,.2); }
.toast-item.toast-stfu{ border-color: var(--green-dim);  color: var(--green);  box-shadow: 0 0 20px rgba(0,255,176,.2); }
.toast-item.toast-ysf { border-color: var(--purple-dim); color: var(--purple); box-shadow: 0 0 20px rgba(212,102,255,.2); }
.toast-item.toast-p25 { border-color: var(--orange-dim); color: var(--orange); box-shadow: 0 0 20px rgba(255,170,34,.2); }
.toast-item.toast-nxdn{ border-color: var(--lime-dim);   color: var(--lime);   box-shadow: 0 0 20px rgba(212,255,0,.2); }
.toast-item.toast-dstar{border-color: var(--pink-dim);   color: var(--pink);   box-shadow: 0 0 20px rgba(255,68,204,.2); }
.toast-item.toast-fcs  {border-color: var(--fcs-dim);    color: var(--fcs);    box-shadow: 0 0 20px rgba(0,196,160,.2); }
.toast-item.toast-asl  { border-color: var(--teal-dim);   color: var(--teal);   box-shadow: 0 0 20px rgba(0,255,229,.2); }
.toast-item.toast-echo { border-color: var(--amber-dim);  color: var(--amber);  box-shadow: 0 0 20px rgba(255,208,64,.2); }
.toast-item.toast-xlx  { border-color: var(--teal-dim);   color: var(--teal);   box-shadow: 0 0 20px rgba(0,255,229,.2); }

/* ── Quick-tune bar ── */
.quick-bar {
  display: flex;
  align-items: center;
  gap: .45rem;
  flex-wrap: nowrap;
  padding: .55rem .9rem;
  border-bottom: 1px solid var(--border);
  background: #111828;
}
.quick-inp {
  font-family: var(--mono);
  font-size: .99rem;
  padding: .35rem .6rem;
  background: var(--surface2);
  color: var(--text-bright);
  border: 1px solid var(--border2);
  border-radius: 3px;
  outline: none;
  flex: 1 1 0;
  min-width: 0;
  max-width: 260px;
  transition: border-color .15s;
}
.quick-inp:focus { border-color: var(--amber); box-shadow: 0 0 6px rgba(255,208,64,.2); }

/* ── Server bar (DMR) ── */
.dmr-srv-select {
  font-family: var(--mono);
  font-size: .902rem;
  padding: .35rem .55rem;
  background: var(--surface2);
  color: var(--blue);
  border: 1px solid var(--blue-dim);
  border-radius: 3px;
  outline: none;
  cursor: pointer;
  flex-shrink: 0;
  max-width: 160px;
}
.dmr-srv-select:focus { border-color: var(--blue); box-shadow: 0 0 6px rgba(34,212,255,.3); }
.dmr-srv-select option { background: var(--surface2); color: var(--text-bright); }

/* ── Editor ── */
.ed-toolbar {
  padding: .65rem .9rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: .5rem;
  flex-wrap: wrap;
  border-bottom: 1px solid var(--border);
  background: #131c2d;
}
.ed-list-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  grid-template-rows: repeat(5, auto);
  grid-auto-flow: column;
  gap: .5rem .6rem;
  padding: .5rem .6rem;
}
.ed-row { display: flex; flex-direction: column; gap: .2rem; }
.ed-row:hover { background: rgba(255,255,255,.02); border-radius: 3px; }
.ed-inp {
  font-family: var(--mono);
  font-size: .946rem;
  padding: .3rem .48rem;
  background: var(--surface2);
  color: var(--text-bright);
  border: 1px solid var(--border2);
  border-radius: 3px;
  width: 100%;
  min-width: 0;
  outline: none;
  transition: border-color .15s;
  box-sizing: border-box;
}
.ed-inp:focus { border-color: var(--amber); box-shadow: 0 0 6px rgba(255,208,64,.2); }
.ed-count {
  font-family: var(--mono);
  font-size: .836rem;
  color: #3a5278;
  text-align: right;
  padding: .5rem .9rem;
  border-top: 1px solid var(--border);
  background: #111828;
}
.cfg-section { padding: .65rem .9rem .5rem; border-bottom: 2px solid var(--border); background: #111828; }
.cfg-grid    { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: .55rem .9rem; margin-top: .4rem; }
.cfg-field   { display: flex; flex-direction: column; gap: .2rem; }
.cfg-lbl     { font-family: var(--mono); font-size: .66rem; letter-spacing: .18em; text-transform: uppercase; color: #5a7898; }
.srv-meta-row { display:grid; grid-template-columns:1fr 1fr 1.4fr auto; gap:.4rem; padding:.4rem .6rem; border-bottom:1px solid var(--border); align-items:center; }
.srv-meta-row:last-child { border-bottom:none; }
.btn-xs { font-family:var(--mono); font-size:.77rem; padding:.25rem .55rem; border-radius:3px; border:1px solid; background:transparent; cursor:pointer; }
.btn-xs:hover { filter:brightness(1.6); }
.cfg-inp {
  font-family: var(--mono);
  font-size: .99rem;
  padding: .35rem .55rem;
  background: var(--surface2);
  color: var(--text-bright);
  border: 1px solid var(--border2);
  border-radius: 3px;
  outline: none;
  transition: border-color .15s;
  width: 100%;
}
.cfg-inp:focus { border-color: var(--amber); box-shadow: 0 0 6px rgba(255,208,64,.2); }
.cfg-inp:disabled { opacity: .45; cursor: not-allowed; }
.cfg-lbl.cfg-lbl-reserved { color: #4a5a6a; }
.tab-enable-row { display: flex; flex-wrap: wrap; gap: .6rem 1.2rem; margin-top: .55rem; padding-top: .45rem; border-top: 1px solid var(--border); }
.tab-chk-lbl { display: flex; align-items: center; gap: .35rem; font-family: var(--mono); font-size: .858rem; color: #7a9ec0; cursor: pointer; user-select: none; }
.tab-chk-lbl input[type=checkbox] { accent-color: var(--amber); width: 14px; height: 14px; cursor: pointer; }
/* Section collapse toggle button */
.ed-sec-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-family: var(--mono);
  font-size: .66rem;
  letter-spacing: .22em;
  text-transform: uppercase;
  color: #3a5278;
  padding: .5rem .9rem .35rem;
  margin-top: .4rem;
  border-top: 1px solid var(--border);
}
.ed-sec-hdr.no-top { border-top: none; padding-left: 0; margin-top: 0; }
.ed-hint {
  font-family: var(--mono);
  font-size: .72rem;
  color: #5a7898;
  padding: .15rem .2rem .35rem;
  line-height: 1.35;
}
.ed-sec-hdr button {
  font-family: var(--mono);
  font-size: .55rem;
  letter-spacing: .12em;
  color: #3a5278;
  background: transparent;
  border: 1px solid #1e3050;
  border-radius: 3px;
  padding: .1rem .45rem;
  cursor: pointer;
  text-transform: uppercase;
  transition: color .15s, border-color .15s;
  flex-shrink: 0;
}
.ed-sec-hdr button:hover { color: var(--amber); border-color: var(--amber-dim); }

/* ── Stage 8: Edit tab scoped color contrast overrides ────────────────────────
   All rules are scoped to #pg-EDIT.  Root CSS variables are NOT touched;
   changes do not cascade to any other tab.
   ─────────────────────────────────────────────────────────────────────────── */

/* 8.2 — override tokens, defined at the container level */
#pg-EDIT {
  --edit-lbl:        #ffffff;  /* section / cfg labels  (was #8faacc) */
  --edit-sec-btn:    #ffffff;  /* collapse-toggle btn   (was #6a8aaa) */
  --edit-sec-border: #4a6a90;  /* collapse-toggle border (was #2e4a68) */
  --edit-count:      #ffffff;  /* ed-count status text  (was #6a8aaa) */
  --edit-inp-border: #4a6a90;  /* input borders         (unchanged) */
  --edit-chk-lbl:    #ffffff;  /* tab-checkbox labels   (was #9ab8d0) */
  --edit-btn-muted:  #9ab8d0;  /* Back/Reload btn text  — unchanged */
  --edit-btn-border: #3d5880;  /* Back/Reload btn border — unchanged */
}

/* 8.3 — section headers and labels */
#pg-EDIT .ed-sec-hdr          { color: var(--edit-lbl); }
#pg-EDIT .cfg-lbl              { color: var(--edit-lbl); }
#pg-EDIT .cfg-lbl.cfg-lbl-reserved { color: #5a6b7c; }
#pg-EDIT .ed-sec-hdr button   { color: var(--edit-sec-btn); border-color: var(--edit-sec-border); }
#pg-EDIT .ed-sec-hdr button:hover { color: var(--amber); border-color: var(--amber-dim); }

/* 8.4 — input field borders; text is already var(--text-bright) — no change needed */
#pg-EDIT .ed-inp              { border-color: var(--edit-inp-border); }
#pg-EDIT .cfg-inp             { border-color: var(--edit-inp-border); }
#pg-EDIT .ed-inp::placeholder,
#pg-EDIT .cfg-inp::placeholder {
  color: #5a7898;   /* explicit placeholder so Firefox opacity=54% default doesn't crush it */
  opacity: 1;
}

/* 8.5 — muted buttons (Back / Reload); Save/teal is already high-contrast, no override */
#pg-EDIT .btn-muted { color: var(--edit-btn-muted); border-color: var(--edit-btn-border); }

/* 8.6 — hint/count text and tab-enable checkboxes */
#pg-EDIT .ed-count    { color: var(--edit-count); }
#pg-EDIT .tab-chk-lbl { color: var(--edit-chk-lbl); }

/* 8.7 — network dashboard URL fields (amber-tinted, visually distinct) */
.ed-url-row {
  padding: .25rem .6rem .4rem;
  background: rgba(255,208,64,.04);
  border-bottom: 1px solid rgba(255,208,64,.07);
}
.ed-url-label {
  display: block;
  font-family: var(--mono);
  font-size: .58rem;
  letter-spacing: .2em;
  text-transform: uppercase;
  color: #a89060;
  margin-bottom: .2rem;
}
.ed-inp.url-inp {
  border-color: rgba(255,208,64,.3);
  background: rgba(255,208,64,.04);
  font-size: .836rem;
}
.ed-inp.url-inp::placeholder { color: #4a5a3a; opacity: 1; }
.ed-inp.url-inp:focus { border-color: var(--amber); background: rgba(255,208,64,.08); }
.ed-inp.url-inp-row { margin-top: .2rem; }

/* ─────────────────────────────────────────────────────────────────────────── */

/* ── Overlays (working, modal, error modal, ready bar) ── */
#working-overlay {
  display: none;
  position: fixed;
  inset: 0;
  z-index: 1100;
  background: rgba(0,0,0,.55);
  backdrop-filter: blur(3px);
  align-items: center;
  justify-content: center;
}
#working-overlay.open { display: flex; }
#working-box {
  background: linear-gradient(135deg, #1a2438, #161e2e);
  border: 1px solid var(--border2);
  border-radius: 8px;
  padding: 1.8rem 2.4rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
  box-shadow: 0 20px 80px rgba(0,0,0,.9);
}
#working-msg {
  font-family: var(--mono);
  font-size: 1.1rem;
  color: var(--amber);
  text-shadow: 0 0 10px rgba(255,208,64,.5);
  letter-spacing: .08em;
  text-transform: uppercase;
}
.spinner {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 3px solid var(--border2);
  border-top-color: var(--amber);
  animation: spin .75s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
#modal-overlay {
  display: none;
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(0,0,0,.72);
  backdrop-filter: blur(4px);
  align-items: center;
  justify-content: center;
}
#modal-overlay.open { display: flex; }
#modal-box {
  background: linear-gradient(135deg, #1a2438, #161e2e);
  border: 1px solid var(--border2);
  border-radius: 8px;
  padding: 1.8rem 2rem 1.4rem;
  min-width: 320px;
  max-width: 88vw;
  box-shadow: 0 20px 80px rgba(0,0,0,.9);
  display: flex;
  flex-direction: column;
  gap: 1.2rem;
}
#modal-msg  { font-family: var(--mono); font-size: 1.1rem; color: var(--text-bright); line-height: 1.55; white-space: pre-wrap; }
#modal-btns { display: flex; gap: .6rem; justify-content: flex-end; flex-wrap: wrap; }
#err-modal-overlay {
  display: none;
  position: fixed;
  inset: 0;
  z-index: 1100;
  background: rgba(0,0,0,.8);
  backdrop-filter: blur(4px);
  align-items: center;
  justify-content: center;
}
#err-modal-overlay.open { display: flex; }
#err-modal-box {
  background: linear-gradient(135deg, #2a0a0e, #1a0608);
  border: 2px solid var(--red);
  border-radius: 8px;
  padding: 1.8rem 2rem 1.4rem;
  min-width: 320px;
  max-width: 88vw;
  box-shadow: 0 20px 80px rgba(255,61,90,.35);
  display: flex;
  flex-direction: column;
  gap: 1.2rem;
}
#err-modal-hdr  { font-family: var(--mono); font-size: .792rem; letter-spacing: .22em; text-transform: uppercase; color: var(--red); text-shadow: 0 0 10px rgba(255,61,90,.7); }
#err-modal-msg  { font-family: var(--mono); font-size: 1.045rem; color: #ffb0b8; line-height: 1.6; white-space: pre-wrap; }
#err-modal-btns { display: flex; gap: .6rem; justify-content: flex-end; }
.perm-disc-btn { font-family: var(--mono); font-size: .7rem; padding: .18rem .52rem; background: transparent; border: 1px solid rgba(255,208,64,.4); color: var(--amber); border-radius: 4px; cursor: pointer; letter-spacing: .04em; white-space: nowrap; }
.perm-disc-btn:hover { background: rgba(255,208,64,.14); }
#ready-bar {
  position: fixed;
  top: -6rem;
  left: 50%;
  transform: translateX(-50%);
  background: linear-gradient(135deg, #0d2b1a, #0a1e14);
  border: 1px solid var(--green-dim);
  border-radius: 0 0 8px 8px;
  padding: .8rem 2rem;
  z-index: 990;
  transition: top .4s cubic-bezier(.22,.9,.36,1);
  display: flex;
  align-items: center;
  gap: .8rem;
  box-shadow: 0 8px 40px rgba(0,255,176,.15);
  font-family: var(--mono);
  font-size: 1.1rem;
  color: var(--green);
  text-shadow: 0 0 12px rgba(0,255,176,.6);
  white-space: nowrap;
}
#ready-bar.show { top: 0; }
#ready-bar .rdy-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 10px var(--green), 0 0 20px rgba(0,255,176,.5);
  flex-shrink: 0;
}

/* ── Last Heard button ── */
.btn-last {
  font-family: var(--mono);
  font-size: .72rem;
  font-weight: bold;
  letter-spacing: .04em;
  padding: .25rem .48rem;
  border-radius: 3px;
  border: 1px solid var(--amber-dim);
  background: rgba(255,208,64,.05);
  color: var(--amber);
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  transition: background .12s;
}
.btn-last:hover { background: rgba(255,208,64,.14); }
.btn-last.lh-off {
  opacity: .4;
  color: var(--muted);
  border-color: var(--muted);
  background: transparent;
  cursor: default;
  pointer-events: none;
}
.btn-last.lh-off:hover { background: transparent; }
.row-grid.has-lh { grid-template-columns: 2.1rem 9px 1fr auto; }
.row-grid.has-pvt { grid-template-columns: 2.1rem 9px 1fr auto; }
.row-grid.has-pvt.has-lh { grid-template-columns: 2.1rem 9px 1fr auto auto; }
.ref-row.has-lh  { grid-template-columns: 2.1rem 9px 1fr auto auto; }

/* ── Scrollbar + responsive ── */
::-webkit-scrollbar       { width: 4px; }
::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 2px; }
@media (max-width: 560px) {
  .tabs { gap: .2rem; }
  .tab  { padding: .4rem .6rem; font-size: .871rem; }
  .row-grid { grid-template-columns: 1.6rem 7px 1fr; }
  .row-grid.has-lh { grid-template-columns: 1.6rem 7px 1fr auto; }
  .row-grid.has-pvt { grid-template-columns: 1.6rem 7px 1fr auto; }
  .row-grid.has-pvt.has-lh { grid-template-columns: 1.6rem 7px 1fr auto auto; }
  .quick-inp { max-width: 180px; }
  header { padding: .35rem .65rem; gap: .3rem; }
  .logo  { font-size: 1.0rem; }
  .logo-sub { font-size: .62rem; letter-spacing: .14em; }
  #hdr-uptime { font-size: .7rem; }
  .hdr-ver    { font-size: .62rem; }
  .btn-last   { font-size: .66rem; padding: .2rem .4rem; }
  .dmr-srv-select { max-width: 90px; }
}
.hidden{display:none}
</style>
</head>
<body>
<div id="offline-bar">SERVER UNREACHABLE — retrying…</div>
<div id="perm-link-bar">⚠ PERMANENT LINK ACTIVE · Node <span id="perm-link-node">—</span> · Bridging risk<button class="perm-disc-btn" style="margin-left:.9rem" onclick="doBannerDiscPermLink()">Disconnect</button></div>
<header>
  <div class="hdr-left">
    <div class="logo">ASL-DVS Node Control</div>
    <div class="logo-sub"><span id="hdr-callsign" style="color:var(--amber);display:none"></span><span id="hdr-callsign-sep" class="hidden"> · </span><span style="color:var(--amber)">Node</span> <span id="hdr-node" style="color:var(--amber)">…</span></div>
  </div>
  <div class="hdr-right">
    <span id="hdr-uptime">UP 0:00:00</span>
    <div class="hdr-ver" style="font-size:.72rem;color:var(--muted);font-family:var(--mono)">v__VERSION__</div>
  </div>
</header>
<div class="wrap">
  <div>
    <div class="sec-lbl-row" style="position:relative">
      <div class="sec-lbl">Link</div>
      <span id="tg-indicator" class="ind-idle"><span class="dot dot-off" id="tg-dot-l"></span><span id="tg-value">——</span><span class="dot dot-off" id="tg-dot-r"></span></span>
      <a id="lnk-sysmon" class="lnk-sysmon" href="#">SysMon</a>
    </div>
    <div id="tabs-strip">
      <div class="tabs">
        <div class="tab" id="tab-asl"   onclick="clickTab('ASL')">ASL</div>
        <div class="tab" id="tab-echo"  onclick="clickTab('ECHO')">Echo</div>
        <div class="tab" id="tab-dmr"   onclick="clickTab('DMR')">DMR</div>
        <div class="tab" id="tab-stfu"  onclick="clickTab('STFU')">STFU</div>
        <div class="tab" id="tab-ysf"   onclick="clickTab('YSF')">YSF</div>
        <div class="tab" id="tab-fcs"   onclick="clickTab('FCS')">FCS</div>
        <div class="tab" id="tab-p25"   onclick="clickTab('P25')">P-25</div>
        <div class="tab" id="tab-nxdn"  onclick="clickTab('NXDN')">NXDN</div>
        <div class="tab" id="tab-dstar" onclick="clickTab('DSTAR')">D-STAR</div>
        <div class="tab" id="tab-xlx"   onclick="clickTab('XLX')">XLX</div>
        <div class="tab" id="tab-m17"   onclick="clickTab('M17')">M17</div>
        <div class="tab" id="tab-edit"  onclick="clickEdit()">EDIT</div>
      </div>
      <div class="tab-panel">
        <div id="pg-ASL" class="hidden">
          <div class="quick-bar">
            <input id="cbn-input" class="quick-inp" type="text" inputmode="numeric"
              pattern="[0-9]*" placeholder="Node number…" maxlength="12"
              onkeydown="if(event.key==='Enter')doConnectByNumber()">
            <button class="btn btn-teal" onclick="doConnectByNumber()">Tune</button>
            <button id="lh-btn-ASL" class="btn-last lh-off" onclick="openModeLast('ASL')">LH</button>
          </div>
          <div id="asl-grid"></div>
          <div class="act-bar">
            <button class="btn btn-red" onclick="doAslDiscCurrent()">Disconnect</button>
          </div>
        </div>
        <!-- ECHO -->
        <div id="pg-ECHO" class="hidden">
          <div class="quick-bar">
            <input id="echo-input" class="quick-inp" type="text" inputmode="numeric"
              pattern="[0-9]*" placeholder="EchoLink node (e.g. 9999)…" maxlength="6"
              onkeydown="if(event.key==='Enter')doEchoConnectByNumber()">
            <button class="btn btn-amber" onclick="doEchoConnectByNumber()">Tune</button>
            <button id="lh-btn-ECHO" class="btn-last lh-off" onclick="openModeLast('ECHO')">LH</button>
          </div>
          <div id="echo-grid"></div>
          <div class="act-bar">
            <button class="btn btn-red" onclick="doEchoDisc()">Disconnect</button>
          </div>
        </div>
        <div id="pg-DMR" class="hidden">
          <div class="quick-bar">
            <select id="dmr-srv-select" class="dmr-srv-select" onchange="switchDmrServer(this.value)" title="DMR Network"></select>
            <input id="qt-DMR" class="quick-inp" type="text" inputmode="numeric"
              placeholder="TG number…" maxlength="12"
              onkeydown="if(event.key==='Enter')doQuickTune('DMR')">
            <button class="btn btn-blue" onclick="doQuickTune('DMR')">Tune</button>
            <button id="lh-btn-DMR" class="btn-last lh-off" onclick="openDmrLast()">LH</button>
          </div>
          <div id="dmr-grid"></div>
          <div class="act-bar">
            <button class="btn btn-red" onclick="doModeDisconnect('DMR')">Disconnect</button>
            <button class="btn btn-muted" onclick="doDiscAll()">Disconnect All</button>
          </div>
        </div>
        <!-- STFU -->
        <div id="pg-STFU" class="hidden">
          <div class="quick-bar">
            <input id="qt-STFU" class="quick-inp" type="text" inputmode="numeric"
              placeholder="TG or ID#…" maxlength="12"
              onkeydown="if(event.key==='Enter')doQuickTune('STFU')">
            <button class="btn btn-green" onclick="doQuickTune('STFU')">Tune</button>
            <button id="lh-btn-STFU" class="btn-last lh-off" onclick="openModeLast('STFU')">LH</button>
          </div>
          <div id="stfu-grid"></div>
          <div class="act-bar">
            <button class="btn btn-red" onclick="doModeDisconnect('STFU')">Disconnect</button>
            <button class="btn btn-muted" onclick="doDiscAll()">Disconnect All</button>
          </div>
        </div>
        <div id="pg-YSF" class="hidden">
          <div class="quick-bar">
            <input id="qt-YSF" class="quick-inp" type="text" placeholder="IP:port or reflector…" maxlength="40"
              onkeydown="if(event.key==='Enter')doQuickTune('YSF')">
            <button class="btn btn-purple" onclick="doQuickTune('YSF')">Tune</button>
          </div>
          <div id="ysf-grid"></div>
          <div class="act-bar">
            <button class="btn btn-red" onclick="doModeDisconnect('YSF')">Disconnect</button>
            <button class="btn btn-muted" onclick="doDiscAll()">Disconnect All</button>
          </div>
        </div>
        <div id="pg-FCS" class="hidden">
          <div class="quick-bar">
            <input id="qt-FCS" class="quick-inp" type="text" inputmode="numeric"
              placeholder="Room (e.g. FCS00335 or 335)" maxlength="20"
              onkeydown="if(event.key==='Enter')doQuickTune('FCS')">
            <button class="btn btn-conn-fcs" onclick="doQuickTune('FCS')">Tune</button>
          </div>
          <div id="fcs-grid"></div>
          <div class="act-bar">
            <button class="btn btn-red" onclick="doModeDisconnect('FCS')">Disconnect</button>
            <button class="btn btn-muted" onclick="doDiscAll()">Disconnect All</button>
          </div>
        </div>
        <div id="pg-P25" class="hidden">
          <div class="quick-bar">
            <input id="qt-P25" class="quick-inp" type="text" inputmode="numeric"
              placeholder="TG number…" maxlength="12"
              onkeydown="if(event.key==='Enter')doQuickTune('P25')">
            <button class="btn btn-orange" onclick="doQuickTune('P25')">Tune</button>
          </div>
          <div id="p25-grid"></div>
          <div class="act-bar">
            <button class="btn btn-red" onclick="doModeDisconnect('P25')">Disconnect</button>
            <button class="btn btn-muted" onclick="doDiscAll()">Disconnect All</button>
          </div>
        </div>
        <div id="pg-NXDN" class="hidden">
          <div class="quick-bar">
            <input id="qt-NXDN" class="quick-inp" type="text" inputmode="numeric"
              placeholder="TG number…" maxlength="12"
              onkeydown="if(event.key==='Enter')doQuickTune('NXDN')">
            <button class="btn btn-lime" onclick="doQuickTune('NXDN')">Tune</button>
          </div>
          <div id="nxdn-grid"></div>
          <div class="act-bar">
            <button class="btn btn-red" onclick="doModeDisconnect('NXDN')">Disconnect</button>
            <button class="btn btn-muted" onclick="doDiscAll()">Disconnect All</button>
          </div>
        </div>
        <div id="pg-DSTAR" class="hidden">
          <div class="quick-bar">
            <input id="qt-DSTAR-base" class="quick-inp" type="text" placeholder="REF001…" maxlength="12"
              style="max-width:130px"
              onkeydown="if(event.key==='Enter')dstarQuickConnect()">
            <select id="qt-DSTAR-mod" class="ref-mod-sel" title="Module"></select>
            <button class="btn btn-conn-pink" onclick="dstarQuickConnect()">Tune</button>
          </div>
          <div id="dstar-grid"></div>
          <div class="act-bar">
            <button class="btn btn-red" onclick="doDstarDisconnect()">Disconnect</button>
            <button class="btn btn-muted" onclick="doDiscAll()">Disconnect All</button>
          </div>
        </div>
        <div id="pg-XLX" class="hidden">
          <div class="quick-bar">
            <input id="qt-XLX-base" class="quick-inp" type="text" placeholder="XLX334…" maxlength="12"
              style="max-width:130px"
              onkeydown="if(event.key==='Enter')xlxQuickConnect()">
            <select id="qt-XLX-mod" class="ref-mod-sel" title="Module"></select>
            <button class="btn btn-conn" onclick="xlxQuickConnect()">Tune</button>
          </div>
          <div id="xlx-grid"></div>
          <div class="act-bar">
            <button class="btn btn-red" onclick="doXlxDisconnect()">Disconnect</button>
            <button class="btn btn-muted" onclick="doDiscAll()">Disconnect All</button>
          </div>
        </div>
        <div id="pg-M17" class="hidden">
          <div class="quick-bar">
            <input id="qt-M17-ip" class="quick-inp" type="text" placeholder="Reflector IP…" maxlength="45"
              style="max-width:160px"
              onkeydown="if(event.key==='Enter')m17QuickConnect()">
            <select id="qt-M17-mod" class="ref-mod-sel" title="Module"></select>
            <button class="btn btn-conn" onclick="m17QuickConnect()">Connect</button>
          </div>
          <div id="m17-grid"></div>
          <div class="act-bar">
            <button class="btn btn-red" onclick="doM17Disconnect()">Disconnect</button>
            <button class="btn btn-muted" onclick="doDiscAll()">Disconnect All</button>
          </div>
        </div>
        <div id="pg-EDIT" class="hidden">
          <div class="ed-toolbar" style="justify-content:center">
            <button class="btn btn-muted" onclick="showPage(curPage)">Back</button>
            <button class="btn btn-teal"  onclick="edSave()">Save</button>
            <button class="btn btn-muted" onclick="edReload()">Reload</button>
          </div>
          <div class="cfg-section">
            <div class="ed-sec-hdr no-top">Configuration</div>
            <div class="cfg-grid">
              <div class="cfg-field">
                <label class="cfg-lbl" for="cfg-callsign">Callsign</label>
                <input id="cfg-callsign" class="cfg-inp" type="text" placeholder="e.g. KD8PGK" maxlength="16" style="text-transform:uppercase">
              </div>
              <div class="cfg-field">
                <label class="cfg-lbl" for="cfg-asl-node">Main Node Number</label>
                <input id="cfg-asl-node" class="cfg-inp" type="text" inputmode="numeric" placeholder="e.g. 652701" maxlength="10">
              </div>
              <div class="cfg-field">
                <label class="cfg-lbl" for="cfg-bridge-node-0">Digital Voice Bridge</label>
                <input id="cfg-bridge-node-0" class="cfg-inp" type="text" inputmode="numeric" placeholder="e.g. 1999" maxlength="10">
              </div>
              <div class="cfg-field">
                <label class="cfg-lbl" for="cfg-bridge-node-1">M17 Bridge</label>
                <input id="cfg-bridge-node-1" class="cfg-inp" type="text" inputmode="numeric" placeholder="e.g. 1917" maxlength="10">
              </div>
              <div class="cfg-field">
                <label class="cfg-lbl cfg-lbl-reserved" for="cfg-bridge-node-2">Reserved</label>
                <input id="cfg-bridge-node-2" class="cfg-inp" type="text" inputmode="numeric" placeholder="—" maxlength="10" disabled title="Reserved for future use">
              </div>
              <div class="cfg-field">
                <label class="cfg-lbl cfg-lbl-reserved" for="cfg-bridge-node-3">Reserved</label>
                <input id="cfg-bridge-node-3" class="cfg-inp" type="text" inputmode="numeric" placeholder="—" maxlength="10" disabled title="Reserved for future use">
              </div>
              <div class="cfg-field">
                <label class="cfg-lbl" for="cfg-port">Web UI Port</label>
                <input id="cfg-port" class="cfg-inp" type="text" inputmode="numeric" placeholder="e.g. 8989" maxlength="5">
              </div>
            </div>
            <div class="ed-sec-hdr" style="margin-top:.6rem;padding-left:0">
              <span>Visible Tabs</span>
              <button onclick="toggleEdSection('eds-tabs')">Hide</button>
            </div>
            <div id="eds-tabs" class="tab-enable-row" style="border-top:none;padding-top:0;margin-top:.3rem">
              <label class="tab-chk-lbl"><input type="checkbox" id="chk-ASL"   value="ASL">ASL</label>
              <label class="tab-chk-lbl"><input type="checkbox" id="chk-ECHO"  value="ECHO">Echo</label>
              <label class="tab-chk-lbl"><input type="checkbox" id="chk-DMR"   value="DMR">DMR</label>
              <label class="tab-chk-lbl"><input type="checkbox" id="chk-STFU"  value="STFU">STFU</label>
              <label class="tab-chk-lbl"><input type="checkbox" id="chk-YSF"   value="YSF">YSF</label>
              <label class="tab-chk-lbl"><input type="checkbox" id="chk-FCS"   value="FCS">FCS</label>
              <label class="tab-chk-lbl"><input type="checkbox" id="chk-P25"   value="P25">P-25</label>
              <label class="tab-chk-lbl"><input type="checkbox" id="chk-NXDN"  value="NXDN">NXDN</label>
              <label class="tab-chk-lbl"><input type="checkbox" id="chk-DSTAR" value="DSTAR">D-STAR</label>
              <label class="tab-chk-lbl"><input type="checkbox" id="chk-XLX"   value="XLX">XLX</label>
              <label class="tab-chk-lbl"><input type="checkbox" id="chk-M17"   value="M17">M17</label>
            </div>
          </div>
          <div id="ed-list"></div>
          <div class="ed-count" id="ed-count"></div>
          <div class="ed-toolbar" style="margin-top:.5rem;justify-content:center">
            <button class="btn btn-teal"  onclick="edSave()">Save</button>
            <button class="btn btn-muted" onclick="edReload()">Reload</button>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div>
    <div class="sec-lbl">System</div>
    <div class="act-bar" style="border-top:none">
      <button class="btn btn-red"   onclick="doReboot()">Reboot</button>
      <button class="btn btn-muted" onclick="doShutdown()">Shutdown</button>
    </div>
  </div>
</div>
<div id="toast-stack"></div>
<div id="modal-overlay"><div id="modal-box"><div id="modal-msg"></div><div id="modal-btns"></div></div></div>
<div id="err-modal-overlay"><div id="err-modal-box">
  <div id="err-modal-hdr">⚠ Tune Failed</div>
  <div id="err-modal-msg"></div>
  <div id="err-modal-btns"><button class="btn btn-red" onclick="byId('err-modal-overlay').classList.remove('open')">Dismiss</button></div>
</div></div>
<div id="working-overlay"><div id="working-box"><div class="spinner"></div><div id="working-msg">Working…</div></div></div>
<div id="ready-bar"><div class="rdy-dot"></div><span id="ready-msg">READY</span></div>
<script>
const byId=id=>document.getElementById(id);
// Initial value only — this literal predates MODE_CAPS in file order (TDZ
// prevents referencing STATIC_PAGES here), and gets fully overwritten by
// applyTabVisibility() on first load anyway. Keep this list in sync with
// MODE_CAPS' keys below if a mode is ever added/removed at the Object.keys
// level; applyTabVisibility() itself no longer needs this list at all.
const PAGES=['ASL','ECHO','DMR','STFU','YSF','FCS','P25','NXDN','DSTAR','XLX'];
let TAB_LABELS={ASL:'ASL',ECHO:'ECHO',DMR:'DMR',STFU:'STFU',YSF:'YSF',FCS:'FCS',P25:'P25',NXDN:'NXDN',DSTAR:'DSTAR',XLX:'XLX'};
const TG_BLANK_NAME='blank';
const TG_BLANK_ADDR='000000';
const TG_DISCONNECT='disconnect';
let curPage='ASL',curTg=null,busy=false,inEdit=false;
// Per-mode last-tuned memory.  Digital tabs clear their entry on disconnect
// (clickTab sends TG_DISCONNECT before leaving) so _curTgPerMode[mode] is
// only non-null when a connection is still active (ASL/ECHO) or was never
// torn down (Edit-page round-trips).  Used by clickTab to restore the
// correct indicator immediately on tab entry without waiting for a tune event.
const _curTgPerMode = {};
let _hasAsl=true,_hasDvs=true,_hasStfu=false,_hasEcho=false,_hasM17=false,_lastHash='',_firstPoll=true,_failCount=0,_lastKeyed=false;
let _uptimeBase=0,_uptimeAt=0;
let _pendingTune=null; // {tg,mode,name,at} while awaiting ABInfo confirmation; null otherwise
// When true the DMR panel shows the network-select tile grid instead of the TG grid.
// D3 (audit) — this flag has 4 independent writers; not a bug, but easy to
// mistake for one if you're only looking at one call site. Each site below
// is tagged "D3 writer" so a future edit to any one of them prompts a check
// of the other three:
//   1. First-load init (applyTabState, DVS-only node landing on DMR)
//   2. clickTab('DMR')            — arriving at DMR from another tab
//   3. reTuneTab('DMR')           — re-clicking the already-active DMR tab
//   4. doDiscAll()'s success callback, when curPage==='DMR'
// Cleared only in switchDmrServer(), and only on success (see D1 fix) — a
// failed switch must leave the tile picker up, not fall through to the TG grid.
// Never touched by Edit → Back navigation (showPage preserves the flag as-is).
let _dmrNetSelectMode=false;
let _lastEtag='';  // ETag from last /api/status 200 — sent as If-None-Match on next poll
let _tgDataLoaded=false; // true once loadTgData() has completed at least one successful fetch
let _lastTgs={},_lastAslNodes=[],_lastEchoNodes=[],_lastEchoFav=null,_lastLinkedNode=null,_lastIsKnownPerm=false;
let _lastDmrServers=[],_lastActiveDmrServer=''; // cached from /api/status for immediate net-select render
let _lastDstarRefs=[],_lastXlxRefs=[],_lastM17Refs=[];   // reflector lists for DSTAR/XLX/M17 grids
let dstarModSel={},xlxModSel={},m17ModSel={}; // per-row module dropdown selections (session only)
let dmrSrvRows={};  // {SERVER_KEY: [{name,tg}, ...]}
let _pollTimer=null,_readyTimer=null,_workTimer=null;
function fmtUptime(secs){
  const h=Math.floor(secs/3600);
  const m=Math.floor((secs%3600)/60);
  const s=secs%60;
  return 'UP '+h+':'+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0');
}
function toast(msg,type='ok',mode=''){
  const stack=byId('toast-stack');
  const last=stack.lastElementChild;
  if(last&&last.classList.contains('show')&&last.textContent===msg)return;
  const item=document.createElement('div');
  const modeClass=mode?'toast-'+mode.toLowerCase():'';
  item.className='toast-item '+(modeClass||type);
  item.textContent=msg;
  stack.appendChild(item);
  requestAnimationFrame(()=>requestAnimationFrame(()=>item.classList.add('show')));
  const t=setTimeout(()=>{
    item.classList.remove('show');
    setTimeout(()=>{if(item.parentNode)item.parentNode.removeChild(item)},220);
  },7200);
  item._t=t;
}
function dimGrid(mode){
  const el=byId(mode.toLowerCase()+'-grid');
  if(el)el.classList.add('grid-busy');
}
function undimGrid(mode){
  const el=byId(mode.toLowerCase()+'-grid');
  if(el)el.classList.remove('grid-busy');
}
function modal(msg,buttons){
  return new Promise(res=>{
    const ov=byId('modal-overlay');
    byId('modal-msg').textContent=msg;
    const btns=byId('modal-btns');
    btns.innerHTML='';
    buttons.forEach(b=>{
      const btn=Object.assign(document.createElement('button'),{
        textContent:b.label,className:'btn '+(b.cls||'btn-muted'),
        onclick:()=>{ov.classList.remove('open');res(b.value)}
      });
      btns.appendChild(btn);
    });
    ov.classList.add('open');
  });
}
const confirm1=msg=>modal(msg,[{label:'Cancel',cls:'btn-muted',value:false},{label:'OK',cls:'btn-amber',value:true}]);
function errModal(msg){
  byId('err-modal-msg').textContent=msg;
  byId('err-modal-overlay').classList.add('open');
}
async function doBannerDiscPermLink(){
  if(busy)return;busy=true;
  showWorking('Clearing link…');
  try{
    const d=await api({action:'disc-perm-link'});
    if(d.ok)toast('External link cleared','info');
    else toast(d.message||'Disconnect failed','err');
  }finally{endAction(500)}
}
function showReady(msg){
  byId('ready-msg').textContent=msg||'READY';
  const b=byId('ready-bar');
  b.classList.add('show');clearTimeout(_readyTimer);
  _readyTimer=setTimeout(()=>b.classList.remove('show'),4000);
}
function showWorking(msg){
  byId('working-msg').textContent=msg||'Working…';
  byId('working-overlay').classList.add('open');
  clearTimeout(_workTimer);_workTimer=setTimeout(hideWorking,30000);
}
function hideWorking(){
  clearTimeout(_workTimer);
  byId('working-overlay').classList.remove('open');
}
async function api(body,ms=25000){
  const ctrl=new AbortController();
  const tid=setTimeout(()=>ctrl.abort(),ms);
  try{
    const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body),signal:ctrl.signal});
    clearTimeout(tid);return await r.json();
  }catch(e){clearTimeout(tid);return{ok:false,message:e.name==='AbortError'?'Request timed out':'Network error'}}
}
const esc=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
// ── MODE_CAPS — single source of truth for per-mode UI behavior ────────────
// Stage 0 of the v8.0 M17 normalization pass. Every place that used to
// hardcode a mode-name list or an exclusion chain (tab visibility, the
// isDigital tests, the TG-grid-vs-reflector-grid render skip, the
// enabled-tabs checkbox filter) now reads from this table instead. This
// stage intentionally changes ZERO runtime behavior for existing modes —
// the `requires` arrays below reproduce the prior if/else chain in
// applyTabVisibility exactly (including the pre-existing quirk that STFU's
// visibility gate is `hasDvs`, not a dedicated `hasStfu` check — hasStfu is
// still accepted as a param for API-shape compatibility but was never
// actually branched on differently than the `else` case).
//   requires:      array of has-flags that must ALL be true to show the tab
//   isDigital:     true for every tab except ASL/ECHO (drives curTg restore
//                  on tab-switch and the keyed-poll dispatch)
//   reflectorGrid: true for modes with their own tap-to-connect grid
//                  (DSTAR/XLX today) — these render via their own grid
//                  function on the keyed-poll path instead of renderTGGrid
//   tgRefresh:     true if this mode's TG list should re-render on the
//                  keyed-poll path via the generic renderTGGrid() call
//
// M17 (Stage 1 of the port): added here ahead of its own UI so the
// exclusion-list-of-one problem doesn't recur once M17 gets real behavior.
// Stage 5 threads hasM17 through applyTabVisibility()'s signature and every
// call site, so requires:['hasM17'] now actually evaluates instead of being
// permanently inert.
const MODE_CAPS={
  ASL:   {requires:['hasAsl'],            isDigital:false, reflectorGrid:false, tgRefresh:false},
  ECHO:  {requires:['hasAsl','hasEcho'],  isDigital:false, reflectorGrid:false, tgRefresh:false},
  DMR:   {requires:['hasDvs'],            isDigital:true,  reflectorGrid:false, tgRefresh:true},
  STFU:  {requires:['hasDvs'],            isDigital:true,  reflectorGrid:false, tgRefresh:true},
  YSF:   {requires:['hasDvs'],            isDigital:true,  reflectorGrid:false, tgRefresh:true},
  FCS:   {requires:['hasDvs'],            isDigital:true,  reflectorGrid:false, tgRefresh:true},
  P25:   {requires:['hasDvs'],            isDigital:true,  reflectorGrid:false, tgRefresh:true},
  NXDN:  {requires:['hasDvs'],            isDigital:true,  reflectorGrid:false, tgRefresh:true},
  DSTAR: {requires:['hasDvs'],            isDigital:true,  reflectorGrid:true,  tgRefresh:false},
  XLX:   {requires:['hasDvs'],            isDigital:true,  reflectorGrid:true,  tgRefresh:false},
  M17:   {requires:['hasM17'],            isDigital:true,  reflectorGrid:true,  tgRefresh:false},
};
const STATIC_PAGES=Object.keys(MODE_CAPS);
function applyTabVisibility(enabled,hasAsl,hasDvs,hasStfu,hasEcho,hasM17){
  const flags={hasAsl,hasDvs,hasStfu,hasEcho,hasM17};
  const before=PAGES.slice().sort().join();
  PAGES.length=0;
  STATIC_PAGES.forEach(p=>{
    const caps=MODE_CAPS[p];
    const show=!!(caps.requires.every(f=>flags[f])&&Array.isArray(enabled)&&enabled.includes(p));
    const t=byId('tab-'+p.toLowerCase());
    if(t)t.style.display=show?'':'none';
    if(show)PAGES.push(p);
  });
  return PAGES.slice().sort().join()!==before;
}
function syncPageDisplay(){
  STATIC_PAGES.forEach(p=>{
    const el=byId('pg-'+p);
    const tab=byId('tab-'+p.toLowerCase());
    if(el)el.style.display='none';
    if(tab&&PAGES.includes(p))
      tab.className='tab'+(p===curPage&&!inEdit?' t-'+p.toLowerCase():'');
  });
  if(inEdit){
    byId('pg-EDIT').style.display='block';
    byId('tab-edit').className='tab t-edit';
    return;
  }
  byId('pg-EDIT').style.display='none';
  byId('tab-edit').className='tab';
  if(!curPage||!PAGES.includes(curPage))return;
  const el=byId('pg-'+curPage);
  if(el)el.style.display='block';
}
async function reTuneTab(page){
  busy=true;showWorking('Re-tuning '+page+'…');
  const srv=byId('dmr-srv-select');
  const server=srv?srv.value:'';
  try{
    const d=await api({action:'retune-tab',page,server},30000);
    if(d.ok){
      curTg=null;_pendingTune=null;
      setIndicator(null,page,false);
      // DMR retune: show network selector (not TG grid)
      if(page==='DMR'){
        _dmrNetSelectMode=true;   // D3 writer 3/4 — see declaration comment
        renderDmrNetSelect(_lastDmrServers,_lastActiveDmrServer);
      }
    }else{errModal(d.message);}
  }finally{endAction(500)}
}
async function clickTab(page){
  if(busy)return;
  if(!inEdit&&page===curPage){reTuneTab(page);return;}
  inEdit=false;busy=true;
  showWorking(`Switching to ${page}…`);
  const prevPage=curPage;
  if(prevPage&&PAGES.includes(prevPage)&&prevPage!=='ASL'&&prevPage!=='ECHO'){
    // XLX uses DSTAR tune-disconnect (DSTAR_UNLINK is handled inside action_tune for DSTAR mode)
    if(prevPage==='XLX'){
      await api({action:'tune',mode:'DSTAR',tg:TG_DISCONNECT,name:'Disconnect'}).catch(()=>{});
    }else if(prevPage==='M17'){
      // M17 isn't in TUNE_MODES (it never routes through Analog_Bridge's
      // generic tune action — see the M17_NODE constant comment), so the
      // else-branch's {action:'tune',mode:prevPage,...} would just get
      // "Unknown mode 'M17'" back and do nothing useful. Use M17's own
      // disconnect action instead, matching how leaving XLX is routed to
      // DSTAR's tune-disconnect above.
      await api({action:'m17-disconnect'}).catch(()=>{});
    }else{
      await api({action:'tune',mode:prevPage,tg:TG_DISCONNECT,name:'Disconnect'}).catch(()=>{});
    }
    curTg=null;_pendingTune=null;
    _curTgPerMode[prevPage]=null;  // no memory — returning to this tab starts clean
    setIndicator(null,prevPage,false);
  }
  try{
    const d=await api({action:'switch-tab',page},30000);
    if(d.ok){
      curPage=page;
      // Arriving at DMR via tab-switch: always show network selector, never the
      // TG list.  Set the flag AND render immediately from cached server data so
      // the user sees the selector the instant the tab becomes visible rather
      // than seeing the old TG list for up to 1s until the next refresh fires.
      if(page==='DMR'){
        _dmrNetSelectMode=true;   // D3 writer 2/4 — see declaration comment
        renderDmrNetSelect(_lastDmrServers,_lastActiveDmrServer);
      }
      const isDigital=!!(MODE_CAPS[page]&&MODE_CAPS[page].isDigital);

      // RC-2: force-sync body.radio-keyed immediately on tab arrival.
      // pollKeyed() only toggles on *change*; sync unconditionally here so
      // the CSS is correct from the first render on this tab.
      document.body.classList.toggle('radio-keyed', _lastKeyed);

      // RC-1: restore curTg from server state if a TG is genuinely active.
      // The server clears current_fav on tab leave, so a non-null value here
      // means a TG is still tuned (e.g. we returned to a tab mid-call).
      // This is not tab memory — it reflects real server state.
      if(isDigital&&d.current_fav){
        curTg={mode:page,tg:d.current_fav};
        _curTgPerMode[page]=curTg;
      }else{
        curTg=null;
        _curTgPerMode[page]=null;
      }

      setIndicator(curTg?curTg.tg:null,page,_lastKeyed);
      syncPageDisplay();
    }
    if(!d.ok)errModal(d.message);
  }finally{endAction(1000)}
}
function clickEdit(){if(inEdit)return;inEdit=true;syncPageDisplay();edReload()}

// ── Edit section collapse state ───────────────────────────────────────────────
// Keys are section content div IDs. Persists for the session; not saved to conf.
const _edCollapsed = {};

function toggleEdSection(id){
  const el = byId(id);
  if(!el) return;
  _edCollapsed[id] = !_edCollapsed[id];
  el.style.display = _edCollapsed[id] ? 'none' : '';
  // Update button label on the sibling header
  const hdr = el.previousElementSibling;
  if(hdr){
    const btn = hdr.querySelector('button');
    if(btn) btn.textContent = _edCollapsed[id] ? 'Show' : 'Hide';
  }
}

function applyEdCollapsed(){
  Object.entries(_edCollapsed).forEach(([id, collapsed]) => {
    const el = byId(id);
    if(!el) return;
    el.style.display = collapsed ? 'none' : '';
    const hdr = el.previousElementSibling;
    if(hdr){ const btn = hdr.querySelector('button'); if(btn) btn.textContent = collapsed ? 'Show' : 'Hide'; }
  });
}

// S1 — EDIT tab back button navigation path: returns to prior page WITHOUT triggering retune.
// Called by: <button onclick="showPage(curPage)">Back</button> in EDIT tab (line ~3394)
// Contrast with clickTab(): uses clickTab() path (calls reTuneTab on same-page click).
// This separation prevents unintended retune-on-back behavior when DMR tab was active
// before entering EDIT.  Example: User is on DMR → clicks EDIT → makes changes → clicks Back.
// Expected: returns to DMR without showing network selector (user didn't click DMR tab again).
// If showPage() incorrectly called clickTab() or reTuneTab(), it would trigger retune and
// show network selector unexpectedly.  Maintain this distinction to prevent regression.
function showPage(page){if(!PAGES.includes(page))return;inEdit=false;curPage=page;syncPageDisplay()}
function setIndicator(value,mode,keyed,name,state){
  const el    =byId('tg-indicator');
  const valEl =byId('tg-value');
  const dotL  =byId('tg-dot-l');
  const dotR  =byId('tg-dot-r');
  if(!el)return;
  function setDots(on){
    const cls='dot '+(on?'dot-on':'dot-off');
    if(dotL)dotL.className=cls;
    if(dotR)dotR.className=cls;
  }
  // Disconnect / idle path
  if(!value||value===TG_DISCONNECT){
    if(valEl)valEl.textContent=mode||'——';
    setDots(false);
    el.className='ind-idle';
    el.removeAttribute('title');
    return;
  }
  // Value: raw tg always; friendly name as tooltip
  if(valEl){
    valEl.textContent=value;
    if(name&&name!==value)el.title=name;
    else el.removeAttribute('title');
  }
  setDots(true);
  // Outer class: base colour + optional state modifier
  const base=keyed?'ind-rx':'ind-'+(mode||'').toLowerCase();
  if(state==='confirmed'){
    el.className=base+' ind-confirmed';
    // One-shot: remove ind-confirmed after animation completes
    setTimeout(()=>{
      const cur=byId('tg-indicator');
      if(cur)cur.className=base;
    },650);
  }else{
    el.className=base;
  }
}
// ── DMR network selector ──────────────────────────────────────────────────────
// Renders a tile grid of DMR networks into #dmr-grid.  Called from
// applyGridState() when _dmrNetSelectMode is true.  Tiles share the same
// .row-grid CSS as TG tiles so they look like a natural TG list.
// Clicking a tile calls switchDmrServer(name), which clears _dmrNetSelectMode
// and transitions to the normal TG grid.
function renderDmrNetSelect(servers,activeServer){
  const el=byId('dmr-grid');if(!el)return;
  if(!servers||!servers.length){
    el.innerHTML='<div style="padding:1rem;color:var(--muted);font-family:var(--mono);font-size:.858rem">No DMR networks configured</div>';
    return;
  }
  let n=0;
  el.innerHTML='<div class="net-sel-hdr">Select Network</div>'+
    servers.map(s=>{
      if(!s.name)return '';
      n++;
      const active=s.name===activeServer;
      const cls=active?'row-grid active-dmr':'row-grid';
      const dotCls=active?'dot-on':'dot-off';
      const sUrl=s.net_url||'';
      const sLh=`<button class="btn-last${sUrl?'':' lh-off'}" ${sUrl?`onclick="event.stopPropagation();openLast('${esc(sUrl)}')"`:''} title="Last Heard">LH</button>`;
      const sCls=cls+' has-lh';
      return `<div class="${sCls}" onclick="switchDmrServer('${esc(s.name)}')" title="${esc(s.name)}">
        <span class="row-num">${n}</span>
        <div class="dot ${dotCls}"></div>
        <span class="row-name">${esc(s.name)}</span>${sLh}</div>`;
    }).join('');
  if(!n)el.innerHTML='<div style="padding:1rem;color:var(--muted);font-family:var(--mono);font-size:.858rem">No DMR networks configured</div>';
}
function renderTGGrid(elId,tgs,mode){
  const el=byId(elId);if(!el)return;const m=mode.toLowerCase();
  // DEV-NOTE (v7.760): P25 per-row-LH conversion (spec: "P25 -> Per-Row LH,
  // mirror NXDN v7.759 conversion") was found ALREADY IMPLEMENTED in the
  // v7.759 upload this session started from -- hasRowLh, loadTgData() P25
  // url mapping, removal of lh-btn-P25 / its _refreshLhBtns() line, and the
  // edRender() isSectionUrl/isRowUrl split were all already in place. No
  // functional edits were made; this delivery is a version bump (7.759 ->
  // 7.760) + header-comment sync (line 3 was stale at "v7.758") to reflect
  // and lock in that state as a clean checkpoint.
  const hasRowLh=mode==='YSF'||mode==='FCS'||mode==='P25'||mode==='NXDN';
  if(!tgs||!tgs.length){el.innerHTML=`<div style="padding:1rem;color:var(--muted);font-family:var(--mono);font-size:.858rem">No ${mode} entries</div>`;return}
  let n=0;
  el.innerHTML=tgs.map(tg=>{
    if(tg.name===TG_BLANK_NAME&&tg.tg===TG_BLANK_ADDR)return '';
    n++;
    const disc=tg.tg===TG_DISCONNECT;
    const active=curTg&&curTg.mode===mode&&curTg.tg===tg.tg;
    const url=tg.url||'';                 // per-row user URL only (defaults treated as unset)
    const showLh=hasRowLh&&!disc;         // YSF/FCS rows always render the LH slot
    // Trailing '#' marks a DMR private call (STFU) — display-only detection,
    // the tune path always receives the stored string verbatim.
    const hasPvt=(!disc&&typeof tg.tg==='string'&&tg.tg.endsWith('#'));
    // L18: every extra grid child needs a matching column-template variant (see has-lh)
    const sfx=`${showLh?' has-lh':''}${hasPvt?' has-pvt':''}`;
    const cls=disc?'row-grid disc':active?`row-grid active-${m}${sfx}`:`row-grid${sfx}`;
    const dotCls=active?'dot-on':'dot-off';
    const lhBtn=showLh?`<button class="btn-last${url?'':' lh-off'}" ${url?`onclick="event.stopPropagation();openLast('${esc(url)}')"`:''} title="Last Heard">LH</button>`:'';
    const pvtChip=hasPvt?'<span class="pvt-chip" title="Private call">PVT</span>':'';
    return `<div class="${cls}" onclick="${disc?'':` tuneTG('${esc(mode)}','${esc(tg.tg)}','${esc(tg.name)}')`}" ${disc?'':`title="${esc(tg.name)}"` }>
      <span class="row-num">${n}</span>
      <div class="dot ${dotCls}"></div>
      <span class="row-name">${esc(tg.name)}</span>${pvtChip}${lhBtn}</div>`;
  }).join('');
  if(!n)el.innerHTML=`<div style="padding:1rem;color:var(--muted);font-family:var(--mono);font-size:.858rem">No ${mode} entries</div>`;
}
function renderASLGrid(nodes,fav){
  const el=byId('asl-grid');if(!el)return;let n=0;
  el.innerHTML=nodes.map(nd=>{
    if(nd.name===TG_BLANK_NAME||nd.node===TG_BLANK_ADDR)return '';
    n++;
    const active=fav===nd.node;
    return `<div class="${active?'row-grid active-asl':'row-grid'}" onclick="aslConnect('${esc(nd.node)}','${esc(nd.name)}')" title="${esc(nd.name)}">
      <span class="row-num">${n}</span>
      <div class="dot ${active?'dot-on':'dot-off'}"></div>
      <span class="row-name">${esc(nd.name)}</span></div>`;
  }).join('');
  if(!n)el.innerHTML='<div style="padding:1rem;color:var(--muted);font-family:var(--mono);font-size:.858rem">No ASL nodes saved</div>';
}
function renderEchoGrid(nodes,fav){
  const el=byId('echo-grid');if(!el)return;let n=0;
  el.innerHTML=nodes.map(nd=>{
    if(nd.name===TG_BLANK_NAME||nd.node===TG_BLANK_ADDR)return '';
    n++;
    const active=fav===nd.node;
    return `<div class="${active?'row-grid active-echo':'row-grid'}" onclick="echoConnect('${esc(nd.node)}','${esc(nd.name)}')" title="${esc(nd.name)}">
      <span class="row-num">${n}</span>
      <div class="dot ${active?'dot-on':'dot-off'}"></div>
      <span class="row-name">${esc(nd.name)}</span></div>`;
  }).join('');
  if(!n)el.innerHTML='<div style="padding:1rem;color:var(--muted);font-family:var(--mono);font-size:.858rem">No Echo nodes saved</div>';
}
function buildModuleOptions(selected,includeAll){
  // Returns <option> HTML for modules A–Z, optionally prefixed with the
  // M17 "@ALL" wildcard (Stage 4 addition, v8.0 M17 normalization pass).
  // Existing callers (DSTAR/XLX quick-tune bars, renderReflectorGrid's
  // default path) never pass includeAll, so `includeAll` is undefined →
  // falsy → the @ALL option is skipped and output is byte-identical to
  // the pre-Stage-4 version. Stage 5 passes includeAll:true for M17.
  let h='';
  if(includeAll)h+=`<option value="@ALL"${selected==='@ALL'?' selected':''}>All Modules</option>`;
  for(let i=0;i<26;i++){
    const l=String.fromCharCode(65+i);
    h+=`<option value="${l}"${l===selected?' selected':''}>Mod-${l}</option>`;
  }
  return h;
}
function initModuleSelects(){
  // Populate the quick-bar module dropdowns on first load
  ['qt-DSTAR-mod','qt-XLX-mod'].forEach(id=>{
    const el=byId(id);
    if(el&&!el.dataset.init){
      el.innerHTML=buildModuleOptions('A');
      el.value='A';
      el.dataset.init='1';
    }
  });
  // M17's quick-bar dropdown includes the @ALL wildcard and defaults to it
  // (join every module on the reflector) rather than defaulting to 'A' like
  // DSTAR/XLX above — matches the saved-row default in action_save_m17().
  const m17el=byId('qt-M17-mod');
  if(m17el&&!m17el.dataset.init){
    m17el.innerHTML=buildModuleOptions('@ALL',true);
    m17el.value='@ALL';
    m17el.dataset.init='1';
  }
}
function getReflectorMod(gridId,i){
  const sel=document.querySelector('#'+gridId+' .ref-mod-sel[data-idx="'+i+'"]');
  return sel?sel.value:'A';
}
function getDstarMod(i){return getReflectorMod('dstar-grid',i);}
function getXlxMod(i){return getReflectorMod('xlx-grid',i);}
function getM17Mod(i){return getReflectorMod('m17-grid',i);}
function renderReflectorGrid(gridId,refs,activeTune,cfg){
  const el=byId(gridId);
  if(!el)return;
  if(!refs||!refs.length){el.innerHTML='<div style="padding:1rem;color:var(--muted);font-family:var(--mono);font-size:.858rem">'+cfg.emptyMsg+'</div>';return;}
  // v7.761 — tap-whole-row-to-connect (mirrors ASL/Echo/DMR/STFU/YSF/FCS/
  // P25/NXDN pattern). Re-tapping the already-active row just reissues the
  // same connect (harmless). Disconnect is bottom-bar only
  // (doDstarDisconnect/doXlxDisconnect) — no per-row button.
  // v7.763 — audit fix: empty-state color now uses var(--muted) (was a
  // stray hardcoded #5a7898, the row-num/label gray, inconsistent with
  // every other tab's empty message). Rows now carry a row-num span too,
  // matching ASL/ECHO/TG-grid rows — reflector rows were the only ones
  // in the app without a leading index number.
  //
  // Stage 4 (v8.0 M17 normalization): this function used to hardcode the
  // assumption that every reflector row is a single "base+module" tg
  // string (XLX/DSTAR's shape — r.tg, e.g. "XLX334A"). M17's rows carry
  // base/module/ip as separate fields instead (see the backend _parse_conf
  // M17 branch from Stage 1), so three optional cfg hooks were added to
  // keep this ONE function correct for both shapes without changing
  // XLX/DSTAR's behavior at all:
  //   cfg.isBlank(r)             — placeholder-row test
  //                                 (default: r.tg===TG_BLANK_ADDR)
  //   cfg.parseRow(r,i)          — returns {base, defMod, hostLabel}
  //                                 (default: slices r.tg the way
  //                                 XLX/DSTAR always did)
  //   cfg.makeTuneKey(base,mod)  — builds the string compared against
  //                                 activeTune (default: base+mod+'L',
  //                                 XLX/DSTAR's tune-string format; M17
  //                                 uses base+'|'+mod instead, matching
  //                                 action_m17_connect()'s fav string)
  //   cfg.includeAllModule       — passed through to buildModuleOptions()
  //                                 so the module <select> offers @ALL
  // renderDstarGrid()/renderXlxGrid() below pass none of these, so they
  // fall back to exactly the logic that was inlined here before Stage 4 —
  // zero behavior change for the two existing callers. renderM17Grid()
  // (Stage 5) is the first caller to actually use them.
  const isBlank     = cfg.isBlank     || (r=>r.tg===TG_BLANK_ADDR);
  const parseRow     = cfg.parseRow     || (r=>({base:r.tg.slice(0,-2)||r.tg, defMod:r.tg.slice(-2,-1)||'A', hostLabel:r.tg}));
  const makeTuneKey  = cfg.makeTuneKey  || ((base,mod)=>base+mod+'L');
  let _rn=0;el.innerHTML=refs.map((r,i)=>{
    if(r.name===TG_BLANK_NAME||isBlank(r))return '';
    _rn++;
    const {base,defMod,hostLabel}=parseRow(r,i);
    const selMod=cfg.modSel[i]||defMod;
    const tuneFull=makeTuneKey(base,selMod);
    const active=activeTune===tuneFull;
    const cls=active?'ref-row '+cfg.activeClass:'ref-row';
    const url=r.url||'';                  // per-row user URL only (defaults treated as unset)
    const lhBtn=`<button class="btn-last${url?'':' lh-off'}" ${url?`onclick="event.stopPropagation();openLast('${esc(url)}')"`:''} title="Last Heard">LH</button>`;
    const refCls=cls+' has-lh ref-tap';
    return `<div class="${refCls}" onclick="${cfg.connectFn(base,i,r.name)}" title="${esc(r.name)}">
      <span class="row-num">${_rn}</span>
      <div class="dot ${active?'dot-on':'dot-off'}"></div>
      <div class="ref-info">
        <span class="ref-name">${esc(r.name)}</span>
        <span class="ref-host">${esc(hostLabel)}</span>
      </div>
      <select class="ref-mod-sel" data-idx="${i}" onclick="event.stopPropagation()" onchange="event.stopPropagation();${cfg.modSelName}[${i}]=this.value">${buildModuleOptions(selMod,!!cfg.includeAllModule)}</select>
      ${lhBtn}
    </div>`;
  }).join('');
  if(!_rn)el.innerHTML='<div style="padding:1rem;color:var(--muted);font-family:var(--mono);font-size:.858rem">'+cfg.emptyMsg+'</div>';
}
function renderDstarGrid(refs,activeTune){
  renderReflectorGrid('dstar-grid',refs,activeTune,{
    emptyMsg:'No D-STAR reflectors saved',activeClass:'active-dstar',mode:'DSTAR',
    modSel:dstarModSel,modSelName:'dstarModSel',btnConn:'btn btn-conn-pink',
    connectFn:(base,i,name)=>`dstarConnect('${esc(base)}',getDstarMod(${i}),'${esc(name)}')`
  });
}
function renderXlxGrid(refs,activeTune){
  renderReflectorGrid('xlx-grid',refs,activeTune,{
    emptyMsg:'No XLX reflectors saved',activeClass:'active-xlx',mode:'XLX',
    modSel:xlxModSel,modSelName:'xlxModSel',btnConn:'btn btn-conn',
    connectFn:(base,i,name)=>`xlxConnect('${esc(name)}','${esc(base)}',getXlxMod(${i}))`
  });
}
// renderM17Grid uses the shared renderReflectorGrid() infrastructure built
// in Stage 4, rather than a bespoke grid function — M17 differs from
// DSTAR/XLX in two ways, both covered by cfg hooks instead of a rewrite:
//   1. Data shape/active-match: base and module are stored as separate
//      fields (not encoded into a single tune string like base+module+'L'),
//      since ip has no suffix to decode a module out of. The active
//      favourite is compared as "base|module" (see current_fav's format,
//      set by action_m17_connect) via cfg.makeTuneKey — base is the true
//      identity written into the ini Name= field; ip alone can't
//      disambiguate two reflectors sharing a bridge address.
//   2. Host label shows "base · ip" instead of a single tg string, via
//      cfg.parseRow's hostLabel.
// Row-tap-to-connect, the LH button, and module-select click-stop behavior
// are all inherited unchanged from renderReflectorGrid() — no per-row
// Connect/Disconnect button, same as DSTAR/XLX (bottom-bar Disconnect only).
function renderM17Grid(refs,activeFav){
  renderReflectorGrid('m17-grid',refs,activeFav,{
    emptyMsg:'No M17 reflectors saved',activeClass:'active-m17',mode:'M17',
    modSel:m17ModSel,modSelName:'m17ModSel',includeAllModule:true,
    isBlank:r=>r.ip===TG_BLANK_ADDR,
    parseRow:r=>({base:r.base||r.name,defMod:r.module||'@ALL',hostLabel:(r.base||r.name)+' · '+r.ip}),
    makeTuneKey:(base,mod)=>base+'|'+mod,
    connectFn:(base,i,name)=>{
      const ip=(refs[i]&&refs[i].ip)||'';
      return `m17Connect('${esc(name)}','${esc(base)}','${esc(ip)}',getM17Mod(${i}))`;
    }
  });
}
// ── Last Heard helpers ────────────────────────────────────────────────────────
function openLast(url){
  if(!url)return;
  let u=String(url).trim();
  // Bare host/IP (no scheme) would resolve relative to the dashboard origin
  // (e.g. http://192.168.x.x:8989/78.129.135.58) — prepend http:// so it opens
  // as an absolute URL. Existing http(s):// values pass through untouched.
  if(!/^[a-z][a-z0-9+.-]*:\/\//i.test(u)) u='http://'+u;
  // Named target reuses the same browser tab for every LH press — no tab pile-up.
  // Browser security prevents JavaScript from keeping focus here after opening;
  // use Ctrl+Tab or click the dashboard tab to return.
  window.open(u,'asl_dvs_lh');
}
function openDmrLast(){
  // Use _lastDmrServers (live from /api/status) — always available,
  // not dependent on edit tab having been opened.
  const activeSrv=(_lastDmrServers||[]).find(s=>s.name===_lastActiveDmrServer);
  openLast(activeSrv?activeSrv.net_url||'':'');
}
function openModeLast(m){openLast(modeNetUrls[m]||'');}
function _updateLhBtn(id,url){const el=byId(id);if(el)el.classList.toggle('lh-off',!url);}
function _refreshLhBtns(){
  // Use _lastDmrServers (live from /api/status) rather than dmrSrvRows
  // (edit tab only) so the DMR LH button works without opening the edit tab.
  const activeSrv=(_lastDmrServers||[]).find(s=>s.name===_lastActiveDmrServer);
  _updateLhBtn('lh-btn-DMR', activeSrv?activeSrv.net_url||'':'');
  _updateLhBtn('lh-btn-ASL',  modeNetUrls.ASL||'');
  _updateLhBtn('lh-btn-ECHO', modeNetUrls.ECHO||'');
  _updateLhBtn('lh-btn-STFU', modeNetUrls.STFU||'');
  // P25/NXDN moved to per-row LH buttons (like YSF/FCS) — no quick-bar button to update.
}

/* endAction(refreshDelay) — uniform action teardown: hide the working
   overlay, release the busy latch, schedule a refresh (v7.744; was
   copy-pasted at 10 sites with varying delays). */
function endAction(refreshDelay){
  hideWorking();busy=false;setTimeout(refresh,refreshDelay);
}
async function apiAction(payload,workingMsg,onOk,timeoutMs=8000){
  if(busy)return;busy=true;
  showWorking(workingMsg);
  try{
    const d=await api(payload,timeoutMs);
    if(d.ok)onOk(d);
    else errModal(d.message);
  }finally{endAction(800)}
}
async function dstarConnect(base,module,name){
  if(busy)return;
  dimGrid('DSTAR');
  try{await apiAction(
    {action:'dstar-connect',base,module,name},
    `Connecting ${base}${module}L…`,
    d=>{curTg={mode:'DSTAR',tg:base+module+'L'};_curTgPerMode['DSTAR']=curTg;toast(d.message,'ok','dstar');renderDstarGrid(_lastDstarRefs,curTg.tg);setIndicator(curTg.tg,'DSTAR',false);},
    30000
  );}finally{undimGrid('DSTAR');}
}
async function xlxConnect(name,base,module){
  if(busy)return;
  dimGrid('XLX');
  try{await apiAction(
    {action:'xlx-connect',name,base,module},
    `Connecting ${base}${module}L…`,
    d=>{curTg={mode:'XLX',tg:base+module+'L'};_curTgPerMode['XLX']=curTg;toast(d.message,'ok','xlx');renderXlxGrid(_lastXlxRefs,curTg.tg);setIndicator(curTg.tg,'XLX',false,base+' Mod-'+module);},
    30000
  );}finally{undimGrid('XLX');}
}
async function m17Connect(name,base,ip,module){
  if(busy)return;
  dimGrid('M17');
  try{await apiAction(
    {action:'m17-connect',name,base,ip,module},
    `Connecting ${base} Mod-${module}…`,
    d=>{curTg={mode:'M17',tg:base+'|'+module};_curTgPerMode['M17']=curTg;toast(d.message,'ok','m17');renderM17Grid(_lastM17Refs,curTg.tg);setIndicator(curTg.tg,'M17',false,base+' Mod-'+module);},
    30000
  );}finally{undimGrid('M17');}
}
async function doAslDiscCurrent(){
  await apiAction(
    {action:'asl-disc-current'},
    'Disconnecting all…',
    ()=>{curTg=null;setIndicator(null,'ASL',false);renderASLGrid(_lastAslNodes,null);showReady('ASL DISCONNECTED');},
    30000
  );
}
async function doEchoDisc(){
  await apiAction(
    {action:'echo-disc'},
    'Echo disconnecting…',
    ()=>{_lastEchoFav=null;setIndicator(null,'ECHO',false);renderEchoGrid(_lastEchoNodes,null);showReady('Echo DISCONNECTED');},
    30000
  );
}
async function doDiscAll(){
  await apiAction(
    {action:'disc-all'},
    'Emergency disconnect — restarting services…',
    ()=>{
      curTg=null;_pendingTune=null;
      setIndicator(null,curPage,false);
      if(curPage==='DSTAR')renderDstarGrid(_lastDstarRefs,null);
      if(curPage==='XLX')renderXlxGrid(_lastXlxRefs,null);
      if(curPage==='M17')renderM17Grid(_lastM17Refs,null);
      // DMR: return to network selector after a full disconnect/restart.
      // The bridge stack has been restarted; user should re-confirm network.
      // Other tabs stay on their current grid — no change needed.
      if(curPage==='DMR') _dmrNetSelectMode=true;  // D3 writer 4/4 — see declaration comment
    },
    35000
  );
}
async function doModeDisconnect(mode){
  // Stage 2 Change 2 — soft per-tab disconnect for DMR/STFU/YSF/FCS/P25/NXDN.
  // Routes through the existing action_tune(tg=disconnect) branch instead of
  // the hard action_disconnect_all() reset — retunes immediately, no service
  // restarts. "Disconnect All" remains available as a secondary action for
  // genuinely stuck states (see doDiscAll()).
  const gridId=mode.toLowerCase()+'-grid';
  await apiAction(
    {action:'tune',mode,tg:TG_DISCONNECT,name:''},
    mode+' disconnecting…',
    ()=>{
      curTg=null;_curTgPerMode[mode]=null;_pendingTune=null;
      setIndicator(null,mode,false);
      renderTGGrid(gridId,_lastTgs[mode]||[],mode);
      showReady(mode+' | DISCONNECTED');
    },
    10000
  );
}
async function doDstarDisconnect(){
  await apiAction(
    {action:'dstar-disconnect'},
    'D-STAR disconnecting…',
    ()=>{
      curTg=null;_pendingTune=null;
      setIndicator(null,'DSTAR',false);
      renderDstarGrid(_lastDstarRefs,null);
      showReady('D-STAR DISCONNECTED');
    },
    10000
  );
}
async function doXlxDisconnect(){
  await apiAction(
    {action:'xlx-disconnect'},
    'XLX disconnecting…',
    ()=>{
      curTg=null;_pendingTune=null;
      setIndicator(null,'XLX',false);
      renderXlxGrid(_lastXlxRefs,null);
      showReady('XLX DISCONNECTED');
    },
    10000
  );
}
async function doM17Disconnect(){
  await apiAction(
    {action:'m17-disconnect'},
    'M17 disconnecting…',
    ()=>{
      curTg=null;_pendingTune=null;
      setIndicator(null,'M17',false);
      renderM17Grid(_lastM17Refs,null);
      showReady('M17 DISCONNECTED');
    },
    10000
  );
}
async function reflectorQuickConnect(baseId,modId,errMsg,connectFn){
  const base=byId(baseId).value.trim().toUpperCase();
  const mod=(byId(modId).value||'A').toUpperCase();
  if(!base){toast(errMsg,'err');return;}
  await connectFn(base,mod);
}
async function dstarQuickConnect(){
  await reflectorQuickConnect('qt-DSTAR-base','qt-DSTAR-mod',
    'Enter a reflector (e.g. REF001)',
    (base,mod)=>dstarConnect(base,mod,`${base} Mod-${mod}`));
}
async function xlxQuickConnect(){
  await reflectorQuickConnect('qt-XLX-base','qt-XLX-mod',
    'Enter a reflector (e.g. XLX334)',
    (base,mod)=>xlxConnect(`${base} Mod-${mod}`,base,mod));
}
async function m17QuickConnect(){
  // Custom rather than reflectorQuickConnect(): that helper uppercases and
  // treats the field as a reflector callsign/base. M17's quick-bar field is
  // a plain IP/hostname with no separate name/base field, so ip doubles as
  // both the display name and the ini-identity base for ad-hoc lookups
  // (saved rows in Edit have proper name/base pairs — see m17SyncFromDOM).
  const ipEl=byId('qt-M17-ip');
  const modEl=byId('qt-M17-mod');
  const ip=ipEl?ipEl.value.trim():'';
  const mod=((modEl&&modEl.value)||'@ALL').toUpperCase();
  if(!ip){toast('Enter a reflector IP first','err');return;}
  await m17Connect(ip,ip,ip,mod);
}
async function tuneTG(mode,tg,name){
  if(busy)return;
  if(tg!==TG_DISCONNECT&&curTg&&curTg.mode===mode&&curTg.tg===tg)return;
  busy=true;
  _pendingTune=null;
  try{
    if(mode!==curPage&&!inEdit&&curPage!=='ASL'&&curPage!=='ECHO'){
      curTg=null; // null immediately so stale duplicate-tune guard can't fire
      dimGrid(curPage);
      showWorking(`Switching to ${mode}…`);
      try{
        await api({action:'tune',mode:curPage,tg:TG_DISCONNECT,name:'Disconnect'}).catch(()=>{});
        setIndicator(null,curPage,false);
        const sw=await api({action:'switch-tab',page:mode},30000);
        if(!sw.ok){
          undimGrid(curPage);
          errModal(sw.message||'Tab switch failed');
          return;
        }
        undimGrid(curPage);
        curPage=mode;syncPageDisplay();
      }finally{hideWorking();}
    }
    dimGrid(mode);
    showWorking(`${mode} → ${name}`);
    try{
      const d=await api({action:'tune',mode,tg,name});
      if(d.ok){
        curTg=tg===TG_DISCONNECT?null:{mode,tg};
        _curTgPerMode[mode]=curTg;   // null on disconnect, {mode,tg} on tune
        if(tg===TG_DISCONNECT){
          showReady(`${mode} DISCONNECTED`);
          setIndicator(null,mode,false);
          _pendingTune=null;
        }else{
          setIndicator(tg,mode,false,name);
          _pendingTune={tg,mode,name,at:Date.now()};
          pollAbInfo(); // fire immediately — don't wait up to 10s
        }
        const ap=(curPage||mode).toLowerCase();
        renderTGGrid(ap+'-grid',_lastTgs[mode]||[],mode);
      }
      if(!d.ok)errModal(d.message);
    }finally{undimGrid(mode);hideWorking();setTimeout(refresh,500)}
  }finally{busy=false;}
}
async function doQuickTune(mode){
  if(busy)return;
  const inp=byId('qt-'+mode);
  const tg=inp?inp.value.trim():'';
  if(!tg){
    // DMR with empty field: retune the currently-selected network
    if(mode==='DMR'){
      const sel=byId('dmr-srv-select');
      const srv=sel?sel.value:'';
      if(srv){
        switchDmrServer(srv);
        return;
      }
    }
    toast('Enter a TG / address first','err');
    return;
  }
  _pendingTune=null;
  dimGrid(mode);
  try{await apiAction(
    {action:'quick-tune',mode,tg},
    `${mode} → ${tg}`,
    d=>{
      curTg={mode,tg};
      _curTgPerMode[mode]=curTg;
      if(inp)inp.value='';
      setIndicator(tg,mode,false,tg);
      _pendingTune={tg,mode,name:tg,at:Date.now()};
      pollAbInfo();
    },
    25000
  );}finally{undimGrid(mode);}
}
async function aslConnect(node,name){
  if(busy)return;
  dimGrid('ASL');
  try{await apiAction(
    {action:'asl-connect',node,name},
    `Connecting ${name}…`,
    d=>{curTg={mode:'ASL',tg:node};setIndicator(node,'ASL',false);renderASLGrid(_lastAslNodes,node);showReady(`ASL READY — ${name}`);},  // A5 writer 3/3 (optimistic render) — see applyGridState comment
    30000
  );}finally{undimGrid('ASL');}
}
async function doConnectByNumber(){
  const inp=byId('cbn-input');
  const node=inp?inp.value.trim():'';
  if(!node){toast('Enter a node number first','err');return}
  if(busy)return;
  dimGrid('ASL');
  try{await apiAction(
    {action:'connect-by-number',node},
    `Connecting node ${node}…`,
    d=>{if(inp)inp.value='';curTg={mode:'ASL',tg:node};setIndicator(node,'ASL',false);renderASLGrid(_lastAslNodes,node);showReady(`ASL READY — ${node}`);},
    30000
  );}finally{undimGrid('ASL');}
}
async function echoConnect(node,name){
  if(busy)return;
  dimGrid('ECHO');
  try{await apiAction(
    {action:'echo-connect',node,name},
    `Echo connecting ${name}…`,
    d=>{_lastEchoFav=node;setIndicator(node,'ECHO',false);renderEchoGrid(_lastEchoNodes,node);showReady(`Echo READY — ${name}`);},
    30000
  );}finally{undimGrid('ECHO');}
}
async function doEchoConnectByNumber(){
  const inp=byId('echo-input');
  const node=inp?inp.value.trim():'';
  if(!node){toast('Enter a node number first','err');return}
  if(!/^\d{1,6}$/.test(node)){toast('EchoLink node numbers are 1–6 digits','err');return}
  if(busy)return;
  dimGrid('ECHO');
  try{await apiAction(
    {action:'echo-connect-by-number',node},
    `Echo connecting ${node}…`,
    d=>{if(inp)inp.value='';_lastEchoFav=node;setIndicator(node,'ECHO',false);renderEchoGrid(_lastEchoNodes,node);showReady(`Echo READY — ${node}`);},
    30000
  );}finally{undimGrid('ECHO');}
}
async function switchDmrServer(name){
  if(busy||!name)return;
  busy=true;
  const DMR_READY_TIMEOUT=20000;
  const DMR_READY_INTERVAL=1000;
  showWorking('Switching to '+name+'…');
  try{
    const d=await api({action:'switch-dmr-server',name},30000);
    if(!d.ok){
      // A failed full switch has already issued TG_DISCONNECT server-side —
      // clear the indicator to match (parity with the ≤v7.744 early clear).
      curTg=null;_curTgPerMode['DMR']=null;setIndicator(null,'DMR',false);
      errModal(d.message);return;
    }
    // D1 fix: only clear net-select mode once the switch is confirmed ok.
    // Previously this was cleared unconditionally at the top of the function,
    // so a failed switch (wrong password / unreachable host) still exited
    // net-select mode — the next poll's applyGridState() would then replace
    // the tile picker with a stale TG grid even though nothing connected.
    _dmrNetSelectMode=false;   // D3 — sole clear site; see declaration comment
    const empty=d.message&&d.message.includes('|tgs_empty');
    // N1 — backend skipped the network tune: same password@address as the
    // live login (duplicate entry or reselecting the current network).  No
    // disconnect was issued, so keep curTg/indicator intact and bypass the
    // 20 s ready-wait — just refresh the grid for the selected entry.
    if(d.message&&d.message.includes('|same_net')){
      showReady('DMR → '+name+' ONLINE');
      toast(name+' — already connected','ok','dmr');
      if(empty)toast('Set up Talkgroups in EDIT','info');
      await loadTgData();
      _refreshLhBtns();
      return;
    }
    // Real switch confirmed — the backend disconnected the old TG, so the
    // indicator clear is only valid from this point on (moved from the
    // pre-request position in ≤v7.744, where a skipped switch would have
    // blanked a still-live TG).
    curTg=null;_curTgPerMode['DMR']=null;setIndicator(null,'DMR',false);
    const deadline=Date.now()+DMR_READY_TIMEOUT;
    let secs=Math.round(DMR_READY_TIMEOUT/1000);
    let ready=false;
    while(Date.now()<deadline){
      showWorking('Connecting to '+name+'… ('+secs+'s)');
      try{
        const ctrl=new AbortController();
        const tid=setTimeout(()=>ctrl.abort(),2000);
        const r=await fetch('/api/dmr-ready',{signal:ctrl.signal});
        clearTimeout(tid);
        const rd=await r.json();
        if(rd.ready){ready=true;break;}
      }catch(_){}
      await new Promise(res=>setTimeout(res,DMR_READY_INTERVAL));
      secs=Math.max(0,Math.round((deadline-Date.now())/1000));
    }
    if(ready){
      showReady('DMR → '+name+' ONLINE');
      toast(name+' connected','ok','dmr');
    }else{
      toast(name+' — no response after 20s','info','dmr');
    }
    if(empty)toast('Set up Talkgroups in EDIT','info');
    await loadTgData();
    _refreshLhBtns();
  }finally{endAction(500)}
}
async function doReboot(){if(!await confirm1('Reboot the system?'))return;const d=await api({action:'reboot'});if(!d||!d.ok){toast(d?.message||'Reboot failed','err');return}toast(d.message||'Rebooting…','info')}
async function doShutdown(){if(!await confirm1('Shut down the system?'))return;const d=await api({action:'shutdown'});if(!d||!d.ok){toast(d?.message||'Shutdown failed','err');return}toast(d.message||'Shutting down…','info')}
function applyTabState(d){
  if(_firstPoll){
    _hasAsl=!!d.has_asl;_hasDvs=!!d.has_dvs;_hasStfu=!!d.has_stfu;_hasEcho=!!d.has_echo;_hasM17=!!d.has_m17;
    if(!d.has_asl&&!d.has_dvs){
      byId('tabs-strip').style.display='none';
      PAGES.length=0;inEdit=true;syncPageDisplay();edReload();
      document.body.classList.add('tabs-ready');
      _firstPoll=false;return;
    }
    applyTabVisibility(d.enabled_tabs||[],_hasAsl,_hasDvs,_hasStfu,_hasEcho,_hasM17);
    // X2 — one-shot startup warnings from the backend (e.g. legacy XLX rows
    // dropped during conf parse). Gated on _firstPoll so it surfaces exactly
    // once per page load, never repeats on subsequent poll cycles.
    if(Array.isArray(d.conf_warnings)){
      d.conf_warnings.forEach(w=>toast(w,'info'));
    }
    // SysMon return: if the user navigated to SysMon (same tab) and pressed
    // Back, restore the tab they left from and skip all forced-page overrides
    // (ASL default, DMR net-select).  Breadcrumb is one-shot — cleared here.
    let _sysmonReturning=false;
    try{
      const _srRaw=sessionStorage.getItem('sysmonReturn');
      if(_srRaw){
        sessionStorage.removeItem('sysmonReturn');
        const _sr=JSON.parse(_srRaw);
        if(_sr.page&&PAGES.includes(_sr.page)){curPage=_sr.page;_sysmonReturning=true;}
      }
    }catch(_){}
    if(!_sysmonReturning){
      // On a full ASL+DVS system always open the ASL tab by default — the
      // backend page is 'DMR' from _dvs_startup_init which runs before any
      // user interaction. Only use d.page if ASL is absent (DVS-only node).
      const preferredPage=_hasAsl?'ASL':(PAGES.includes(d.page)?d.page:(PAGES[0]||'DMR'));
      curPage=PAGES.includes(preferredPage)?preferredPage:(PAGES[0]||'ASL');
      // DVS-only nodes (no ASL) land on DMR at first load — show net-select.
      if(curPage==='DMR') _dmrNetSelectMode=true;  // D3 writer 1/4 — see declaration comment
    }
    syncPageDisplay();
    document.body.classList.add('tabs-ready');
    _firstPoll=false;
  }else if(Array.isArray(d.enabled_tabs)){
    _hasStfu=!!d.has_stfu;_hasEcho=!!d.has_echo;_hasM17=!!d.has_m17;
    const pc=applyTabVisibility(d.enabled_tabs,_hasAsl,_hasDvs,_hasStfu,_hasEcho,_hasM17);
    if(pc){
      if(curPage&&!PAGES.includes(curPage)){curPage=PAGES.length?PAGES[0]:null;if(!inEdit)inEdit=!curPage}
      syncPageDisplay();_lastHash='';
    }
  }
}
function applyServerState(d){
  byId('hdr-node').textContent=d.asl_node;
  const csEl=byId('hdr-callsign');
  const csSep=byId('hdr-callsign-sep');
  if(d.callsign){csEl.textContent=d.callsign;csEl.style.display='inline';csSep.style.display='inline';}
  else{csEl.style.display='none';csSep.style.display='none';}
  if(d.uptime_seconds!=null){
    _uptimeBase=d.uptime_seconds;
    _uptimeAt=Date.now();
    byId('hdr-uptime').textContent=fmtUptime(_uptimeBase);
  }
  // Stage 2 — login state badges removed (v7.42)
  const sel=byId('dmr-srv-select');
  if(sel&&Array.isArray(d.dmr_servers)&&d.dmr_servers.length){
    const names=d.dmr_servers.map(s=>s.name).join('\x00');
    if(sel.dataset.names!==names){
      sel.dataset.names=names;
      sel.innerHTML=d.dmr_servers.map(s=>`<option value="${esc(s.name)}">${esc(s.name)}</option>`).join('');
    }
    if(d.active_dmr_server&&sel.value!==d.active_dmr_server)sel.value=d.active_dmr_server;
    sel.disabled=busy;
    // Cache for immediate net-select render in clickTab (no poll round-trip needed)
    _lastDmrServers=d.dmr_servers;
    _lastActiveDmrServer=d.active_dmr_server||'';
  }
  if(d.page==='ECHO'){
    setIndicator(d.echo_fav||null,'ECHO',d.echo_fav?_lastKeyed:false);
  }else if(d.current_fav&&d.page&&d.page!=='ASL'){
    curTg={mode:d.page,tg:d.current_fav};
  }else if(!d.current_fav){
    curTg=null;
  }
  if(!inEdit&&!busy&&d.page!==curPage&&PAGES.includes(d.page)){curPage=d.page;syncPageDisplay()}
  if(d.page==='ECHO'){
    // already handled above
  }else if(d.page==='XLX'&&d.current_fav){
    // current_fav is a D-Star-family tune string e.g. "XLX334AL". v7.762:
    // pass the raw tg as the indicator value (matches DSTAR and every other
    // mode's "raw tg always" convention — see setIndicator() doc comment)
    // with the friendly base+module label as the tooltip/name, instead of
    // showing the friendly label as the primary value (audit finding —
    // XLX was the only mode not following the documented convention).
    const tg=d.current_fav;
    const base=tg.length>=2?tg.slice(0,-2):tg;
    const modLetter=tg.length>=2?tg.slice(-2,-1):'?';
    setIndicator(tg,'XLX',_lastKeyed,base+' Mod-'+modLetter);
  }else{
    setIndicator(d.current_fav,d.page,_lastKeyed);
  }
}
function applyGridState(d,changed){
  if(!inEdit&&PAGES.length&&changed){
    _lastAslNodes=d.asl||[];_lastEchoNodes=d.echo||[];_lastEchoFav=d.echo_fav||null;
    // TG/DSTAR/XLX data is no longer in the status response.
    // _lastTgs / _lastDstarRefs / _lastXlxRefs are populated by loadTgData()
    // at boot and after save-all. Re-render grids with whatever is cached.
    // Sync curTg and per-mode map from server state on every status change.
    // Ensures the indicator survives a page reload or service restart.
    if(d.current_fav&&d.page){
      curTg={mode:d.page,tg:d.current_fav};
      _curTgPerMode[d.page]=curTg;
    }else if(d.page&&!d.current_fav){
      // Server says nothing tuned on this page — clear local memory for it.
      _curTgPerMode[d.page]=null;
      if(curTg&&curTg.mode===d.page)curTg=null;
    }
    // ASL grid: render on every changed status so it draws immediately at boot
    // and stays current as linked_node changes. _lastLinkedNode reflects the
    // most recent pollKeyed() result; null means nothing linked.
    // A5 (audit) — asl-grid has 3 independent repaint triggers, and is the
    // one grid driven by link state rather than curTg: this call (status
    // poll), pollKeyed() below (keyed/link-state poll, gated to ASL), and
    // the optimistic immediate render inside aslConnect/doConnectByNumber
    // (uses the just-clicked node before the server confirms). Not a bug —
    // this is how foreign/perm-linked nodes get reflected on the grid.
    renderASLGrid(_lastAslNodes,_lastLinkedNode);
    // Echo grid: same treatment as ASL — repaint on every changed status so
    // it draws at boot/tab-switch instead of only after a connect/disconnect
    // action (which was the only place this used to be called from).
    renderEchoGrid(_lastEchoNodes,_lastEchoFav);
    // T2 guard: only render TG grids once loadTgData() has successfully fetched
    // real data.  Before that, _lastTgs is {} and every renderTGGrid call would
    // render "No X entries", permanently blanking the grids if loadTgData()
    // then fails (T1).  applyGridState is still called first-thing at boot, so
    // skipping the TG portion here costs nothing — loadTgData() renders them
    // moments later via its own direct renderTGGrid() calls.
    if(_dmrNetSelectMode){
      renderDmrNetSelect(d.dmr_servers||[],d.active_dmr_server||'');
    }else if(_tgDataLoaded){
      renderTGGrid('dmr-grid',_lastTgs.DMR||[],'DMR');
    }
    if(_tgDataLoaded){
      renderTGGrid('stfu-grid',_lastTgs.STFU||[],'STFU');
      renderTGGrid('ysf-grid',_lastTgs.YSF||[],'YSF');
      renderTGGrid('fcs-grid',_lastTgs.FCS||[],'FCS');
      renderTGGrid('p25-grid',_lastTgs.P25||[],'P25');
      renderTGGrid('nxdn-grid',_lastTgs.NXDN||[],'NXDN');
      renderDstarGrid(_lastDstarRefs,curTg&&curTg.mode==='DSTAR'?curTg.tg:null);
      renderXlxGrid(_lastXlxRefs,curTg&&curTg.mode==='XLX'?curTg.tg:null);
      renderM17Grid(_lastM17Refs,curTg&&curTg.mode==='M17'?curTg.tg:null);
    }
    // Keep _refreshLhBtns current after every status change.
    _refreshLhBtns();
    initModuleSelects();
  }
}
async function refresh(){
  if(busy)return;
  try{
    const ctrl=new AbortController();
    const tid=setTimeout(()=>ctrl.abort(),5000);
    const hdrs=_lastEtag?{'If-None-Match':_lastEtag}:{};
    const r=await fetch('/api/status',{headers:hdrs,signal:ctrl.signal});
    clearTimeout(tid);
    if(r.status===304){
      _failCount=0;document.body.classList.remove('offline');
      return;
    }
    const etag=r.headers.get('ETag');
    if(etag)_lastEtag=etag;
    const d=await r.json();
    _failCount=0;document.body.classList.remove('offline');
    const aslFP=(d.asl||[]).map(n=>n.name+n.node).join('|');
    const echoFP=(d.echo||[]).map(n=>n.name+n.node).join('|');
    const hash=JSON.stringify([d.page,d.current_fav,d.echo_fav,
                               d.has_asl,d.has_dvs,d.has_stfu,d.has_echo,
                               aslFP,echoFP,(d.enabled_tabs||[]).join()]);
    const changed=hash!==_lastHash;_lastHash=hash;
    applyTabState(d);
    applyServerState(d);
    applyGridState(d,changed);
  }catch(e){
    console.error('refresh() error:',e);
    if(++_failCount>=4){
      document.body.classList.add('offline');
      // If first poll never succeeded tabs stay hidden behind the
      // body:not(.tabs-ready) gate forever.  Force it so the offline
      // bar is visible and tabs appear when the service comes back.
      if(_firstPoll) document.body.classList.add('tabs-ready');
    }
  }
}
let edRows=[],ndRows=[],ecRows=[],xlxEdRows=[],m17EdRows=[],modeNetUrls={},rowNetUrlDefaults={};
async function cfgLoad(){
  try{
    const d=await(await fetch('/api/config')).json();
    byId('cfg-callsign').value=d.callsign||'';
    byId('cfg-asl-node').value=d.asl_node||'';
    const bn=Array.isArray(d.bridge_nodes)?d.bridge_nodes:['','','',''];
    for(let i=0;i<4;i++){
      const el=byId('cfg-bridge-node-'+i);
      if(el)el.value=bn[i]||'';
    }
    byId('cfg-port').value=d.port||'';
    const enabled=Array.isArray(d.enabled_tabs)?d.enabled_tabs:[];
    STATIC_PAGES.forEach(m=>{
      const el=byId('chk-'+m);if(el)el.checked=enabled.includes(m);
    });
    if(d.mode_net_urls&&typeof d.mode_net_urls==='object'){
      modeNetUrls=Object.assign({},d.mode_net_urls);
    }
    if(d.row_net_url_defaults&&typeof d.row_net_url_defaults==='object'){
      rowNetUrlDefaults=Object.assign({},d.row_net_url_defaults);
    }
    _refreshLhBtns();
  }catch(e){console.error('cfgLoad() error:',e);}
}
async function cfgSave(){
  const callsign=byId('cfg-callsign').value.trim().toUpperCase();
  const asl_node=byId('cfg-asl-node').value.trim();
  const bridge_nodes=[0,1,2,3].map(i=>{
    const el=byId('cfg-bridge-node-'+i);
    return el?el.value.trim():'';
  });
  const bridge_node=bridge_nodes[0];
  const port=byId('cfg-port').value.trim();
  const enabled_tabs=STATIC_PAGES
    .filter(m=>{const el=byId('chk-'+m);return el&&el.checked});
  const d=await api({action:'save-config',asl_node,bridge_node,bridge_nodes,port,callsign,enabled_tabs,mode_net_urls:modeNetUrls});
  if(!d.ok){toast('Config: '+d.message,'err');return false}return true;
}
async function loadTgData(){
  // Fetches TG/DSTAR/XLX data from dedicated endpoints and re-renders all
  // mode grids. Called at boot and after save-all. Keeps /api/status lean.
  // T1: any failure shows a toast and schedules one retry so a transient
  // server-startup hiccup (common after service restart) self-heals rather
  // than silently leaving every grid blank until the user reloads the page.
  try{
    const [tgRes,xlxRes,m17Res,cfgRes]=await Promise.all([
      fetch('/api/talkgroups'),fetch('/api/xlx-reflectors'),fetch('/api/m17-reflectors'),fetch('/api/config')]);
    const rawTg=await tgRes.json();
    const xlxRaw=await xlxRes.json();
    const m17Raw=await m17Res.json();
    // Populate rowNetUrlDefaults so LH fallbacks work before the edit tab is opened
    try{
      const cfgD=await cfgRes.json();
      if(cfgD.row_net_url_defaults&&typeof cfgD.row_net_url_defaults==='object')
        rowNetUrlDefaults=Object.assign({},cfgD.row_net_url_defaults);
      if(cfgD.mode_net_urls&&typeof cfgD.mode_net_urls==='object')
        modeNetUrls=Object.assign(modeNetUrls,cfgD.mode_net_urls);
    }catch(_){}
    _lastTgs={
      DMR: rawTg.filter(r=>r.mode==='DMR') .map(r=>({name:r.name,tg:r.tg})),
      STFU:rawTg.filter(r=>r.mode==='STFU').map(r=>({name:r.name,tg:r.tg})),
      YSF: rawTg.filter(r=>r.mode==='YSF') .map(r=>({name:r.name,tg:r.tg,url:r.url||''})),
      FCS: rawTg.filter(r=>r.mode==='FCS') .map(r=>({name:r.name,tg:r.tg,url:r.url||''})),
      P25: rawTg.filter(r=>r.mode==='P25') .map(r=>({name:r.name,tg:r.tg,url:r.url||''})),
      NXDN:rawTg.filter(r=>r.mode==='NXDN').map(r=>({name:r.name,tg:r.tg,url:r.url||''})),
    };
    _lastDstarRefs=rawTg.filter(r=>r.mode==='DSTAR').map(r=>({name:r.name,tg:r.tg,url:r.url||''}));
    _lastXlxRefs=Array.isArray(xlxRaw)?xlxRaw.map(r=>({name:r.name,tg:r.tg,url:r.url||''})):[];
    _lastM17Refs=Array.isArray(m17Raw)?m17Raw.map(r=>({name:r.name,base:r.base,module:r.module,ip:r.ip,url:r.url||''})):[];
    _tgDataLoaded=true;  // mark before renders so applyGridState uses real data
    if(_dmrNetSelectMode){
      // dmr_servers not available here — applyGridState will render net-select
      // on the next refresh cycle; skip TG grid render for DMR only.
    }else{
      renderTGGrid('dmr-grid', _lastTgs.DMR, 'DMR');
    }
    renderTGGrid('stfu-grid',_lastTgs.STFU,'STFU');
    renderTGGrid('ysf-grid', _lastTgs.YSF, 'YSF');
    renderTGGrid('fcs-grid', _lastTgs.FCS, 'FCS');
    renderTGGrid('p25-grid', _lastTgs.P25, 'P25');
    renderTGGrid('nxdn-grid',_lastTgs.NXDN,'NXDN');
    renderDstarGrid(_lastDstarRefs,curTg&&curTg.mode==='DSTAR'?curTg.tg:null);
    renderXlxGrid(_lastXlxRefs,curTg&&curTg.mode==='XLX'?curTg.tg:null);
    renderM17Grid(_lastM17Refs,curTg&&curTg.mode==='M17'?curTg.tg:null);
    renderASLGrid(_lastAslNodes,_lastLinkedNode);  // ensure ASL grid draws at boot
    initModuleSelects();
    _refreshLhBtns();
  }catch(e){
    console.error('loadTgData() error:',e);
    // Only toast+retry on the first failure — if retry also fails, stay silent
    // to avoid a persistent error banner while the Pi finishes booting.
    if(!_tgDataLoaded){
      toast('Talkgroups unavailable — retrying…','err');
      setTimeout(loadTgData,4000);
    }
  }
}
async function edReload(){
  try{
    const[tgRes,ndRes,ecRes,srvRes,srvTgRes,xlxRes,m17Res]=await Promise.all([
      fetch('/api/talkgroups'),fetch('/api/asl-nodes'),fetch('/api/echo-nodes'),
      fetch('/api/dmr-servers'),fetch('/api/dmr-server-tgs'),fetch('/api/xlx-reflectors'),
      fetch('/api/m17-reflectors')]);
    const rawTg=await tgRes.json();ndRows=await ndRes.json();ecRows=await ecRes.json();
    const srvList=await srvRes.json();const rawSrvTgs=await srvTgRes.json();
    xlxEdRows=await xlxRes.json();
    m17EdRows=await m17Res.json();
    while(ndRows.length<10)ndRows.push({name:TG_BLANK_NAME,node:TG_BLANK_ADDR});
    while(ecRows.length<10)ecRows.push({name:TG_BLANK_NAME,node:TG_BLANK_ADDR});
    while(xlxEdRows.length<10)xlxEdRows.push({name:TG_BLANK_NAME,tg:TG_BLANK_ADDR,url:''});
    while(m17EdRows.length<10)m17EdRows.push({name:TG_BLANK_NAME,base:TG_BLANK_NAME,module:'@ALL',ip:TG_BLANK_ADDR,url:''});
    const DM=['DMR','STFU','YSF','FCS','P25','NXDN','DSTAR'];edRows=[];
    DM.forEach(m=>{
      const g=rawTg.filter(r=>r.mode===m);
      edRows.push(...g);
      for(let i=g.length;i<10;i++)edRows.push({mode:m,name:TG_BLANK_NAME,tg:TG_BLANK_ADDR,url:''});
    });
    dmrSrvRows={};
    if(Array.isArray(srvList))srvList.forEach(s=>{
      const key=s.name.toUpperCase().replace(/ /g,'_').replace(/\+/g,'PLUS');
      const rows=rawSrvTgs[key]||[];
      while(rows.length<10)rows.push({name:TG_BLANK_NAME,tg:TG_BLANK_ADDR});
      dmrSrvRows[key]={srvName:s.name,password:s.password,address:s.address,
                       netUrl:s.net_url||'',rows:rows.slice(0,10)};
    });
    edRender();await cfgLoad();toast('Loaded','ok');
  }catch(_){toast('Failed to load','err')}
}
function edSyncFromDOM(){
  // Sync generic TG rows — skip DSTAR rows (they use dstar-ed-row class and
  // reconstruct tg from base+module on save)
  document.querySelectorAll('.ed-row:not(.nd-row):not(.ec-row):not(.dstar-ed-row):not(.xlx-ed-row)').forEach(row=>{
    const i=parseInt(row.dataset.idx);
    if(!isNaN(i)&&i<edRows.length){
      const n=row.querySelector('.ed-inp-name');const t=row.querySelector('.ed-inp-tg');
      if(n)edRows[i].name=n.value;if(t)edRows[i].tg=t.value;
    }
  });
  // Sync DSTAR rows: reassemble tg = base + module + L
  document.querySelectorAll('.dstar-ed-row').forEach(row=>{
    const i=parseInt(row.dataset.idx);
    if(!isNaN(i)&&i<edRows.length){
      const n=row.querySelector('.dstar-inp-name');
      const b=row.querySelector('.dstar-inp-base');
      const m=row.querySelector('.dstar-inp-mod');
      if(n)edRows[i].name=n.value;
      if(b&&m){
        const baseVal=b.value.trim().toUpperCase();
        edRows[i].tg=baseVal?baseVal+m.value.trim().toUpperCase()+'L':TG_BLANK_ADDR;
        if(!baseVal)edRows[i].name=TG_BLANK_NAME;
      }
      const u=row.querySelector('.url-inp');
      if(u)edRows[i].url=u.value.trim();
    }
  });
}
function syncEdRowsFromDOM(rowSelector,rowsArray,syncFn){
  // Stage 4 (v8.0 M17 normalization): shared boilerplate for every
  // "*SyncFromDOM" function — find each edit-row element, resolve its
  // index, bounds-check against the backing array, then hand off to a
  // per-tab callback that knows its own field names. xlxSyncFromDOM()
  // below is refactored onto this with its callback body left completely
  // untouched, so XLX's edit-save behavior is unchanged. m17SyncFromDOM()
  // (Stage 5) is the second caller.
  document.querySelectorAll(rowSelector).forEach(row=>{
    const i=parseInt(row.dataset.idx);
    if(!isNaN(i)&&i<rowsArray.length)syncFn(row,rowsArray[i],i);
  });
}
function xlxSyncFromDOM(){
  syncEdRowsFromDOM('.xlx-ed-row',xlxEdRows,(row,entry)=>{
    const n=row.querySelector('.xlx-inp-name');
    const b=row.querySelector('.xlx-inp-base');
    const m=row.querySelector('.xlx-inp-mod');
    if(n)entry.name=n.value;
    if(b&&m){
      const baseVal=b.value.trim().toUpperCase();
      entry.tg=baseVal?baseVal+m.value.trim().toUpperCase()+'L':TG_BLANK_ADDR;
      if(!baseVal)entry.name=TG_BLANK_NAME;
    }
    const u=row.querySelector('.url-inp');
    if(u)entry.url=u.value.trim();
  });
}
function m17SyncFromDOM(){
  // Unlike xlxSyncFromDOM() above, M17's base/module/ip stay as separate
  // fields all the way through — there's no single "tg" string to collapse
  // them into, since ip has no trailing-character convention to decode a
  // module out of the way XLX's tg does. entry.url is kept in sync
  // separately via m17UrlChanged() (onchange, not read here) for
  // consistency with xlxUrlChanged()'s existing pattern.
  syncEdRowsFromDOM('.m17-ed-row',m17EdRows,(row,entry)=>{
    const n=row.querySelector('.m17-inp-name');
    const b=row.querySelector('.m17-inp-base');
    const m=row.querySelector('.m17-inp-mod');
    const ip=row.querySelector('.m17-inp-ip');
    const baseVal=b?b.value.trim().toUpperCase():'';
    const ipVal=ip?ip.value.trim():'';
    entry.base=baseVal||TG_BLANK_NAME;
    entry.ip=ipVal||TG_BLANK_ADDR;
    entry.module=m?m.value.trim().toUpperCase():'@ALL';
    entry.name=(n&&n.value.trim())||(baseVal||TG_BLANK_NAME);
    if(!baseVal||!ipVal){entry.name=TG_BLANK_NAME;entry.base=TG_BLANK_NAME;entry.ip=TG_BLANK_ADDR;}
  });
}

function ndSyncFromDOM(){
  document.querySelectorAll('.nd-row').forEach(row=>{
    const i=parseInt(row.dataset.idx);
    if(!isNaN(i)&&i<ndRows.length){
      const n=row.querySelector('.nd-inp-name');const nd=row.querySelector('.nd-inp-node');
      if(n)ndRows[i].name=n.value;if(nd)ndRows[i].node=nd.value;
    }
  });
}
function ecSyncFromDOM(){
  document.querySelectorAll('.ec-row').forEach(row=>{
    const i=parseInt(row.dataset.idx);
    if(!isNaN(i)&&i<ecRows.length){
      const n=row.querySelector('.ec-inp-name');const nd=row.querySelector('.ec-inp-node');
      if(n)ecRows[i].name=n.value;if(nd)ecRows[i].node=nd.value;
    }
  });
}
function ecFieldChanged(i,f,v){if(ecRows[i])ecRows[i][f]=v}
function modeNetUrlChanged(m,v){modeNetUrls[m]=v;}
function xlxUrlChanged(i,v){if(xlxEdRows[i])xlxEdRows[i].url=v;}
function m17UrlChanged(i,v){if(m17EdRows[i])m17EdRows[i].url=v;}
function dmrSrvTgChanged(key,i,f,v){
  if(dmrSrvRows[key]&&dmrSrvRows[key].rows[i])dmrSrvRows[key].rows[i][f]=v;
}
function dmrSrvMetaChanged(key,f,v){
  if(dmrSrvRows[key])dmrSrvRows[key][f]=v;
}
function dmrSrvAdd(){
  const name='New Network';
  const key='NEW_'+Date.now();
  const rows=[];
  for(let i=0;i<10;i++)rows.push({name:TG_BLANK_NAME,tg:TG_BLANK_ADDR});
  dmrSrvRows[key]={srvName:name,password:'passw0rd',address:'host:62031',netUrl:'',rows};
  edRender();
}
function dmrSrvRemove(key){
  if(Object.keys(dmrSrvRows).length<=1){toast('At least one DMR network required','err');return;}
  delete dmrSrvRows[key];
  edRender();
}
function edFieldChanged(i,f,v){if(edRows[i])edRows[i][f]=v}
function ndFieldChanged(i,f,v){if(ndRows[i])ndRows[i][f]=v}
/* edUrlRow(mode) — Network Dashboard URL row bound to modeNetUrls (v7.744;
   was copy-pasted at 3 sites).  The per-DMR-server variant (srv.netUrl via
   dmrSrvMetaChanged) is a different data path and stays hand-rolled. */
function edUrlRow(mode){
  return `<div class="ed-url-row"><span class="ed-url-label">Network Dashboard URL</span>`+
         `<input class="ed-inp url-inp" value="${esc(modeNetUrls[mode]||'')}" placeholder="https://host/last_heard (optional)" oninput="modeNetUrlChanged('${mode}',this.value)"></div>`;
}
function edRender(){
  const DM=['DMR','STFU','YSF','P25','NXDN','DSTAR'];
  // Default all sections to collapsed on first entry to the edit tab.
  // _edCollapsed persists for the session, so sections the user has explicitly
  // opened stay open on subsequent edReload() calls.
  const allSids=['eds-tabs','eds-ASL','eds-ECHO','eds-DSTAR','eds-XLX','eds-M17',
                 'eds-DMR-NET','eds-FCS',
                 ...DM.map(m=>`eds-${m}`),
                 ...Object.keys(dmrSrvRows||{}).map(k=>`eds-TGS-${k}`)];
  allSids.forEach(id=>{ if(_edCollapsed[id]===undefined) _edCollapsed[id]=true; });
  let h='';
  if(PAGES.includes('ASL')){
    h+=`<div class="ed-sec-hdr"><span>ASL</span><button onclick="toggleEdSection('eds-ASL')">Hide</button></div>`;
    h+=`<div id="eds-ASL">`;
    h+=edUrlRow('ASL');
    h+=`<div class="ed-list-grid">`;
    h+=ndRows.map((r,i)=>`<div class="nd-row ed-row" data-idx="${i}">
    <input class="ed-inp nd-inp-name" value="${esc(r.name)}" placeholder="Name" oninput="ndFieldChanged(${i},'name',this.value)">
    <input class="ed-inp nd-inp-node" value="${esc(r.node)}" placeholder="Node #" inputmode="numeric" oninput="ndFieldChanged(${i},'node',this.value)">
    </div>`).join('');
    h+='</div></div>';
  }
  if(PAGES.includes('ECHO')){
    h+=`<div class="ed-sec-hdr"><span>Echo</span><button onclick="toggleEdSection('eds-ECHO')">Hide</button></div>`;
    h+=`<div id="eds-ECHO">`;
    h+=edUrlRow('ECHO');
    h+=`<div class="ed-list-grid">`;
    h+=ecRows.map((r,i)=>`<div class="ec-row ed-row" data-idx="${i}">
    <input class="ed-inp ec-inp-name" value="${esc(r.name)}" placeholder="Name" oninput="ecFieldChanged(${i},'name',this.value)">
    <input class="ed-inp ec-inp-node" value="${esc(r.node)}" placeholder="Node #" inputmode="numeric" oninput="ecFieldChanged(${i},'node',this.value)">
    </div>`).join('');
    h+='</div></div>';
  }
  const idx=edRows.map((r,i)=>({...r,_i:i}));
  const nonDmr=['STFU','YSF','P25','NXDN'];
  nonDmr.forEach(m=>{
    if(!PAGES.includes(m))return;
    const g=idx.filter(r=>r.mode===m);
    if(!g.length)return;
    const label=TAB_LABELS[m]||m;
    const sid=`eds-${m}`;
    h+=`<div class="ed-sec-hdr"><span>${label}</span><button onclick="toggleEdSection('${sid}')">Hide</button></div>`;
    h+=`<div id="${sid}">`;
    const isSectionUrl=m==='STFU';
    const isRowUrl=m==='YSF'||m==='P25'||m==='NXDN';
    if(isSectionUrl){
      h+=edUrlRow(m);
    }
    if(m==='STFU'){
      // Private-call usage note: trailing '#' on a DMR ID marks the entry as
      // a BrandMeister private call (e.g. node-to-node between own ESSIDs).
      h+=`<div class="ed-hint">Append # to a DMR ID for a private call &mdash; e.g. 312123401# &harr; 312123402# for node-to-node (IDs must differ by ESSID).</div>`;
    }
    h+='<div class="ed-list-grid">';
    h+=g.map(r=>{
      const rowUrl=isRowUrl?`<input class="ed-inp url-inp url-inp-row" value="${esc(r.url||'')}" placeholder="https://reflector-host/last_heard (optional)" oninput="edFieldChanged(${r._i},'url',this.value)">`:'' ;
      return `<div class="ed-row" data-idx="${r._i}">
      <input class="ed-inp ed-inp-name" value="${esc(r.name)}" placeholder="Name" oninput="edFieldChanged(${r._i},'name',this.value)">
      <input class="ed-inp ed-inp-tg" value="${esc(r.tg)}" placeholder="TG / address" oninput="edFieldChanged(${r._i},'tg',this.value)">
      ${rowUrl}</div>`;
    }).join('');
    h+='</div></div>';
    // FCS section — inserted after YSF, before P25
    if(m==='YSF'&&PAGES.includes('FCS')){
      const fg=idx.filter(r=>r.mode==='FCS');
      if(fg.length){
        h+=`<div class="ed-sec-hdr"><span>FCS Rooms</span><button onclick="toggleEdSection('eds-FCS')">Hide</button></div>`;
        h+=`<div id="eds-FCS"><div class="ed-list-grid">`;
        h+=fg.map(r=>`<div class="ed-row" data-idx="${r._i}">
          <input class="ed-inp ed-inp-name" value="${esc(r.name)}" placeholder="Name" oninput="edFieldChanged(${r._i},'name',this.value)">
          <input class="ed-inp ed-inp-tg" value="${esc(r.tg)}" placeholder="Room # (e.g. FCS00335 or 335)" oninput="edFieldChanged(${r._i},'tg',this.value)">
          <input class="ed-inp url-inp url-inp-row" value="${esc(r.url||'')}" placeholder="https://fcsXXX.host/last_heard (optional)" oninput="edFieldChanged(${r._i},'url',this.value)">
          </div>`).join('');
        h+='</div></div>';
      }
    }
  });
  // ── DSTAR: 3-field rows (Name | Base | Default Module) ──────────────────────
  if(PAGES.includes('DSTAR')){
    const dg=idx.filter(r=>r.mode==='DSTAR');
    h+=`<div class="ed-sec-hdr"><span>D-STAR Reflectors</span><button onclick="toggleEdSection('eds-DSTAR')">Hide</button></div>`;
    h+=`<div id="eds-DSTAR">`;
    h+='<div style="padding:.25rem .6rem .1rem;display:grid;grid-template-columns:1fr 1fr 5rem;gap:.4rem">';
    h+='<span style="font-family:var(--mono);font-size:.66rem;color:#5a7898">Name</span>';
    h+='<span style="font-family:var(--mono);font-size:.66rem;color:#5a7898">Reflector Base</span>';
    h+='<span style="font-family:var(--mono);font-size:.66rem;color:#5a7898">Def. Mod</span></div>';
    h+='<div style="padding:.25rem .6rem .5rem;display:flex;flex-direction:column;gap:.35rem">';
    h+=dg.map(r=>{
      const isBlank=r.name===TG_BLANK_NAME||r.tg===TG_BLANK_ADDR;
      const base=(!isBlank&&r.tg&&r.tg.length>=2)?r.tg.slice(0,-2):'';
      const mod=(!isBlank&&r.tg&&r.tg.length>=2)?r.tg.slice(-2,-1):'A';
      return `<div class="dstar-ed-row ed-row" data-idx="${r._i}" style="display:flex;flex-direction:column;gap:.2rem">
        <div style="display:grid;grid-template-columns:1fr 1fr 5rem;gap:.4rem">
        <input class="ed-inp dstar-inp-name" value="${isBlank?'':esc(r.name)}" placeholder="Name">
        <input class="ed-inp dstar-inp-base" value="${esc(base)}" placeholder="REF001" style="text-transform:uppercase">
        <select class="ed-inp dstar-inp-mod" style="padding:.3rem .3rem">${buildModuleOptions(mod||'A')}</select>
        </div>
        <input class="ed-inp url-inp url-inp-row" value="${esc(r.url||'')}" placeholder="https://reflector-host/last_heard (optional)" oninput="edFieldChanged(${r._i},'url',this.value)">
      </div>`;
    }).join('');
    h+='</div></div>';
  }
  // ── XLX: 3-field rows (Name | Reflector Base | Default Module) — mirrors DSTAR
  if(PAGES.includes('XLX')){
    h+=`<div class="ed-sec-hdr"><span>XLX Reflectors</span><button onclick="toggleEdSection('eds-XLX')">Hide</button></div>`;
    h+=`<div id="eds-XLX">`;
    h+='<div style="padding:.25rem .6rem .1rem;display:grid;grid-template-columns:1fr 1fr 5rem;gap:.4rem">';
    h+='<span style="font-family:var(--mono);font-size:.66rem;color:#5a7898">Name</span>';
    h+='<span style="font-family:var(--mono);font-size:.66rem;color:#5a7898">Reflector Base</span>';
    h+='<span style="font-family:var(--mono);font-size:.66rem;color:#5a7898">Def. Mod</span></div>';
    h+='<div style="padding:.25rem .6rem .5rem;display:flex;flex-direction:column;gap:.35rem">';
    h+=xlxEdRows.map((r,i)=>{
      const isBlank=r.name===TG_BLANK_NAME||r.tg===TG_BLANK_ADDR;
      const base=(!isBlank&&r.tg&&r.tg.length>=2)?r.tg.slice(0,-2):'';
      const mod=(!isBlank&&r.tg&&r.tg.length>=2)?r.tg.slice(-2,-1):'A';
      return `<div class="xlx-ed-row ed-row" data-idx="${i}" style="display:flex;flex-direction:column;gap:.2rem">
        <div style="display:grid;grid-template-columns:1fr 1fr 5rem;gap:.4rem">
        <input class="ed-inp xlx-inp-name" value="${isBlank?'':esc(r.name)}" placeholder="Name">
        <input class="ed-inp xlx-inp-base" value="${esc(base)}" placeholder="XLX334" style="text-transform:uppercase">
        <select class="ed-inp xlx-inp-mod" style="padding:.3rem .3rem">${buildModuleOptions(mod||'A')}</select>
        </div>
        <input class="ed-inp url-inp url-inp-row" value="${esc(r.url||'')}" placeholder="https://xlxXXX.host/last_heard (optional)" oninput="xlxUrlChanged(${i},this.value)">
      </div>`;
    }).join('');
    h+='</div></div>';
  }
  // ── M17: 4-field rows (Name | Reflector Base | Module | IP) — separate
  // base/module/ip fields (not collapsed into one tg string like
  // XLX/DSTAR) because ip has no trailing-character convention to decode a
  // module out of; module also needs to support the @ALL wildcard.
  if(PAGES.includes('M17')){
    h+=`<div class="ed-sec-hdr"><span>M17</span><button onclick="toggleEdSection('eds-M17')">Hide</button></div>`;
    h+=`<div id="eds-M17">`;
    h+='<div style="padding:.25rem .6rem .1rem;display:grid;grid-template-columns:1fr 1fr 5rem 1fr;gap:.4rem">';
    h+='<span style="font-family:var(--mono);font-size:.66rem;color:#5a7898">Name</span>';
    h+='<span style="font-family:var(--mono);font-size:.66rem;color:#5a7898">Reflector Base</span>';
    h+='<span style="font-family:var(--mono);font-size:.66rem;color:#5a7898">Module</span>';
    h+='<span style="font-family:var(--mono);font-size:.66rem;color:#5a7898">IP / Host</span></div>';
    h+='<div style="padding:.25rem .6rem .5rem;display:flex;flex-direction:column;gap:.35rem">';
    h+=m17EdRows.map((r,i)=>{
      const isBlank=r.name===TG_BLANK_NAME||r.ip===TG_BLANK_ADDR;
      const base=isBlank?'':(r.base||'');
      const mod=isBlank?'@ALL':(r.module||'@ALL');
      return `<div class="m17-ed-row ed-row" data-idx="${i}" style="display:flex;flex-direction:column;gap:.2rem">
        <div style="display:grid;grid-template-columns:1fr 1fr 5rem 1fr;gap:.4rem">
        <input class="ed-inp m17-inp-name" value="${isBlank?'':esc(r.name)}" placeholder="Name">
        <input class="ed-inp m17-inp-base" value="${esc(base)}" placeholder="M17-USA" style="text-transform:uppercase">
        <select class="ed-inp m17-inp-mod" style="padding:.3rem .3rem">${buildModuleOptions(mod,true)}</select>
        <input class="ed-inp m17-inp-ip" value="${isBlank?'':esc(r.ip)}" placeholder="203.0.113.5">
        </div>
        <input class="ed-inp url-inp url-inp-row" value="${esc(r.url||'')}" placeholder="https://reflector-host/last_heard (optional)" oninput="m17UrlChanged(${i},this.value)">
      </div>`;
    }).join('');
    h+='</div></div>';
  }
  if(PAGES.includes('DMR')){
    h+=`<div class="ed-sec-hdr"><span>DMR Networks</span><button onclick="toggleEdSection('eds-DMR-NET')">Hide</button></div>`;
    h+=`<div id="eds-DMR-NET">`;
    h+='<div style="padding:.35rem .6rem .1rem">';
    h+='<div class="srv-meta-row" style="font-family:var(--mono);font-size:.66rem;color:#5a7898;border-bottom:2px solid var(--border2)">';
    h+='<span>Name</span><span>Password</span><span>Host:Port</span><span></span></div>';
    Object.entries(dmrSrvRows).forEach(([key,srv])=>{
      h+=`<div class="srv-meta-row">`;
      h+=`<input class="ed-inp" value="${esc(srv.srvName)}" placeholder="Name" oninput="dmrSrvMetaChanged('${esc(key)}','srvName',this.value)">`;
      h+=`<input class="ed-inp" value="${esc(srv.password)}" placeholder="Password" oninput="dmrSrvMetaChanged('${esc(key)}','password',this.value)">`;
      h+=`<input class="ed-inp" value="${esc(srv.address)}" placeholder="host:port" oninput="dmrSrvMetaChanged('${esc(key)}','address',this.value)">`;
      h+=`<button class="btn-xs btn-red" onclick="dmrSrvRemove('${esc(key)}')" title="Remove">×</button>`;
      h+='</div>';
      h+=`<div class="ed-url-row"><span class="ed-url-label">Network Dashboard URL</span>`;
      h+=`<input class="ed-inp url-inp" value="${esc(srv.netUrl||'')}" placeholder="https://host/last_heard (optional)" oninput="dmrSrvMetaChanged('${esc(key)}','netUrl',this.value)"></div>`;
    });
    h+='</div>';
    h+=`<div style="padding:.35rem .6rem"><button class="btn btn-muted" onclick="dmrSrvAdd()" style="font-size:.77rem;padding:.3rem .8rem">+ Add Network</button></div>`;
    h+='</div>';
    if(Object.keys(dmrSrvRows).length){
      Object.entries(dmrSrvRows).forEach(([key,srv])=>{
        const tgsid=`eds-TGS-${key}`;
        h+=`<div class="ed-sec-hdr"><span>TGs · ${esc(srv.srvName)}</span><button onclick="toggleEdSection('${tgsid}')">Hide</button></div>`;
        h+=`<div id="${tgsid}"><div class="ed-list-grid" style="margin-bottom:.5rem">`;
        h+=srv.rows.map((r,i)=>`<div class="ed-row" data-srvkey="${esc(key)}" data-idx="${i}">
          <input class="ed-inp" value="${esc(r.name)}" placeholder="Name" oninput="dmrSrvTgChanged('${esc(key)}',${i},'name',this.value)">
          <input class="ed-inp" value="${esc(r.tg)}" placeholder="TG" oninput="dmrSrvTgChanged('${esc(key)}',${i},'tg',this.value)">
          </div>`).join('');
        h+='</div></div>';
      });
    }
  }
  byId('ed-list').innerHTML=h;
  applyEdCollapsed();   // restore any sections the user previously collapsed
  const parts=[];
  if(PAGES.includes('ASL'))parts.push(`${ndRows.length} ASL nodes`);
  if(PAGES.includes('ECHO'))parts.push(`${ecRows.length} Echo nodes`);
  const dmCount=['DMR','STFU','YSF','FCS','P25','NXDN','DSTAR'].filter(m=>PAGES.includes(m)).length;
  if(dmCount)parts.push(`${edRows.length} talkgroups (${dmCount} mode${dmCount>1?'s':''})`);
  if(PAGES.includes('DMR'))parts.push(`${Object.keys(dmrSrvRows).length} DMR networks`);
  if(PAGES.includes('XLX'))parts.push(`${xlxEdRows.length} XLX reflectors`);
  byId('ed-count').textContent=parts.join(' · ');
}
async function edSave(){
  if(busy)return;busy=true;
  if(document.activeElement?.closest('.ed-row'))document.activeElement.blur();
  edSyncFromDOM();ndSyncFromDOM();ecSyncFromDOM();xlxSyncFromDOM();m17SyncFromDOM();showWorking('Saving…');
  try{
    if(!await cfgSave())return;
    const d=await api({action:'save-all',nodes:ndRows,talkgroups:edRows,echo_nodes:ecRows});
    toast(d.message,d.ok?'ok':'err');
    if(d.ok){
      if(Object.keys(dmrSrvRows).length){
        const server_tgs={};
        const server_list=[];
        Object.entries(dmrSrvRows).forEach(([key,srv])=>{
          const newKey=srv.srvName.toUpperCase().replace(/ /g,'_').replace(/\+/g,'PLUS');
          server_tgs[newKey]=srv.rows;
          server_list.push({name:srv.srvName,password:srv.password,address:srv.address,net_url:srv.netUrl||''});
        });
        const ds=await api({action:'save-dmr-server-tgs',server_tgs,server_list});
        if(!ds.ok)toast(ds.message,'err');
      }
      if(PAGES.includes('XLX')){
        const dx=await api({action:'save-xlx',rows:xlxEdRows});
        if(!dx.ok)toast(dx.message,'err');
      }
      if(PAGES.includes('M17')){
        const dm=await api({action:'save-m17',rows:m17EdRows});
        if(!dm.ok)toast(dm.message,'err');
      }
      edRender();
      loadTgData();
      _refreshLhBtns();
      const en=STATIC_PAGES.filter(m=>byId('chk-'+m)?.checked);
      applyTabVisibility(en,_hasAsl,_hasDvs,_hasStfu,_hasEcho,_hasM17);syncPageDisplay();setTimeout(refresh,400);
    }
  }finally{hideWorking();busy=false}
}
function schedulePoll(){
  clearTimeout(_pollTimer);
  _pollTimer=setTimeout(async()=>{try{await refresh()}finally{schedulePoll()}},busy?1000:3000);
}
let _keyedTimer=null;
async function pollKeyed(){
  try{
    const ctrl=new AbortController();
    const tid=setTimeout(()=>ctrl.abort(),2000);
    const r=await fetch('/api/keyed',{signal:ctrl.signal});
    clearTimeout(tid);
    const d=await r.json();
    const keyed      =!!d.keyed;
    const linkedNode =d.linked_node||null;
    const onPermLink  =!!d.on_perm_link;
    const permLinkNode=d.perm_link_node||null;
    const isKnownPerm =!!d.is_known_perm;
    const mode       =(curPage||'').toUpperCase();
    const isDigital  =!!(mode&&MODE_CAPS[mode]&&MODE_CAPS[mode].isDigital);

    const keyedChanged=keyed!==_lastKeyed;
    const linkChanged =linkedNode!==_lastLinkedNode;

    // ── Permanent-link banner ─────────────────────────────────────────────
    document.body.classList.toggle('perm-linked',onPermLink);
    _lastIsKnownPerm=isKnownPerm;
    const plNode=byId('perm-link-node');
    const plBar =byId('perm-link-bar');
    if(plNode)plNode.textContent=permLinkNode||'—';
    if(plBar){
      const label=isKnownPerm?'PERM LINK':'EXTERNAL LINK';
      plBar.firstChild.textContent=`⚠ ${label} ACTIVE · Node `;
    }

    // ── Node keyed path — applies to ALL tabs ─────────────────────────────
    if(keyedChanged){
      _lastKeyed=keyed;
      document.body.classList.toggle('radio-keyed',_lastKeyed);
      if(mode==='DSTAR'){
        renderDstarGrid(_lastDstarRefs,curTg&&curTg.mode==='DSTAR'?curTg.tg:null);
      }
      if(mode==='XLX'){
        renderXlxGrid(_lastXlxRefs,curTg&&curTg.mode==='XLX'?curTg.tg:null);
      }
      if(mode==='M17'){
        renderM17Grid(_lastM17Refs,curTg&&curTg.mode==='M17'?curTg.tg:null);
      }
      if(mode==='ASL'){
        renderASLGrid(_lastAslNodes,linkedNode);  // A5 writer 2/3 — see applyGridState comment
      }
      if(isDigital&&MODE_CAPS[mode]&&MODE_CAPS[mode].tgRefresh&&_lastTgs[mode]){
        renderTGGrid(mode.toLowerCase()+'-grid',_lastTgs[mode],mode);
      }
    }

    // ── Indicator / linked-node update ────────────────────────────────────
    if(keyedChanged||linkChanged){
      _lastLinkedNode=linkedNode;
      if(mode==='ASL'){
        if(linkChanged){
          curTg=linkedNode?{mode:'ASL',tg:linkedNode}:null;
          renderASLGrid(_lastAslNodes,linkedNode);
        }
        setIndicator(linkedNode||null,'ASL',linkedNode?keyed:false);
      }else if(mode==='ECHO'){
        setIndicator(_lastEchoFav||null,'ECHO',_lastEchoFav?_lastKeyed:false);
      }else{
        setIndicator(curTg?curTg.tg:null,mode,_lastKeyed);
      }
    }

  }catch(_){}
  _keyedTimer=setTimeout(pollKeyed,500);
}
/* ── Analog Bridge confirmation poll ─────────────────────────────────────── */
async function pollAbInfo(){
  try{
    const r=await fetch('/api/abinfo');
    if(!r.ok)return;
    const d=await r.json();

    if(_pendingTune){
      const age=Date.now()-_pendingTune.at;
      const dvsModeFor=m=>m==='FCS'?'YSF':m==='XLX'?'DSTAR':m;
      const modeMatch=!d.mode||d.mode===dvsModeFor(_pendingTune.mode);
      const confirmed=(d.running&&d.last_tune===_pendingTune.tg&&modeMatch)||age>10000;
      if(confirmed){
        const p=_pendingTune;
        _pendingTune=null;
        // Stage 1: prefer backend-resolved YSF room name when available;
        // fall back to the favorites-row label stored in the pending tune.
        const resolvedName=(d.name&&d.name!==p.tg)?d.name:p.name;
        hideWorking();
        showReady(`${p.mode} READY — ${resolvedName}`);
        setIndicator(p.tg,p.mode,_lastKeyed,resolvedName,'confirmed');
      }
      if(_pendingTune)return;
    }

  }catch(_){}
}
refresh().then(()=>{loadTgData();schedulePoll();pollKeyed();initModuleSelects();pollAbInfo();});
setInterval(pollAbInfo,10_000);
setInterval(()=>{
  if(!_uptimeAt)return;
  const el=byId('hdr-uptime');
  if(el)el.textContent=fmtUptime(_uptimeBase+Math.floor((Date.now()-_uptimeAt)/1000));
},60_000);

/* ── SysMon link probe ─────────────────────────────────────── */
async function _probeSysMon() {
  const btn = document.getElementById('lnk-sysmon');
  if (!btn) return;
  try {
    const r = await fetch('/api/sysmon-status');
    if (!r.ok) return;
    const d = await r.json();
    if (d.running) {
      btn.href         = `http://${window.location.hostname}:${d.port}/`;
      btn.style.display = 'inline-block';
      // Save current tab so Back from SysMon restores it (any tab, not just DMR).
      btn.addEventListener('click', () => {
        try{sessionStorage.setItem('sysmonReturn',JSON.stringify({page:curPage}));}catch(_){}
      }, {once:true});
    }
  } catch (_) {}
}
_probeSysMon();
</script>
</body>
</html>
"""

_HTML_BYTES = (HTML
               .replace("__VERSION__",    VERSION)
               .replace("__BUILD_DATE__", BUILD_DATE)
               .encode())
_HTML_GZIP  = gzip.compress(_HTML_BYTES, compresslevel=6)

class _EarlyReturn(Exception):
    pass

class Handler(BaseHTTPRequestHandler):
    timeout = 30

    def log_message(self, fmt, *args):
        pass

    def _accepts_gzip(self) -> bool:
        return "gzip" in self.headers.get("Accept-Encoding", "")

    def send_json(self, data: dict, status: int = 200) -> None:
        raw = json.dumps(data, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type",          "application/json")
        self.send_header("Cache-Control",          "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
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
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'unsafe-inline'; "
                         "script-src 'unsafe-inline'; connect-src 'self'")
        if self._accepts_gzip():
            body = _HTML_GZIP
            self.send_header("Content-Encoding", "gzip")
        else:
            body = _HTML_BYTES
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_status(self) -> None:
        global _status_etag
        client_etag = self.headers.get("If-None-Match", "")

        with _lock:
            current_etag = _status_etag

        if current_etag and client_etag == current_etag:
            self.send_response(304)
            self.send_header("ETag", current_etag)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return

        d = build_status()
        d_hash = {k: v for k, v in d.items() if k != "uptime_seconds"}
        raw_hash = json.dumps(d_hash, separators=(",", ":"), sort_keys=True).encode()
        etag = '"' + hashlib.md5(raw_hash).hexdigest() + '"'

        if client_etag == etag:
            with _lock:
                _status_etag = etag
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return

        raw = json.dumps(d, separators=(",", ":")).encode()
        if self._accepts_gzip() and len(raw) > 256:
            body = gzip.compress(raw, compresslevel=1)
            encoding = "gzip"
        else:
            body = raw
            encoding = None

        with _lock:
            _status_etag = etag
        self.send_response(200)
        self.send_header("Content-Type",          "application/json")
        self.send_header("Cache-Control",          "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("ETag",                   etag)
        if encoding:
            self.send_header("Content-Encoding", encoding)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        if length > 524_288:
            self.send_json({"ok": False, "message": "Request body too large"}, 413)
            raise _EarlyReturn()
        return self.rfile.read(length)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        handler = _GET_ROUTES.get(path)
        if not handler:
            self.send_response(404); self.end_headers()
            return
        try:
            handler(self)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            log.exception("Unhandled error in GET %s", path)
            try:
                self.send_json({"ok": False, "message": "Internal server error"}, 500)
            except Exception:
                pass

    def do_POST(self) -> None:
        if self.path != "/api/action":
            self.send_response(404); self.end_headers(); return
        try:
            data = json.loads(self._read_body())
        except _EarlyReturn:
            return
        except (json.JSONDecodeError, ValueError) as e:
            self.send_json({"ok": False, "message": f"Bad request: {e}"}, 400); return
        if not isinstance(data, dict):
            self.send_json({"ok": False, "message": "Request body must be a JSON object"}, 400); return
        try:
            ok, msg = self._dispatch_action(data)
        except _EarlyReturn:
            return
        except Exception:
            log.exception("Unhandled error in action dispatch")
            self.send_json({"ok": False, "message": "Internal server error"}, 500); return
        try:
            self.send_json({"ok": ok, "message": msg}, 200 if ok else 400)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _dispatch_action(self, data: dict) -> Tuple[bool, str]:
        action = str(data.get("action", ""))

        if action == "switch-tab":
            page = str(data.get("page", "")).upper()
            return (False, f"Unknown page '{page}'") if page not in ALL_PAGES                   else action_switch_tab(page)

        if action == "retune-tab":
            page   = str(data.get("page",   "")).upper()
            server = str(data.get("server", "")).strip()
            return (False, f"Unknown page '{page}'") if page not in ALL_PAGES                   else action_retune_tab(page, server)

        if action == "tune":
            mode = str(data.get("mode", "")).upper()
            tg   = str(data.get("tg",   ""))
            name = _clip_label(str(data.get("name", "")))
            return (False, f"Unknown mode '{mode}'") if mode not in TUNE_MODES                   else action_tune(mode, tg, name)

        if action == "quick-tune":
            mode = str(data.get("mode", "")).upper()
            tg   = str(data.get("tg",   "")).strip()
            return (False, f"Unknown mode '{mode}'") if mode not in TUNE_MODES                   else action_quick_tune(mode, tg)

        if action == "asl-connect":
            return action_asl_connect(str(data.get("node", "")), _clip_label(str(data.get("name", ""))))

        if action == "asl-disc-current":
            return action_asl_disconnect_current()

        if action == "disc-perm-link":
            return action_disc_perm_link()

        if action == "connect-by-number":
            return action_connect_by_number(str(data.get("node", "")))

        if action == "echo-connect":
            return action_echo_connect(str(data.get("node", "")), _clip_label(str(data.get("name", ""))))

        if action == "echo-connect-by-number":
            return action_echo_connect_by_number(str(data.get("node", "")))

        if action == "echo-disc":
            return action_echo_disconnect()

        if action == "dstar-connect":
            base   = str(data.get("base",   "")).strip()
            module = str(data.get("module", "")).strip()
            name   = _clip_label(str(data.get("name",   "")).strip() or f"DSTAR {base}{module}")
            return action_dstar_connect(base, module, name)

        if action == "xlx-connect":
            base   = str(data.get("base",   "")).strip()
            module = str(data.get("module", "")).strip()
            name   = _clip_label(str(data.get("name", "")).strip() or f"XLX {base} Mod-{module}")
            return action_xlx_connect(name, base, module)

        if action == "dstar-disconnect":
            return action_dstar_disconnect()

        if action == "xlx-disconnect":
            return action_xlx_disconnect()

        if action == "m17-connect":
            base   = str(data.get("base",   "")).strip()
            module = str(data.get("module", "")).strip()
            ip     = str(data.get("ip",     "")).strip()
            name   = _clip_label(str(data.get("name", "")).strip() or f"M17 {base} Mod-{module}")
            return action_m17_connect(name, base, ip, module)

        if action == "m17-disconnect":
            return action_m17_disconnect()

        if action == "disc-all":
            self.send_json({"ok": True, "message": "Emergency disconnect — restarting services…"})
            threading.Thread(target=action_disconnect_all, daemon=True).start()
            raise _EarlyReturn()

        if action == "switch-dmr-server":
            name = str(data.get("name", "")).strip()
            if not name:
                return False, "name is required"
            return action_switch_dmr_server(name)

        if action == "save-all":
            nd = data.get("nodes", [])
            tg = data.get("talkgroups", [])
            ec = data.get("echo_nodes", [])
            if not (isinstance(nd, list) and isinstance(tg, list) and isinstance(ec, list)):
                return False, "nodes, talkgroups and echo_nodes must be lists"
            return action_save_all(nd, tg, ec)

        if action == "save-dmr-server-tgs":
            srv_tgs = data.get("server_tgs", {})
            srv_list = data.get("server_list", None)
            if not isinstance(srv_tgs, dict):
                return False, "server_tgs must be a dict"
            return action_save_dmr_server_tgs(srv_tgs, srv_list)

        if action == "save-xlx":
            rows = data.get("rows", [])
            if not isinstance(rows, list):
                return False, "rows must be a list"
            return action_save_xlx(rows)

        if action == "save-m17":
            rows = data.get("rows", [])
            if not isinstance(rows, list):
                return False, "rows must be a list"
            return action_save_m17(rows)

        if action == "save-config":
            allowed  = {"asl_node", "bridge_node", "port", "callsign"}
            cfg_data = {k: str(v) for k, v in data.items() if k in allowed}
            if "enabled_tabs" in data and isinstance(data["enabled_tabs"], list):
                cfg_data["enabled_tabs"] = data["enabled_tabs"]
            if "mode_net_urls" in data and isinstance(data["mode_net_urls"], dict):
                cfg_data["mode_net_urls"] = data["mode_net_urls"]
            if "bridge_nodes" in data and isinstance(data["bridge_nodes"], (list, tuple)):

                cfg_data["bridge_nodes"] = list(data["bridge_nodes"])
            return action_save_config(cfg_data)

        if action == "reboot":
            if os.geteuid() != 0:
                return False, "root required for reboot"
            log.warning("REBOOT requested")
            self.send_json({"ok": True, "message": "Rebooting…"})
            threading.Thread(
                target=lambda: (time.sleep(1), os.system("reboot")),
                daemon=True,
            ).start()
            raise _EarlyReturn()

        if action == "shutdown":
            if os.geteuid() != 0:
                return False, "root required for shutdown"
            log.warning("SHUTDOWN requested")
            self.send_json({"ok": True, "message": "Shutting down…"})
            threading.Thread(
                target=lambda: (time.sleep(1), os.system("shutdown -h now")),
                daemon=True,
            ).start()
            raise _EarlyReturn()

        return False, f"Unknown action '{action}'"

def _send_event_response(handler) -> None:
    try:
        handler.send_json({"ok": True})
    except (BrokenPipeError, ConnectionResetError):
        pass

_GET_ROUTES: dict = {
    "/":               lambda h: h.send_html(),
    "/index.html":     lambda h: h.send_html(),
    "/api/ping":       lambda h: h.send_ping(),
    "/api/sysmon-status": lambda h: h.send_json(action_sysmon_status()),
    "/api/status":     lambda h: h.send_status(),
    "/api/keyed":      lambda h: h.send_json(action_get_keyed()),
    "/api/talkgroups":     lambda h: h.send_json(action_get_talkgroups()),
    "/api/asl-nodes":      lambda h: h.send_json(action_get_asl_nodes()),
    "/api/echo-nodes":     lambda h: h.send_json(action_get_echo_nodes()),
    "/api/xlx-reflectors": lambda h: h.send_json(action_get_xlx_reflectors()),
    "/api/m17-reflectors": lambda h: h.send_json(action_get_m17_reflectors()),
    "/api/dmr-servers":    lambda h: h.send_json(action_get_dmr_servers()),
    "/api/dmr-server-tgs": lambda h: h.send_json(action_get_dmr_server_tgs()),
    "/api/dmr-ready":      lambda h: h.send_json(action_dmr_server_ready()),
    "/api/config":     lambda h: h.send_json(action_get_config()),
    "/api/event":      lambda h: (action_handle_event(), _send_event_response(h)),
    "/api/abinfo":     lambda h: h.send_json(action_get_abinfo()),
}

_ABINFO_EMPTY = {
    "ok":        False,
    "running":   False,
    "mode":      "",
    "last_tune": "",
    "tg":        "",
    "name":      "",
}

def action_get_abinfo() -> dict:
    try:
        data = _read_abinfo()

        if not data:
            return dict(_ABINFO_EMPTY)

        ambe_mode = str(data.get("tlv", {}).get("ambe_mode", "")).strip()
        tg        = str(data.get("digital", {}).get("tg", "")).strip()

        name = ""
        if ambe_mode.upper() in ("YSFN", "YSFW") and tg:
            name = _resolve_ysf_name(tg, ambe_mode)

        return {
            "ok":        True,
            "running":   True,
            "mode":      ambe_mode,
            "last_tune": data.get("last_tune", ""),
            "tg":        tg,
            "name":      name,
        }
    except Exception as exc:
        log.warning("action_get_abinfo: %s", exc)
        return dict(_ABINFO_EMPTY)

def _dvs_startup_init() -> None:
    _st = get_state()
    set_state(page="DMR")
    if _st.dmr_servers:
        action_switch_dmr_server(_st.dmr_servers[0]["name"])
    else:
        _dvs("tune", TG_DISCONNECT)
        set_state(current_dvs_mode="DMR")

def _is_fresh_boot() -> bool:
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except Exception:
        return True
    try:
        marker = Path(_BOOT_MARKER_PATH)
        prev = marker.read_text().strip() if marker.is_file() else None
        fresh = prev != boot_id
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(boot_id)
        return fresh
    except Exception:
        return True

def startup() -> None:
    global DVS_PATH
    found = _find_dvs_path()
    if found:
        DVS_PATH = found
        log.info("DVS path: %s", DVS_PATH)
    else:
        log.warning("dvswitch.sh not found in any search path — DVS disabled")

    _ami_connect()
    has_asl = _detect_asl()
    has_dvs = _detect_dvs()
    has_m17 = _detect_m17()
    set_state(has_asl=has_asl, has_dvs=has_dvs, has_m17=has_m17)
    if has_m17:
        log.info("M17 bridge detected — tab enabled")

    cs = _read_callsign()
    set_state(callsign=cs)
    if cs:
        log.info("Callsign: %s", cs)
    else:
        log.warning("Callsign not found in any INI file — checked: %s",
                    ", ".join(_CALLSIGN_SEARCH_PATHS))

    _migrate_legacy_conf()
    nodes, tgs, echo_nodes = load_conf()
    set_state(talkgroups=tgs, asl_nodes=nodes, echo_nodes=echo_nodes)

    fresh_boot = _is_fresh_boot()
    if not fresh_boot:
        log.info("startup: process restart within same boot — preserving live links")

    if has_dvs:
        has_stfu = _detect_stfu()
        set_state(has_stfu=has_stfu)
        if has_stfu:
            set_state(stfu_server=detect_stfu_server())

        live_ab = _read_abinfo()
        if live_ab:
            ab_mode    = live_ab.get("tlv", {}).get("ambe_mode", "")
            ab_last_tg = live_ab.get("last_tune", "")
            ab_gw      = str(live_ab.get("digital", {}).get("gw", "0")).strip()
            ab_active  = bool(ab_gw and ab_gw != "0")
            if ab_mode in DIGITAL_MODES:
                if ab_active or not fresh_boot:
                    reason = (f"active call gw={ab_gw}" if ab_active
                              else "idle, process restart same boot")
                    log.info(
                        "startup: AB live in %s (%s) — preserving connection",
                        ab_mode, reason,
                    )
                    set_state(
                        current_dvs_mode = ab_mode,
                        current_fav      = ab_last_tg or None,
                        current_fav_node  = None,
                    )
                else:
                    log.info(
                        "startup: AB live in %s (idle, fresh boot) — re-establishing server connection",
                        ab_mode,
                    )
                    if ab_mode == "DMR":
                        _dvs_startup_init()
                    else:
                        _dvs("tune", TG_DISCONNECT)
                        _dvs_settle()
                        _dvs("mode", ab_mode)
                        set_state(
                            current_dvs_mode = ab_mode,
                            current_fav      = None,
                            current_fav_node = None,
                        )
            else:
                _dvs_startup_init()
        else:
            _dvs_startup_init()

    if has_asl or has_dvs:
        try:
            set_state(perm_link_nodes=_read_perm_links())
        except Exception:
            pass
        threading.Thread(target=_link_poll_loop, daemon=True).start()

    if has_asl:
        has_echo = _detect_echo()
        set_state(has_echo=has_echo)
        if fresh_boot:
            _disconnect_all()
            time.sleep(0.5)
        else:
            log.info("startup: process restart within same boot — skipping ASL disconnect-all")
        _write_event_script()
        if "ASL" in _cfg.enabled_tabs:
            set_state(page="ASL", status="ASL | Ready", current_fav=None, current_fav_node=None)
        else:
            _st2     = get_state()
            _srv_lbl = _st2.active_dmr_server or "Disconnected"
            set_state(page="DMR", status=f"DMR | {_srv_lbl}", current_fav=None, current_fav_node=None)
            _seed_dmr_tgs()
    elif has_dvs:
        _st2 = get_state()
        _srv_lbl = _st2.active_dmr_server or "Disconnected"
        set_state(page="DMR", status=f"DMR | {_srv_lbl}", current_fav=None, current_fav_node=None)
        _seed_dmr_tgs()
    else:
        set_state(page="ASL", status="No radio software detected")

def _lan_ip() -> str:
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "your-pi-ip"

class _QuietThreadingHTTPServer(ThreadingHTTPServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._conn_semaphore = threading.BoundedSemaphore(_MAX_CONCURRENT_CONNECTIONS)

    def verify_request(self, request, client_address) -> bool:
        if not self._conn_semaphore.acquire(blocking=False):
            log.warning("Connection cap (%d) reached, rejecting %s",
                        _MAX_CONCURRENT_CONNECTIONS, client_address)
            return False
        return True

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._conn_semaphore.release()

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)

def install_service() -> None:
    if os.geteuid() != 0:
        print("ERROR: install requires root  →  sudo python3 asl_dvs_dashboard.py --install",
              file=sys.stderr)
        sys.exit(1)

    current_script = os.path.abspath(__file__)
    print("Installing asl_dvs_dashboard...")

    os.makedirs(_INSTALL_DIR, exist_ok=True)
    dest = os.path.join(_INSTALL_DIR, os.path.basename(current_script))
    shutil.copy2(current_script, dest)
    os.chmod(dest, 0o755)
    print(f"  [+] Copied {os.path.basename(current_script)} -> {dest}")

    if os.path.islink(_INSTALL_LINK) or os.path.exists(_INSTALL_LINK):
        os.remove(_INSTALL_LINK)
    os.symlink(dest, _INSTALL_LINK)
    print(f"  [+] Symlinked {_INSTALL_LINK} -> {dest}")

    with open(_SERVICE_PATH, "w") as f:
        f.write(_SERVICE_CONTENT)
    print(f"  [+] Wrote service file at {_SERVICE_PATH}")

    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "asl_dvs_dashboard.service"], check=True)
    subprocess.run(["systemctl", "restart", "asl_dvs_dashboard.service"], check=True)
    print("  [+] Enabled and restarted asl_dvs_dashboard.service")
    print(f"\nInstall complete. {ASL_DVS_CONF} was not touched.")
    print("View logs anytime using:  journalctl -u asl_dvs_dashboard -f")

def uninstall_service() -> None:
    if os.geteuid() != 0:
        print("ERROR: uninstall requires root  →  sudo python3 asl_dvs_dashboard.py --uninstall",
              file=sys.stderr)
        sys.exit(1)

    print("Uninstalling asl_dvs_dashboard...")

    subprocess.run(["systemctl", "disable", "--now", "asl_dvs_dashboard.service"],
                    stderr=subprocess.DEVNULL)
    print("  [-] Stopped and disabled asl_dvs_dashboard.service")

    if os.path.exists(_SERVICE_PATH):
        os.remove(_SERVICE_PATH)
        print(f"  [-] Removed {_SERVICE_PATH}")
    subprocess.run(["systemctl", "daemon-reload"], stderr=subprocess.DEVNULL)

    if os.path.islink(_INSTALL_LINK) or os.path.exists(_INSTALL_LINK):
        target = None
        if os.path.islink(_INSTALL_LINK):
            target = os.readlink(_INSTALL_LINK)
        os.remove(_INSTALL_LINK)
        print(f"  [-] Removed {_INSTALL_LINK}")
        if target and os.path.basename(target).startswith("asl_dvs_dashboard_") and os.path.isfile(target):
            os.remove(target)
            print(f"  [-] Removed {target}")

    print(f"\nUninstall complete. {ASL_DVS_CONF} was not touched.")

def main() -> None:
    if os.geteuid() != 0:
        print("ERROR: run as root  →  sudo python3 asl_dvs_dashboard.py", file=sys.stderr)
        sys.exit(1)
    startup()
    Handler.allow_reuse_address = True
    server = _QuietThreadingHTTPServer(("0.0.0.0", _cfg.port), Handler)

    def _sigterm(signum, frame):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, _sigterm)

    ip = _lan_ip()
    pad = " " * max(0, 31 - len(_cfg.asl_node))
    lpad = " " * max(0, 16 - len(str(_cfg.port)))
    npad = " " * max(0, 6 - len(str(_cfg.port)))
    _bridge_short_labels = ("Digital", "M17", "Reserved", "Reserved")
    _bridge_lines = []
    for _i in range(BRIDGE_SLOT_COUNT):
        _val = _cfg.bridge_nodes[_i] or "—"
        _bpad = " " * max(0, 31 - len(_val))
        _bridge_lines.append(f"║  {_bridge_short_labels[_i]:<10}: {_val}{_bpad}║")
    _bridge_block = "\n".join(_bridge_lines)
    print(f"""
╔══════════════════════════════════════════════╗
║         ASL-DVS Node Control Dashboard       ║
╠══════════════════════════════════════════════╣
║  ASL node  : {_cfg.asl_node}{pad}║
╠══════════════════════════════════════════════╣
{_bridge_block}
╠══════════════════════════════════════════════╣
║  Local     : http://localhost:{_cfg.port}{lpad}║
║  Network   : http://{ip}:{_cfg.port}{npad}  ║
╚══════════════════════════════════════════════╝
""")
    _sd_notify("READY=1")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()

if __name__ == "__main__":
    _parser = argparse.ArgumentParser(description="ASL-DVS Node Control Dashboard")
    _parser.add_argument("--install", action="store_true",
                          help="Install as a systemd service (versioned copy + stable symlink)")
    _parser.add_argument("--uninstall", action="store_true",
                          help="Remove the systemd service and installed files")
    _args = _parser.parse_args()

    if _args.install:
        install_service()
    elif _args.uninstall:
        uninstall_service()
    else:
        main()
