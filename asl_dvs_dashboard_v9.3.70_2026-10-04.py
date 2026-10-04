#!/usr/bin/env python3
#
# ASL-DVS Node Control  —  asl_dvs_dashboard.py  —  v9.3.70  —  2026-10-04
# KD8PGK / Claude AI (Anthropic)  —  CC BY-NC 4.0

import argparse
import codecs
import contextlib
import errno
import fcntl
import functools
import gzip
import glob as _glob
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
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
from urllib.parse import urlparse, parse_qs

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

VERSION      = "9.3.70"
BUILD_DATE   = "2026-10-04"

ASL_NODE        = "652702"
ASL_BRIDGE_NODE = "1999"
ASL_PARROT_NODE = "55553"
ASL_CONF        = "/etc/asterisk/rpt.conf"
DVS_PATH        = "/opt/MMDVM_Bridge/dvswitch.sh"

_MAX_CONCURRENT_CONNECTIONS = 48
_MAX_CONCURRENT_CONNECTIONS_PER_IP = 16

_DVS_SEARCH_PATHS = [
    "/opt/MMDVM_Bridge/dvswitch.sh",
    "/usr/local/sbin/dvswitch.sh",
    "/var/lib/dvswitch/dvswitch.sh",
]
PORT            = 8989


WIFIMON_SHUTDOWN_STATE_FILE = "/run/wifimon/shutdown_state.json"


M17_NODE      = "1917"
M17_INI_PATH  = "/opt/USRP2M17/USRP2M17.ini"
M17_SERVICE   = "usrp2m17"


BRIDGE_SLOT_DIGITAL    = 0
BRIDGE_SLOT_M17        = 1
BRIDGE_SLOT_PHONE      = 2
BRIDGE_SLOT_COUNT      = 4
BRIDGE_SLOT_LABELS     = ("Digital Voice Bridge", "M17 Bridge", "Phone Bridge", "Reserved")
PHONE_NODE             = "1001"
DEFAULT_BRIDGE_NODES   = [ASL_BRIDGE_NODE, M17_NODE, PHONE_NODE, ""]


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
_DSTAR_BASE_LEN = 6

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
ALL_PAGES        = ("ASL", "ECHO") + DIGITAL_MODES + ("FCS", "XLX", "M17", "PHONE")
VALID_CONF_MODES = {"DMR", "STFU", "YSF", "FCS", "P25", "NXDN", "DSTAR"}
TUNE_MODES       = set(DIGITAL_MODES) | {"FCS"}


BRIDGE_SLOT_PAGES = {
    BRIDGE_SLOT_DIGITAL: TUNE_MODES | {"XLX"},
    BRIDGE_SLOT_M17:     {"M17"},
    BRIDGE_SLOT_PHONE:   {"PHONE"},
}

@dataclass
class Config:
    asl_node:            str      = ASL_NODE
    bridge_nodes:        List[str] = field(default_factory=lambda: list(DEFAULT_BRIDGE_NODES))
    port:                int      = PORT
    callsign:            str      = ""
    enabled_tabs:        Set[str] = field(default_factory=lambda: set(ALL_PAGES))
    enabled_tabs_sorted: list     = field(default_factory=lambda: list(ALL_PAGES))
    cpuweight_enabled:   bool     = False

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
            if not items[BRIDGE_SLOT_PHONE]:
                items[BRIDGE_SLOT_PHONE] = PHONE_NODE
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
        if "cpuweight_enabled" in cfg:
            v = cfg["cpuweight_enabled"]
            new_val = v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on")
            prev_val = _cfg.cpuweight_enabled
            _cfg.cpuweight_enabled = new_val
            if new_val and not prev_val:
                _cpuweight_enable_all()
            elif prev_val and not new_val:
                _cpuweight_reset_all()

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

def _strip_ctrl(s: str) -> str:
    return "".join(c for c in s if ord(c) >= 0x20 and c != "\x7f")

def _sf(d: dict, key: str, fallback: str = "") -> str:
    return _strip_ctrl(str(d.get(key, fallback)).strip()).replace("|", "-")

def _conf_field(s, url: bool = False) -> str:
    out = _strip_ctrl(str(s or "")).strip()
    return out.replace("|", "%7C" if url else "-")

_RC_TIMEOUT = -1

def run(cmd: list, timeout: int = 10) -> Tuple[str, int]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "timeout", _RC_TIMEOUT
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

_AMI_RECV_MAX_BYTES = 1_000_000
_AMI_BLOCK_END_RE   = re.compile(r"\r?\n\r?\n")
_AMI_LEGACY_END     = "--END COMMAND--"
_ami_action_seq     = 0

class _AmiIncomplete(Exception):
    def __init__(self, partial: str):
        super().__init__("AMI reply incomplete")
        self.partial = partial

def _ami_next_id() -> str:
    global _ami_action_seq
    _ami_action_seq += 1
    return f"dsh{os.getpid()}-{_ami_action_seq}"

def _ami_reset(reason: Optional[str] = None) -> None:
    global _ami_sock, _ami_available
    if reason:
        log.warning("AMI: %s — resetting the connection", reason)
    try:
        if _ami_sock is not None:
            _ami_sock.close()
    except Exception:
        pass
    _ami_sock      = None
    _ami_available = False

def _ami_drain(sock) -> None:
    stale = 0
    sock.setblocking(False)
    try:
        while stale < _AMI_RECV_MAX_BYTES:
            try:
                chunk = sock.recv(4096)
            except (BlockingIOError, InterruptedError):
                break
            if not chunk:
                raise ConnectionError("AMI socket closed by Asterisk")
            stale += len(chunk)
    finally:
        sock.setblocking(True)
    if stale:
        log.info("AMI: discarded %d bytes of old replies/events before sending", stale)

def _ami_take_message(buf: str) -> Tuple[Optional[str], str]:
    body = buf.lstrip("\r\n")
    if not body:
        return None, buf
    if body.startswith("Response: Follows"):
        i = body.find(_AMI_LEGACY_END)
        if i < 0:
            return None, buf
        j = i + len(_AMI_LEGACY_END)
        return body[:j], body[j:]
    m = _AMI_BLOCK_END_RE.search(body)
    if not m:
        return None, buf
    return body[:m.start()], body[m.end():]

def _ami_header(msg: str, name: str) -> Optional[str]:
    pre = name.lower() + ":"
    for line in msg.splitlines()[:6]:
        if line.lower().startswith(pre):
            return line[len(pre):].strip()
    return None

def _ami_read_reply(sock, action_id: str) -> str:
    dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
    buf = ""
    total = 0
    while True:
        while True:
            msg, rest = _ami_take_message(buf)
            if msg is None:
                break
            buf = rest
            aid = _ami_header(msg, "ActionID")
            if msg.startswith("Event:"):
                continue
            if aid is not None and aid != action_id:
                log.info("AMI: skipped a stale reply (ActionID %s, waiting for %s)",
                         aid, action_id)
                continue
            return msg
        try:
            chunk = sock.recv(4096)
        except _socket.timeout:
            raise _AmiIncomplete(buf)
        except OSError:
            if total == 0:
                raise
            raise _AmiIncomplete(buf)
        if not chunk:
            if total == 0:
                raise ConnectionError("AMI socket closed by Asterisk")
            raise _AmiIncomplete(buf)
        total += len(chunk)
        buf += dec.decode(chunk)
        if total >= _AMI_RECV_MAX_BYTES:
            log.warning("AMI: reply passed the %d-byte ceiling without ending",
                        _AMI_RECV_MAX_BYTES)
            raise _AmiIncomplete(buf)

def _ami_command_output(msg: str) -> str:
    lines = msg.splitlines()
    if lines and lines[0].startswith("Response: Follows"):
        out_lines = []
        header = True
        for line in lines[1:]:
            if header and (line.startswith("Privilege:") or line.startswith("ActionID:")):
                continue
            header = False
            if line.endswith(_AMI_LEGACY_END):
                tail = line[:-len(_AMI_LEGACY_END)]
                if tail.strip():
                    out_lines.append(tail)
                break
            out_lines.append(line)
        return "\n".join(out_lines).strip()
    out_lines = [line[7:].lstrip() for line in lines if line.startswith("Output:")]
    if not out_lines:
        out_lines = [line for line in lines
                     if not line.startswith("Response:") and not line.startswith("ActionID:")]
    return "\n".join(out_lines).strip()

def _ami_command_once(cmd_str: str, timeout: float) -> str:
    aid = _ami_next_id()
    _ami_drain(_ami_sock)
    _ami_sock.settimeout(timeout)
    _ami_sock.sendall((f"Action: Command\r\n"
                       f"ActionID: {aid}\r\n"
                       f"Command: {cmd_str}\r\n"
                       f"\r\n").encode())
    return _ami_command_output(_ami_read_reply(_ami_sock, aid))

def ami_command(cmd_str: str, timeout: int = 4, priority: bool = False) -> Tuple[str, bool]:
    global _ami_reconnect_next_try
    if _has_ctrl_chars(cmd_str):
        log.warning("AMI: rejected command with control characters: %r", cmd_str)
        return "rejected: illegal characters in command", False
    if _ami_perm_fail:
        out, rc = _asterisk_rx(cmd_str, timeout=timeout, priority=priority)
        return out, rc == 0

    with _ami_lock:
        if not _ami_available:
            now = time.monotonic()
            if now >= _ami_reconnect_next_try:
                _ami_reconnect_next_try = now + _AMI_RECONNECT_COOLDOWN
                _ami_connect()

        if _ami_available:
            try:
                return _ami_command_once(cmd_str, timeout), True
            except _AmiIncomplete:
                _ami_reset(f"no complete reply to {cmd_str!r} within {timeout}s")
                return f"AMI reply to {cmd_str!r} did not finish", False
            except Exception as e:
                log.warning("AMI: socket error on command %r: %s — reconnecting", cmd_str, e)
                _ami_reset()
                if _ami_connect():
                    try:
                        return _ami_command_once(cmd_str, timeout), True
                    except _AmiIncomplete:
                        _ami_reset(f"no complete reply to {cmd_str!r} within {timeout}s (retry)")
                        return f"AMI reply to {cmd_str!r} did not finish", False
                    except Exception as e2:
                        log.warning("AMI: retry failed: %s — falling back to subprocess", e2)
                        _ami_reset()
    out, rc = _asterisk_rx(cmd_str, timeout=timeout, priority=priority)
    return out, rc == 0

def ami_action(fields: List[Tuple[str, str]], timeout: int = 4) -> Tuple[str, bool]:
    global _ami_reconnect_next_try
    for k, v in fields:
        if _has_ctrl_chars(k) or _has_ctrl_chars(v):
            return "rejected: illegal characters in action", False
    if _ami_perm_fail:
        return "AMI login is not available", False
    with _ami_lock:
        if not _ami_available:
            now = time.monotonic()
            if now >= _ami_reconnect_next_try:
                _ami_reconnect_next_try = now + _AMI_RECONNECT_COOLDOWN
                _ami_connect()
        if not _ami_available:
            return "AMI is not connected", False
        aid = next((v for k, v in fields if k.lower() == "actionid"), None) or _ami_next_id()
        sent = [(k, v) for k, v in fields if k.lower() != "actionid"] + [("ActionID", aid)]
        action = "".join(f"{k}: {v}\r\n" for k, v in sent) + "\r\n"
        try:
            _ami_drain(_ami_sock)
            _ami_sock.settimeout(timeout)
            _ami_sock.sendall(action.encode())
            resp = _ami_read_reply(_ami_sock, aid)
            return resp, "Response: Success" in resp
        except _AmiIncomplete:
            _ami_reset(f"no complete reply to action {fields[0][1] if fields else ''!r}")
            return "AMI reply did not finish", False
        except Exception as e:
            log.warning("AMI: socket error on action %r: %s — reconnecting",
                        fields[0][1] if fields else "", e)
            _ami_reset()
            return f"AMI error: {e}", False

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
                    tg_val = (parts2[0].strip().ljust(_DSTAR_BASE_LEN)
                              + parts2[1].upper() + "L")
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
            if section == "FCS":
                row_url = _fcs_lh_fix(row_url)
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
    "FCS":   "http://xreflector.net/",
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

def _atomic_write(path: Path, data: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    open_flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    try:
        fd = os.open(str(tmp), open_flags, 0o600)
    except OSError as e:
        if e.errno != errno.ELOOP:
            raise
        log.warning("_atomic_write: %s is a symlink — removing and retrying", tmp)
        tmp.unlink(missing_ok=True)
        fd = os.open(str(tmp), open_flags, 0o600)
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

PHONE_CONF       = "/etc/asl_dvs/phone.json"
PHONE_MAX_NETS   = 6
PHONE_FAV_COUNT  = 10
PHONE_TONE_BTNS  = 5
PHONE_TYPES      = ("sip", "sip_ip", "hoip", "awire", "iax2")
_PHONE_SIP_TYPES   = ("sip", "sip_ip", "hoip", "awire")
_PHONE_LOGIN_SIP   = ("sip", "hoip", "awire")
_PHONE_EXT_TYPES   = ("hoip", "awire")
_AWIRE_DEFAULT_HOST = "pbx1-wv.amateurwire.org"
_AWIRE_DEFAULT_PORT = "5060"
_AWIRE_NAME_RE      = re.compile(r"^[A-Za-z0-9 ./\-]{1,40}$")
_HOIP_DEFAULT_HOST = "premium.hamsoverip.com"
_HOIP_DEFAULT_PORT = "5160"
_HOIP_VM_ALIAS     = "0097"
_HOIP_CALLSIGN_RE  = re.compile(r"^[A-Z0-9/\-]{3,12}$")
_HOIP_EMAIL_RE     = re.compile(r"^[^@\s;]+@[^@\s;]+\.[^@\s;]+$")
_HOIP_URL_RE       = re.compile(r"^https://[A-Za-z0-9.\-]+(?::[0-9]{1,5})?(?:/[^\s\"'<>\\]*)?$")
_HOIP_USER_RE      = re.compile(r"^[A-Za-z0-9._@\-]{1,64}$")
_HOIP_VMACCESS_RE  = re.compile(r"^[0-9*#]{1,8}$")
_PHONE_TEST_ALIAS  = "0098"
_PHONE_TEST_RE     = re.compile(r"^[0-9*#]{1,20}$")
PHONE_TONE_MODES     = ("auto", "rfc4733", "inband", "info", "auto_info")
_PHONE_TONE_MODE_DEF = "auto"
_HOIP_TONE_MODE    = "rfc4733"
_PHONE_TONE_MODE_LBL = {"auto": "Automatic", "rfc4733": "Tone packets only (RFC 2833)",
                        "inband": "Real tones in the audio", "info": "SIP messages",
                        "auto_info": "Packets, then SIP messages"}
PHONE_TONE_PATHS     = ("provider", "node", "sound")
_PHONE_TONE_PATH_DEF = "provider"
_PHONE_TONE_PATH_LBL = {"provider": "Straight to the provider (v9.3.13 way)", "node": "Through the call (test)",
                        "sound": "As sound (tone recordings)"}
_HL_USER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{2,31}$")
_HL_PASS_RE = re.compile(r"^[A-Za-z0-9._\-+=!%^*~]{8,64}$")
_HL_DEFAULT = {"enabled": False, "username": "", "password": "", "fqdn": "", "port": "", "node": ""}
PHONE_DIALING    = ("phone", "ext")
PHONE_INCOMING   = ("pin", "open", "off")
_PHONE_TYPE_LBL  = {"sip": "SIP with login", "sip_ip": "SIP by IP address",
                    "hoip": "Hams Over IP", "awire": "AmateurWire", "iax2": "IAX2"}
_PHONE_DIALTIME_MIN, _PHONE_DIALTIME_MAX, _PHONE_DIALTIME_DEF = 5000, 90000, 20000
_PHONE_SIMPLEX_DEF = {"enabled": False, "voxtimeout": 10000, "voxrecover": 2000,
                      "patchdelay": 25, "phonedelay": 25}
_PHONE_SIMPLEX_RANGE = {"voxtimeout": (1000, 60000), "voxrecover": (500, 10000),
                        "patchdelay": (0, 100), "phonedelay": (0, 100)}
_phone_lock      = threading.RLock()
_phone_doc_cache: list = [0.0, None]
_HOST_RE         = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.\-]{0,120}[A-Za-z0-9])?$")
_PHONE_DIGITS_RE = re.compile(r"^[0-9]+$")

def _phone_default() -> dict:
    return {
        "networks":      [],
        "active":        "",
        "patch_enabled": True,
        "dialtime":      _PHONE_DIALTIME_DEF,
        "simplex":       dict(_PHONE_SIMPLEX_DEF),
        "tone_path":     _PHONE_TONE_PATH_DEF,
        "hoip_link":     dict(_HL_DEFAULT),
        "hangtime":      "",
        "signin_mode":   "picked",
        "tot_phone_off": True,
        "tot_cap_min":   15,
        "activated":     False,
    }

def _phone_load() -> dict:
    with _phone_lock:
        try:
            raw = json.loads(Path(PHONE_CONF).read_text())
        except FileNotFoundError:
            return _phone_default()
        except Exception as e:
            log.warning("phone: could not read %s (%s) — using defaults", PHONE_CONF, e)
            return _phone_default()
    if not isinstance(raw, dict):
        return _phone_default()
    doc = _phone_default()
    for k in ("networks", "active", "patch_enabled", "dialtime", "hangtime", "signin_mode",
              "tot_phone_off", "tot_cap_min"):
        if k in raw:
            doc[k] = raw[k]
    if "activated" in raw:
        doc["activated"] = raw["activated"] is True
    else:
        doc["activated"] = os.path.isfile(_ph_path(_PH_OWNED["ext"]))
    if raw.get("tone_path_user") and raw.get("tone_path") in PHONE_TONE_PATHS:
        doc["tone_path"], doc["tone_path_user"] = raw["tone_path"], True
    sx = dict(_PHONE_SIMPLEX_DEF)
    if isinstance(raw.get("simplex"), dict):
        for k in sx:
            if k in raw["simplex"]:
                sx[k] = raw["simplex"][k]
    doc["simplex"] = sx
    hl = dict(_HL_DEFAULT)
    if isinstance(raw.get("hoip_link"), dict):
        for k in hl:
            if k in raw["hoip_link"]:
                hl[k] = raw["hoip_link"][k]
    doc["hoip_link"] = hl
    nets = [n for n in doc["networks"] if isinstance(n, dict)][:PHONE_MAX_NETS] \
        if isinstance(doc["networks"], list) else []
    for n in nets:
        n["favorites"] = _phone_norm_favs(n.get("favorites"))
    doc["networks"] = nets
    if _phone_assign_nodes(nets):
        with _phone_lock:
            ok, msg = _phone_write(doc)
        log.info("phone: gave phone networks their node numbers (%s): %s", "saved" if ok else msg,
                 ", ".join(f"{n.get('name', '?')}={n['node']}" for n in nets))
    legacy = _phone_norm_favs(raw.get("favorites")) if isinstance(raw.get("favorites"), list) else []
    if any(f["number"] for f in legacy):
        home = _phone_fav_home(doc)
        if home is None:
            doc["favorites"] = legacy
        else:
            with _phone_lock:
                home["favorites"] = _phone_merge_favs(home["favorites"], legacy)
                ok, msg = _phone_write(doc)
            log.info("phone: moved the shared favorites to %s (%s)", home.get("name", "?"),
                     "saved" if ok else msg)
    return doc

def _phone_norm_favs(lst) -> List[dict]:
    out: List[dict] = []
    for f in (lst if isinstance(lst, list) else []):
        if not isinstance(f, dict):
            continue
        num = str(f.get("number", "") or "")
        fav = {"name": str(f.get("name", "") or "") if num else "", "number": num}
        if num and f.get("tones"):
            fav["tones"] = str(f["tones"])
        out.append(fav)
        if len(out) == PHONE_FAV_COUNT:
            break
    while len(out) < PHONE_FAV_COUNT:
        out.append({"name": "", "number": ""})
    return out

def _phone_merge_favs(target: List[dict], extra: List[dict]) -> List[dict]:
    out = [dict(f) for f in target]
    have = {f.get("number") for f in out if f.get("number")}
    for f in extra:
        num = f.get("number")
        if not num or num in have:
            continue
        slot = next((i for i, g in enumerate(out) if not g.get("number")), None)
        if slot is None:
            log.warning("phone: no free favorite slot for %s — not moved", num)
            continue
        out[slot] = dict(f)
        have.add(num)
    return out

def _phone_active_net(doc: dict) -> Optional[dict]:
    return next((n for n in doc.get("networks", []) if n.get("id") == doc.get("active")), None)

def _phone_fav_home(doc: dict) -> Optional[dict]:
    nets = doc.get("networks", [])
    return _phone_active_net(doc) or (nets[0] if nets else None)

def _phone_fav_public(favs: List[dict]) -> List[dict]:
    return [{"name": str(f.get("name", "")), "number": str(f.get("number", "")),
             "has_tones": bool(f.get("tones"))} for f in favs]

def _phone_tone_mode(n: dict) -> str:
    m = str((n or {}).get("tone_mode", "") or "").strip()
    return m if m in PHONE_TONE_MODES else _PHONE_TONE_MODE_DEF

def _phone_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())[:12] or "net"

_PHONE_NODE_MIN, _PHONE_NODE_MAX = 1000, 1999

def _phone_node_ok(v) -> bool:
    v = str(v or "")
    return v.isdigit() and _PHONE_NODE_MIN <= int(v) <= _PHONE_NODE_MAX

def _phone_reserved_nodes() -> Set[str]:
    r = {str(_cfg.asl_node)}
    for i, nd in enumerate(_cfg.bridge_nodes):
        if nd and i != BRIDGE_SLOT_PHONE:
            r.add(nd)
    return r

def _phone_hand_nodes() -> Set[str]:
    try:
        txt = _ph_strip(_ph_read(_ph_path("rpt.conf")) or "")
    except Exception:
        return set()
    live = "\n".join(l for l in txt.splitlines() if not l.lstrip().startswith(";"))
    return set(re.findall(r"^\s*\[(\d+)\]", live, re.M))

def _phone_next_free(taken: Set[str]) -> str:
    base = _phone_node()
    start = int(base) if _phone_node_ok(base) else int(PHONE_NODE)
    span = _PHONE_NODE_MAX - _PHONE_NODE_MIN + 1
    for k in range(span):
        c = str(_PHONE_NODE_MIN + (start - _PHONE_NODE_MIN + k) % span)
        if c not in taken:
            return c
    return ""

def _phone_assign_nodes(nets: List[dict], hand: Optional[Set[str]] = None) -> bool:
    bad = _phone_reserved_nodes()
    used: Set[str] = set()
    before = [str(n.get("node", "") or "") for n in nets]
    for n in nets:
        v = str(n.get("node", "") or "").strip()
        if _phone_node_ok(v) and v not in bad and v not in used:
            n["node"] = v
            used.add(v)
        else:
            if v:
                log.warning("phone: %s node %s can't be used -- giving it a new one", n.get("name", "?"), v)
            n["node"] = ""
    if not all(n["node"] for n in nets):
        if hand is None:
            hand = _phone_hand_nodes()
        for n in nets:
            if not n["node"]:
                n["node"] = _phone_next_free(used | bad | set(hand))
                used.add(n["node"])
    return [n["node"] for n in nets] != before

def _phone_on() -> bool:
    try:
        return bool(_phone_doc().get("activated"))
    except Exception:
        return False

def _phone_net_node(n: Optional[dict]) -> str:
    return str((n or {}).get("node") or "") or _phone_node()

def _phone_live_node(doc: Optional[dict] = None) -> str:
    doc = doc if doc is not None else _phone_doc()
    net = _phone_active_net(doc)
    return _phone_net_node(net) if net else _phone_node()

def _phone_all_nodes(doc: Optional[dict] = None) -> List[str]:
    doc = doc if doc is not None else _phone_doc()
    out = [n["node"] for n in doc.get("networks", []) if n.get("node")]
    if _phone_node() not in out:
        out.append(_phone_node())
    return out

def _phone_public(doc: dict) -> dict:
    nets = []
    for n in doc.get("networks", []):
        pub = {k: v for k, v in n.items() if k not in ("password", "pin", "voicemail_pin")}
        pub["has_password"] = bool(n.get("password"))
        pub["has_pin"]      = bool(n.get("pin"))
        pub["has_voicemail_pin"] = bool(n.get("voicemail_pin"))
        pub["type_label"]   = _PHONE_TYPE_LBL.get(n.get("type", ""), "")
        if n.get("type") in _PHONE_SIP_TYPES:
            pub["tone_mode"] = _phone_tone_mode(n)
        pub["favorites"]    = _phone_fav_public(n.get("favorites", []))
        nets.append(pub)
    return {
        "networks":      nets,
        "active":        doc.get("active", ""),
        "patch_enabled": bool(doc.get("patch_enabled", True)),
        "dialtime":      doc.get("dialtime", _PHONE_DIALTIME_DEF),
        "simplex":       dict(doc.get("simplex", _PHONE_SIMPLEX_DEF)),
        "hangtime":      doc.get("hangtime", ""),
        "signin_mode":   _phone_signin_mode(doc),
        "tot_phone_off": doc.get("tot_phone_off", True) is not False,
        "tot_cap_min":   doc.get("tot_cap_min", 15),
        "tone_path":     doc.get("tone_path", _PHONE_TONE_PATH_DEF),
        "hoip_link":     _hl_public(doc),
        "node":          _cfg.bridge_nodes[BRIDGE_SLOT_PHONE],
        "live_node":     _phone_live_node(doc),
        "activated":     bool(doc.get("activated")),
        "max_networks":  PHONE_MAX_NETS,
        "iax_port":      _iax_bindport(),
    }

def _phone_clean_number(v, limit: int = 20) -> Optional[str]:
    v = str(v or "").strip().replace(" ", "").replace("-", "")
    if not v:
        return ""
    if not _PHONE_DIGITS_RE.match(v) or len(v) > limit:
        return None
    return v

def _phone_validate_net(raw: dict, old: Optional[dict]) -> Tuple[Optional[dict], Optional[str]]:
    name = _clip_label(_sf(raw, "name"), 24)
    if not name:
        return None, "Every phone network needs a name"
    ntype = str(raw.get("type", "")).strip()
    if ntype not in PHONE_TYPES:
        return None, f"{name}: type must be SIP with login, SIP by IP address, Hams Over IP, AmateurWire or IAX2"
    hoip = ntype in _PHONE_EXT_TYPES
    awire = ntype == "awire"
    host = _strip_ctrl(str(raw.get("host", "")).strip())
    if hoip and not host:
        host = _AWIRE_DEFAULT_HOST if awire else _HOIP_DEFAULT_HOST
    if not host or not _HOST_RE.match(host):
        return None, f"{name}: server must be a host name or IP address"
    port = str(raw.get("port", "")).strip()
    if hoip and not port:
        port = _AWIRE_DEFAULT_PORT if awire else _HOIP_DEFAULT_PORT
    if port:
        if not port.isdigit() or not (1 <= int(port) <= 65535):
            return None, f"{name}: port must be 1–65535"
        port = str(int(port))
    out = {"name": name, "type": ntype, "host": host, "port": port}
    pnode = str(raw.get("node", "")).strip() if "node" in raw else str((old or {}).get("node", "") or "")
    if pnode:
        if not _phone_node_ok(pnode):
            return None, f"{name}: node number must be {_PHONE_NODE_MIN}–{_PHONE_NODE_MAX} (a private node), or blank"
        if pnode in _phone_reserved_nodes():
            return None, f"{name}: node {pnode} is your radio node or another bridge — pick another number"
    out["node"] = pnode
    hx: dict = {}
    if hoip:
        ext = _phone_clean_number(raw.get("extension", ""), 10)
        if ext is None:
            return None, f"{name}: extension must be digits only"
        call = _strip_ctrl(str(raw.get("callsign", "")).strip()).upper()
        if call and not _HOIP_CALLSIGN_RE.match(call):
            return None, f"{name}: callsign can use letters, digits, / and - (3 to 12 characters)"
        mail = _strip_ctrl(str(raw.get("email", "")).strip())
        if mail and (len(mail) > 120 or not _HOIP_EMAIL_RE.match(mail)):
            return None, f"{name}: email address is not valid"
        transport = str(raw.get("transport", "udp")).strip().lower() or "udp"
        if transport != "udp":
            return None, f"{name}: only UDP transport is supported"
        aid = _strip_ctrl(str(raw.get("auth_id", "")).strip())
        if aid and not _HOIP_USER_RE.match(aid):
            return None, f"{name}: authentication ID can use letters, digits and . _ @ - only"
        vbox = _strip_ctrl(str(raw.get("voicemail", "")).strip())
        if vbox and not _HOIP_USER_RE.match(vbox):
            return None, f"{name}: voicemail can use letters, digits and . _ @ - only"
        vacc = _strip_ctrl(str(raw.get("voicemail_access", "")).strip())
        if vacc and not _HOIP_VMACCESS_RE.match(vacc):
            return None, f"{name}: voicemail access must be digits, * or # (up to 8)"
        url = _strip_ctrl(str(raw.get("login_url", "")).strip())
        if url and (len(url) > 300 or not _HOIP_URL_RE.match(url)):
            return None, f"{name}: website login link must start with https://"
        vpin = str(raw.get("voicemail_pin", "")).strip()
        if vpin and not (vpin.isdigit() and 4 <= len(vpin) <= 10):
            return None, f"{name}: voicemail PIN must be 4 to 10 digits"
        if not vpin and old:
            vpin = old.get("voicemail_pin", "")
        hx = {"callsign": call, "email": mail, "extension": ext, "transport": "udp",
              "voicemail": vbox, "voicemail_access": vacc, "login_url": url,
              "voicemail_pin": vpin}
        if awire:
            dname = _strip_ctrl(str(raw.get("display_name", "")).strip())
            if dname and not _AWIRE_NAME_RE.match(dname):
                return None, f"{name}: display name can use letters, digits, spaces and . / - (up to 40)"
            dmr = str(raw.get("dmr_id", "")).strip()
            if dmr and not (dmr.isdigit() and 6 <= len(dmr) <= 7):
                return None, f"{name}: DMR ID must be 6 or 7 digits"
            hx.update(display_name=dname, dmr_id=dmr)
    if ntype in ("sip", "hoip", "awire", "iax2"):
        user = _strip_ctrl(str(raw.get("username", "")).strip())
        if hoip and not user:
            user = hx.get("extension", "")
        if not user or not re.match(r"^[A-Za-z0-9._@\-]{1,64}$", user):
            return None, f"{name}: username is required (letters, digits and . _ @ - only)"
        pw = str(raw.get("password", ""))
        if _has_ctrl_chars(pw) or len(pw) > 128 or ";" in pw:
            return None, f"{name}: password can't contain a semicolon or control characters"
        if ntype == "iax2" and re.search(r"[@:\s]", pw):
            return None, f"{name}: an IAX2 password can't contain @, : or spaces"
        if not pw and old:
            pw = old.get("password", "")
        if not pw:
            return None, f"{name}: password is required"
        out.update(username=user, password=pw, register=bool(raw.get("register", True)))
        if hoip:
            hx["auth_id"] = aid or user
    else:
        out.update(username="", password="", register=False)
    cid = _phone_clean_number(str(raw.get("caller_id", "")).replace("+", ""), 15)
    if cid is None:
        return None, f"{name}: caller ID must be digits only"
    out["caller_id"] = cid or (hx.get("extension", "") if hoip else "")
    dialing = str(raw.get("dialing", "ext" if hoip else "phone")).strip()
    if dialing not in PHONE_DIALING:
        return None, f"{name}: dialing must be phone numbers or extensions"
    out["dialing"]    = dialing
    dfmt = str(raw.get("dial_format", "10")).strip()
    if dfmt not in ("10", "1", "+1"):
        return None, f"{name}: number format must be 10 digits, 1 + 10 digits, or +1 + 10 digits"
    out["dial_format"] = dfmt
    out["allow_intl"] = bool(raw.get("allow_intl", False)) and dialing == "phone"
    out["e911"]       = bool(raw.get("e911", False)) and dialing == "phone"
    incoming = str(raw.get("incoming", "off")).strip()
    if incoming not in PHONE_INCOMING:
        return None, f"{name}: incoming calls must be Hang up, Ask for a PIN, or Answer (no PIN)"
    out["incoming"] = incoming
    pin = str(raw.get("pin", "")).strip()
    if pin and not (pin.isdigit() and 4 <= len(pin) <= 8):
        return None, f"{name}: PIN must be 4 to 8 digits"
    if not pin and old:
        pin = old.get("pin", "")
    if incoming == "pin" and not pin:
        return None, f"{name}: incoming calls with a PIN need a PIN (4 to 8 digits)"
    out["pin"] = pin
    trusted_raw = raw.get("trusted", [])
    if isinstance(trusted_raw, str):
        trusted_raw = re.split(r"[,\s]+", trusted_raw)
    trusted = []
    for t in trusted_raw:
        t = _phone_clean_number(str(t).replace("+", ""), 15)
        if t is None:
            return None, f"{name}: trusted numbers must be digits only"
        if t:
            trusted.append(t[-10:])
    out["trusted"] = list(dict.fromkeys(trusted))[:10]
    did = _phone_clean_number(str(raw.get("did", "")).replace("+", ""), 15)
    if did is None:
        return None, f"{name}: your phone number must be digits only"
    out["did"] = did
    lan = str(raw.get("lan_net", "")).strip()
    if lan:
        try:
            lan = str(ipaddress.ip_network(lan, strict=False))
        except ValueError:
            return None, f"{name}: home network must look like 192.168.1.0/24"
    out["lan_net"] = lan
    wan = str(raw.get("wan_ip", "")).strip()
    if wan:
        try:
            wan = str(ipaddress.ip_address(wan))
        except ValueError:
            return None, f"{name}: public IP address is not valid"
    out["wan_ip"] = wan
    btns_raw = raw.get("buttons", (old or {}).get("buttons", []))
    if not isinstance(btns_raw, list):
        return None, f"{name}: tone buttons must be a list"
    btns = []
    for j, b in enumerate(btns_raw[:PHONE_TONE_BTNS]):
        if not isinstance(b, dict):
            continue
        tones = _phone_clean_tones(b.get("tones", ""))
        if tones is None:
            return None, f"{name}: tone button {j+1} can only use 0-9, *, # and commas (up to 32)"
        if tones:
            btns.append({"label": _clip_label(_sf(b, "label"), 10) or tones[:10], "tones": tones})
    out["buttons"] = btns
    tnum = _strip_ctrl(str(raw.get("test_number", "")).strip()).replace(" ", "").replace("-", "")
    if tnum and not _PHONE_TEST_RE.match(tnum):
        return None, f"{name}: test number can only use digits, * and # (up to 20)"
    out["test_number"] = tnum
    if ntype in _PHONE_SIP_TYPES:
        tm = str(raw.get("tone_mode", (old or {}).get("tone_mode", ""))).strip() or \
            (_HOIP_TONE_MODE if ntype == "hoip" else _PHONE_TONE_MODE_DEF)
        if tm not in PHONE_TONE_MODES:
            return None, f"{name}: pick a tone mode from the list"
        out["tone_mode"] = tm
    out.update(hx)
    return out, None

def _hl_default_node() -> str:
    return _phone_node()

def _hl_node_choices() -> List[List[str]]:
    ph, radio = _phone_node(), str(_cfg.asl_node or "")
    owner = next((n for n in _phone_doc().get("networks", []) if n.get("node") == ph), None)
    when = f"the Phone tab is open with {owner['name']} picked" if owner else "the Phone tab is open"
    out = [[ph, f"Phone Bridge {ph} (default; reaches the radio only while {when})"]]
    if radio and radio not in ("0", ph):
        out.append([radio, f"Radio node {radio} (see warning)"])
    return out

def _hl_node(hl: dict) -> str:
    n = str((hl or {}).get("node", "") or "")
    return n if n in {c[0] for c in _hl_node_choices()} else _hl_default_node()

def _hl_ready(doc: dict) -> bool:
    hl = doc.get("hoip_link") or {}
    return bool(hl.get("enabled") and hl.get("username") and hl.get("password"))

_iax_port_cache: list = [0.0, "4569"]

def _iax_bindport() -> str:
    now = time.monotonic()
    if now - _iax_port_cache[0] < 30.0:
        return _iax_port_cache[1]
    base = Path("/etc/asterisk")
    port = "4569"
    def scan(path: Path, depth: int) -> Optional[str]:
        try:
            txt = path.read_text(errors="replace")
        except OSError:
            return None
        sec, found = "", None
        for raw in txt.splitlines():
            ln = raw.split(";", 1)[0].strip()
            m = re.match(r'^#(?:try)?include\s+"?([^"\s]+)"?', ln)
            if m and depth < 2:
                for inc in sorted(_glob.glob(str(base / m.group(1)) if not m.group(1).startswith("/") else m.group(1))):
                    r = scan(Path(inc), depth + 1)
                    if r and sec in ("", "general"):
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
    p = scan(base / "iax.conf", 0)
    if p and 1 <= int(p) <= 65535:
        port = p
    _iax_port_cache[0], _iax_port_cache[1] = now, port
    return port

def _hl_public(doc: dict) -> dict:
    hl = dict(doc.get("hoip_link") or _HL_DEFAULT)
    node = _hl_node(hl)
    return {"enabled": bool(hl.get("enabled")), "username": hl.get("username", ""),
            "fqdn": hl.get("fqdn", ""), "port": hl.get("port") or _iax_bindport(), "node": node,
            "has_password": bool(hl.get("password")), "choices": _hl_node_choices(),
            "dial_hint": (f"IAX2/{hl.get('username')}:********@{hl.get('fqdn')}:{hl.get('port') or _iax_bindport()}/{node}"
                          if hl.get("username") and hl.get("fqdn") else "")}

def _iax_foreign_sections() -> Set[str]:
    txt = _ph_strip(_ph_read(_ph_path("iax.conf")) or "")
    return {m.strip().lower() for m in re.findall(r"^\s*\[([^\]]+)\]", txt, re.M)}

def _hl_validate(raw, cur: dict, net_ids: Set[str]) -> Tuple[Optional[dict], Optional[str]]:
    old = dict(cur.get("hoip_link") or _HL_DEFAULT)
    if raw is None:
        return old, None
    if not isinstance(raw, dict):
        return None, "HOIP AllStar Link settings must be an object"
    out = {"enabled": bool(raw.get("enabled", False))}
    user = _strip_ctrl(str(raw.get("username", "")).strip())
    if user and not _HL_USER_RE.match(user):
        return None, "HOIP AllStar Link: username is 3-32 letters, numbers, - or _ (starting with a letter or number)"
    if user and (user.lower() in _iax_foreign_sections() or user.lower() in {i.lower() for i in net_ids}):
        return None, f"HOIP AllStar Link: '{user}' is already used in iax.conf — pick another username"
    pw = str(raw.get("password", ""))
    if pw:
        if not _HL_PASS_RE.match(pw):
            return None, ("HOIP AllStar Link: password is 8-64 characters — letters, numbers and . _ - + = ! % ^ * ~ "
                          "(no : @ / or ;)")
    else:
        pw = old.get("password", "") if user and user == old.get("username") else ""
    fqdn = _strip_ctrl(str(raw.get("fqdn", "")).strip().rstrip(".")).lower()
    if fqdn:
        try:
            ipaddress.ip_address(fqdn)
            return None, "HOIP AllStar Link: HOIP needs an internet name (like kd8pgk.ddns.net), not an IP address"
        except ValueError:
            pass
        if not _HOST_RE.match(fqdn) or "." not in fqdn:
            return None, "HOIP AllStar Link: the internet name doesn't look right (like kd8pgk.ddns.net)"
    port = str(raw.get("port", "") or _iax_bindport()).strip()
    if not port.isdigit() or not (1 <= int(port) <= 65535):
        return None, f"HOIP AllStar Link: port must be a number (normally {_iax_bindport()})"
    node = str(raw.get("node", "") or "").strip()
    if node and node not in {c[0] for c in _hl_node_choices()}:
        return None, "HOIP AllStar Link: pick the node from the list"
    if out["enabled"] and not (user and pw and fqdn):
        return None, "HOIP AllStar Link: fill in username, password and internet name, or untick 'Turn on'"
    out.update(username=user, password=pw, fqdn=fqdn, port=port, node=node or _hl_default_node())
    return out, None

def _phone_validate(raw: dict) -> Tuple[Optional[dict], Optional[str]]:
    if not isinstance(raw, dict):
        return None, "Phone settings must be an object"
    cur = _phone_load()
    old_by_id = {n.get("id"): n for n in cur["networks"]}
    nets_raw = raw.get("networks", cur["networks"])
    if not isinstance(nets_raw, list) or len(nets_raw) > PHONE_MAX_NETS:
        return None, f"Up to {PHONE_MAX_NETS} phone networks are allowed"
    nets, used_ids, names = [], set(), set()
    for r in nets_raw:
        if not isinstance(r, dict):
            return None, "Bad phone network entry"
        rid = str(r.get("id", "")).strip()
        old = old_by_id.get(rid) if rid else None
        net, err = _phone_validate_net(r, old)
        if err:
            return None, err
        if net["name"].lower() in names:
            return None, f"Two phone networks are called '{net['name']}'"
        names.add(net["name"].lower())
        if old:
            nid = old["id"]
        else:
            base = "dvs" + _phone_slug(net["name"])
            nid, i = base, 1
            while nid in used_ids or nid in old_by_id:
                i += 1
                nid = f"{base}{i}"
        used_ids.add(nid)
        net["id"] = nid
        old_favs = (old or {}).get("favorites") or _phone_norm_favs([])
        if "favorites" in r:
            favs, err = _phone_clean_favs(r["favorites"], old_favs, net["name"])
            if err:
                return None, err
            net["favorites"] = favs
        else:
            net["favorites"] = _phone_norm_favs(old_favs)
        nets.append(net)
    hand = _phone_hand_nodes()
    seen: Dict[str, str] = {}
    for net in nets:
        v = net.get("node", "")
        if not v:
            continue
        if v in seen:
            return None, f"{seen[v]} and {net['name']} both use node {v} — each network needs its own"
        if v in hand:
            return None, (f"{net['name']}: rpt.conf already has a [{v}] the dashboard didn't write — "
                          f"pick another node number (or blank for the next free one)")
        seen[v] = net["name"]
    _phone_assign_nodes(nets, hand)
    if any(not n["node"] for n in nets):
        return None, f"No free private node numbers left ({_PHONE_NODE_MIN}–{_PHONE_NODE_MAX})"
    active = str(raw.get("active", cur.get("active", ""))).strip()
    if active not in {n["id"] for n in nets}:
        active = nets[0]["id"] if nets else ""
    try:
        dialtime = int(raw.get("dialtime", cur.get("dialtime", _PHONE_DIALTIME_DEF)))
    except (ValueError, TypeError):
        return None, "Dial timeout must be a number of milliseconds"
    if not (_PHONE_DIALTIME_MIN <= dialtime <= _PHONE_DIALTIME_MAX):
        return None, f"Dial timeout must be {_PHONE_DIALTIME_MIN}–{_PHONE_DIALTIME_MAX} ms"
    legacy = [f for f in cur.get("favorites", []) if f.get("number")]
    if legacy and nets:
        home = next((n for n in nets if n["id"] == active), None) or nets[0]
        home["favorites"] = _phone_merge_favs(home["favorites"], legacy)
        legacy = []
    sx_raw = raw.get("simplex", cur.get("simplex", _PHONE_SIMPLEX_DEF))
    if not isinstance(sx_raw, dict):
        return None, "Simplex settings must be an object"
    sx = {"enabled": bool(sx_raw.get("enabled", False))}
    labels = {"voxtimeout": "VOX timeout", "voxrecover": "VOX recovery",
              "patchdelay": "Radio delay", "phonedelay": "Phone delay"}
    for k, (lo, hi) in _PHONE_SIMPLEX_RANGE.items():
        try:
            v = int(sx_raw.get(k, _PHONE_SIMPLEX_DEF[k]))
        except (ValueError, TypeError):
            return None, f"{labels[k]} must be a number"
        if not (lo <= v <= hi):
            return None, f"{labels[k]} must be {lo}–{hi}"
        sx[k] = v
    hl, err = _hl_validate(raw.get("hoip_link"), cur, {n["id"] for n in nets})
    if err:
        return None, err
    smode = str(raw.get("signin_mode", cur.get("signin_mode", "picked"))).strip()
    if smode not in ("picked", "all"):
        return None, "Sign-in must be 'picked' or 'all'"
    tot_off = raw.get("tot_phone_off", cur.get("tot_phone_off", True)) is not False
    try:
        tot_cap = int(str(raw.get("tot_cap_min", cur.get("tot_cap_min", 15))).strip() or 15)
    except ValueError:
        return None, "Safety cap must be a number of minutes"
    if not 5 <= tot_cap <= 60:
        return None, "Safety cap must be 5–60 minutes"
    hang = str(raw.get("hangtime", cur.get("hangtime", ""))).strip()
    if hang:
        if not hang.isdigit() or not (0 <= int(hang) <= 10000):
            return None, "Hang time must be 0–10000 ms (or blank for the default)"
        hang = str(int(hang))
    out = {
        "networks":      nets,
        "active":        active,
        "patch_enabled": bool(raw.get("patch_enabled", cur.get("patch_enabled", True))),
        "dialtime":      dialtime,
        "simplex":       sx,
        "tone_path":     cur.get("tone_path", _PHONE_TONE_PATH_DEF),
        "tone_path_user": bool(cur.get("tone_path_user")),
        "hoip_link":     hl,
        "hangtime":      hang,
        "signin_mode":   smode,
        "tot_phone_off": tot_off,
        "tot_cap_min":   tot_cap,
        "activated":     bool(cur.get("activated")),
    }
    if legacy:
        out["favorites"] = _phone_norm_favs(legacy)
    return out, None

def _phone_clean_favs(favs_raw, old_favs: List[dict], where: str) -> Tuple[Optional[List[dict]], Optional[str]]:
    pfx = f"{where}: favorite" if where else "Favorite"
    if not isinstance(favs_raw, list):
        return None, f"{where + ': ' if where else ''}favorites must be a list"
    favs = []
    for i in range(PHONE_FAV_COUNT):
        f = favs_raw[i] if i < len(favs_raw) and isinstance(favs_raw[i], dict) else {}
        num = _phone_clean_number(f.get("number", ""))
        if num is None:
            return None, f"{pfx} {i+1}: the number must be digits only (up to 20)"
        nm = _clip_label(_sf(f, "name"), 24)
        tn = _phone_clean_tones(f.get("tones", ""))
        if tn is None:
            return None, f"{pfx} {i+1}: 'then send' can only use 0-9, *, # and commas (up to 32)"
        oldf = old_favs[i] if i < len(old_favs) else {}
        if f.get("tones_clear"):
            tn = ""
        elif not tn and num and oldf.get("number") == num:
            tn = str(oldf.get("tones", ""))
        fav = {"name": nm if num else "", "number": num}
        if num and tn:
            fav["tones"] = tn
        favs.append(fav)
    return favs, None

def _phone_write(doc: dict) -> Tuple[bool, str]:
    try:
        Path(PHONE_CONF).parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(Path(PHONE_CONF), json.dumps(doc, indent=1, sort_keys=True) + "\n")
        _phone_doc_cache[0] = 0.0
        return True, "Saved"
    except Exception as e:
        return False, f"Write failed: {e}"

def action_get_phone() -> dict:
    doc = _phone_load()
    d = _phone_public(doc)
    d["router_note"] = _phone_router_advice(doc)
    return d

def action_save_phone(raw: dict) -> Tuple[bool, str]:
    with _phone_lock:
        old_live = _phone_live_node(_phone_load())
        doc, err = _phone_validate(raw)
        if err:
            return False, err
        new_live = _phone_live_node(doc)
        if old_live != new_live and _phone_call_state(0.0).get("state") != "idle":
            return False, "Hang up first — this changes which node the picked network uses"
        ok, msg = _phone_write(doc)
        if not ok:
            return False, msg
    _phone_relink(old_live, new_live)
    return True, (f"Saved {len(doc['networks'])} phone network"
                  f"{'' if len(doc['networks']) == 1 else 's'}")

_phone_signin_job: dict = {"id": "", "started": 0.0, "error": ""}
_PHONE_SIGNIN_WAIT = 30.0

def _phone_switch_signin(old_doc: dict, new_id: str) -> None:
    try:
        old_id = _phone_signin_id(old_doc)
        old = next((n for n in old_doc["networks"] if n["id"] == old_id), None)
        if old is not None and old["type"] in _PHONE_LOGIN_SIP:
            ami_command(f"pjsip send unregister {old_id}-reg", timeout=6)
            time.sleep(1.0)
        ok, msg = action_phone_apply(False)
        if not ok:
            _phone_signin_job["error"] = msg
            log.warning("phone: sign-in switch failed: %s", msg)
            return
        doc = _phone_load()
        new = next((n for n in doc["networks"] if n["id"] == new_id), None)
        if new is not None and new["type"] in _PHONE_LOGIN_SIP and _phone_signs_in(doc, new):
            ami_command(f"pjsip send register {new_id}-reg", timeout=6)
        _phone_reg_cache[0] = 0.0
        log.info("phone: sign-in moved %s -> %s", old_id or "(none)", new_id)
    except Exception as e:
        _phone_signin_job["error"] = str(e)
        log.warning("phone: sign-in switch failed: %s", e)

def _phone_relink(old_node: str, new_node: str) -> None:
    if not old_node or old_node == new_node or not _phone_on():
        return
    st = get_state_fields("page", "has_asl")
    if st["page"] != "PHONE" or not st["has_asl"]:
        return

    def go():
        if not _link_enter(timeout=30):
            log.warning("phone: link move %s -> %s left to the watchdog (busy)", old_node, new_node)
            return
        try:
            if get_state_fields("page")["page"] != "PHONE":
                return
            linked = _query_linked_nodes() or []
            if old_node in linked:
                _drop_one_link(old_node)
                time.sleep(0.3)
            if new_node and new_node not in linked:
                _connect(new_node)
            _bridge_slot_last_reconnect[BRIDGE_SLOT_PHONE] = time.monotonic()
            _bridge_slot_down_polls[BRIDGE_SLOT_PHONE] = 0
            log.info("phone: link moved from node %s to %s", old_node, new_node)
        finally:
            _link_exit()
    threading.Thread(target=go, name="phone-relink", daemon=True).start()

def action_phone_select(net_id: str) -> Tuple[bool, str]:
    with _phone_lock:
        doc = _phone_load()
        net = next((n for n in doc["networks"] if n.get("id") == net_id), None)
        if net is None:
            return False, "Unknown phone network"
        old_node, new_node = _phone_live_node(doc), _phone_net_node(net)
        if old_node != new_node and _phone_call_state(0.0).get("state") != "idle":
            return False, "Hang up first — each network has its own node, and the call is on this one"
        moving = (doc.get("activated") and _phone_signin_mode(doc) == "picked" and doc["active"] != net_id
                  and _phone_signin_id(doc) != (net_id if net.get("register") else ""))
        if moving and _phone_call_state().get("state") != "idle":
            return False, "Hang up first — the sign-in can't move during a call"
        old_doc = json.loads(json.dumps(doc))
        if doc["active"] != net_id:
            doc["active"] = net_id
            ok, msg = _phone_write(doc)
            if not ok:
                return False, msg
    _phone_astdb("put", "active", net_id)
    _phone_relink(old_node, new_node)
    if moving and _svc_is_active("asterisk"):
        _phone_signin_job.update(id=net_id if net.get("register") else "", started=time.monotonic(), error="")
        threading.Thread(target=_phone_switch_signin, args=(old_doc, net_id), daemon=True).start()
        if net.get("register"):
            return True, f"Phone network: {net['name']} — signing in…"
        return True, f"Phone network: {net['name']} (its Sign in box is off, so nothing signs in)"
    return True, f"Phone network: {net['name']}"

def action_save_phone_favorite(number: str, name: str = "") -> Tuple[bool, str]:
    num = _phone_clean_number(number)
    if not num:
        return False, "Type a number to save (digits only, up to 20)"
    with _phone_lock:
        doc = _phone_load()
        net = _phone_active_net(doc)
        if net is None:
            return False, "Pick a phone network first"
        favs = net["favorites"]
        for i, f in enumerate(favs):
            if f.get("number") == num:
                return True, f"{num} is already in favorites on {net['name']} (slot {i+1})"
        for i, f in enumerate(favs):
            if not f.get("number"):
                label = _clip_label(_sf({"n": name}, "n"), 24) or num
                favs[i] = {"name": label, "number": num}
                ok, msg = _phone_write(doc)
                if not ok:
                    return False, msg
                return True, f"Saved {label} to {net['name']} favorite slot {i+1}"
    return False, f"All 10 favorite slots on {net['name']} are in use — free one on the Edit page"


AST_DIR       = "/etc/asterisk"
HANGUP_SCRIPT = "/var/lib/asterisk/dvs_phone_hangup"
TONECODE_SCRIPT = "/var/lib/asterisk/dvs_phone_tonecode"
_TONE_REQ_DIR   = "/run/asl_dvs_tones/req"
_TONE_CODE_PFX  = "98"
_TONE_CODE_FIXED = {"0": ("*", "*"), "1": ("#", "#"), "2": ("*99", "*99")}
_PH_BEGIN     = "; >>> dvs-phone (managed by asl_dvs_dashboard - edits inside are overwritten) >>>"
_PH_END       = "; <<< dvs-phone <<<"
_PH_BLOCK_RE  = re.compile(re.escape(_PH_BEGIN) + r".*?" + re.escape(_PH_END) + r"\n?\n?", re.S)
_PH_OWN_HDR = "; asl_dvs_dashboard - "
_PH_OWNED = {"ext": "dvs_phone_extensions.conf", "pjsip": "dvs_phone_pjsip.conf",
             "iax_reg": "dvs_phone_iax_reg.conf", "iax": "dvs_phone_iax.conf"}
_PH_MODULES = (
    "bridge_builtin_features.so", "bridge_builtin_interval_features.so", "bridge_holding.so",
    "bridge_native_rtp.so", "bridge_simple.so", "bridge_softmix.so", "chan_bridge_media.so",
    "app_verbose.so", "app_read.so",
    "func_callerid.so",
    "app_senddtmf.so",
    "app_chanspy.so", "app_playback.so", "format_pcm.so")
_PH_PJSIP_MODULES = (
    "chan_pjsip.so", "func_pjsip_endpoint.so", "func_sorcery.so", "func_devstate.so",
    "res_pjproject.so", "res_pjsip_acl.so", "res_pjsip_authenticator_digest.so",
    "res_pjsip_caller_id.so", "res_pjsip_diversion.so", "res_pjsip_dtmf_info.so",
    "res_pjsip_endpoint_identifier_anonymous.so", "res_pjsip_endpoint_identifier_ip.so",
    "res_pjsip_endpoint_identifier_user.so", "res_pjsip_exten_state.so",
    "res_pjsip_header_funcs.so", "res_pjsip_logger.so", "res_pjsip_messaging.so",
    "res_pjsip_nat.so", "res_pjsip_notify.so", "res_pjsip_outbound_authenticator_digest.so",
    "res_pjsip_outbound_registration.so", "res_pjsip_path.so", "res_pjsip_pubsub.so",
    "res_pjsip_refer.so", "res_pjsip_registrar.so", "res_pjsip_rfc3326.so",
    "res_pjsip_sdp_rtp.so", "res_pjsip_session.so", "res_pjsip.so", "res_rtp_asterisk.so",
    "res_sorcery_astdb.so", "res_sorcery_config.so", "res_sorcery_memory.so",
    "res_sorcery_realtime.so")
_PH_BLOCKED = ("_1800NXXXXXX", "_1888NXXXXXX", "_1877NXXXXXX", "_1866NXXXXXX", "_1855NXXXXXX",
               "_1N00XXXXXXX", "_1N11XXXXXXX", "_1NXX555XXXX", "_1NXX976XXXX",
               "_1809XXXXXXX", "_1900XXXXXXX")

def _ph_path(name: str) -> str:
    return os.path.join(AST_DIR, name)

def _phone_node() -> str:
    return _cfg.bridge_nodes[BRIDGE_SLOT_PHONE] or PHONE_NODE

def _phone_astdb(op: str, key: str, val: str = "") -> bool:
    try:
        cmd = (f"database put dvsphone {key} {val}" if op == "put"
               else f"database del dvsphone {key}")
        return bool(ami_command(cmd, timeout=4)[1])
    except Exception as e:
        log.warning("phone: AstDB %s %s failed: %s", op, key, e)
        return False

def _ph_strip(text: str) -> str:
    return _PH_BLOCK_RE.sub("", text)

def _ph_place(text: str, body: str, where: str = "end") -> str:
    text = _ph_strip(text)
    if not body:
        return text
    blk = _PH_BEGIN + "\n" + body.rstrip("\n") + "\n" + _PH_END + "\n"
    if where.startswith("after:") or where.startswith("before:"):
        kind, _, hdr = where.partition(":")
        m = re.search(r"^\[" + re.escape(hdr.strip("[]")) + r"\][^\n]*\n", text, re.M)
        if m:
            i = m.end() if kind == "after" else m.start()
            return text[:i] + blk + "\n" + text[i:]
    return text.rstrip("\n") + "\n\n" + blk

def _ph_read(path: str) -> Optional[str]:
    try:
        return Path(path).read_text()
    except FileNotFoundError:
        return None

def _ph_remove_owned(path: str) -> bool:
    text = _ph_read(path)
    if text is None:
        return False
    if not text.startswith(_PH_OWN_HDR):
        log.info("phone: left %s alone (not written by the dashboard)", path)
        return False
    try:
        os.unlink(path)
    except FileNotFoundError:
        return False
    log.info("phone: removed unused %s", path)
    return True

def _ph_write(path: str, data: str, mode: int = 0o640) -> None:
    p = Path(path)
    uid = gid = None
    try:
        st = p.stat()
        mode, uid, gid = st.st_mode & 0o7777, st.st_uid, st.st_gid
    except FileNotFoundError:
        try:
            import grp
            gid = grp.getgrnam("asterisk").gr_gid
            uid = 0
        except Exception:
            pass
    else:
        bak = Path(str(p) + ".dvsphone.bak")
        if not bak.exists():
            shutil.copy2(p, bak)
    _atomic_write(p, data)
    try:
        os.chmod(p, mode)
        if uid is not None:
            os.chown(p, uid, gid if gid is not None else -1)
    except (PermissionError, OSError) as e:
        log.warning("phone: could not set owner/mode on %s: %s", p, e)

def _ph_dial(net: dict, numexpr: str) -> str:
    if net["type"] == "iax2":
        return f"IAX2/{net['id']}/{numexpr}"
    return f"PJSIP/{numexpr}@{net['id']}"

def _ph_cid(net: dict) -> List[str]:
    out = [f" same => n,Set(CALLERID(num)={net['caller_id']})"] if net.get("caller_id") else []
    if net.get("display_name"):
        out.append(f" same => n,Set(CALLERID(name)={net['display_name']})")
    return out

def _phone_render_dialplan(doc: dict) -> str:
    L = ["; asl_dvs_dashboard - Phone tab dialplan (rewritten on every apply; do not edit)",
         "", "[dvs-invalid]",
         "exten => s,1,Wait(1)", " same => n,Playback(ss-noservice)", " same => n,Hangup()", "",
         "; Outgoing (autopatch): the live network is read from AstDB 'dvsphone/active'.",
         "[dvs-phone-out]",
         "exten => _X.,1,Set(DVSNET=${DB(dvsphone/active)})",
         " same => n,Set(DVSOPT=)",
         " same => n,GotoIf($[${DB_EXISTS(dvsphone/then)}]?then:net)",
         " same => n(then),Set(DVSOPT=D(${DB_DELETE(dvsphone/then)}))",
         " same => n(net),GotoIf($[\"${DVSNET}\" = \"\"]?bad)",
         " same => n,GotoIf($[\"${DB(dvsphone/patch)}\" = \"0\"]?bad)",
         " same => n,Goto(dvs-net-${DVSNET},${EXTEN},1)",
         " same => n(bad),Goto(dvs-invalid,s,1)",
         "exten => i,1,Goto(dvs-invalid,s,1)", "exten => t,1,Hangup()", "",
         "; Tones as sound (v9.3.16): plays touch-tone recordings, whispered into",
         "; the live call by ChanSpy.  Only the dashboard starts this.",
         "[dvs-tones]",
         "exten => s,1,Answer()",
         " same => n,Wait(0.5)",
         " same => n,Playback(${DVSTONES})",
         " same => n,Wait(0.3)",
         " same => n,Hangup()", ""]
    for n in doc["networks"]:
        nid = n["id"]
        node = _phone_net_node(n)
        L.append(f"; ---- {n['name']} ({_PHONE_TYPE_LBL[n['type']]}) -- node {node} ----")
        L += [f"[dvs-node-{nid}]",
              f"exten => _X.,1,Set(DVSNET={nid})",
              " same => n,Set(DVSOPT=)",
              " same => n,GotoIf($[${DB_EXISTS(dvsphone/then)}]?then:net)",
              " same => n(then),Set(DVSOPT=D(${DB_DELETE(dvsphone/then)}))",
              " same => n(net),GotoIf($[\"${DB(dvsphone/patch)}\" = \"0\"]?bad)",
              f" same => n,Goto(dvs-net-{nid},${{EXTEN}},1)",
              " same => n(bad),Goto(dvs-invalid,s,1)",
              "exten => i,1,Goto(dvs-invalid,s,1)", "exten => t,1,Hangup()", ""]
        test = []
        if n.get("test_number"):
            test = [f"exten => {_PHONE_TEST_ALIAS},1,NoOp(test call)"] + _ph_cid(n)
            test += [f" same => n,Dial({_ph_dial(n, n['test_number'])},60,${{DVSOPT}})", " same => n,Hangup()"]
        if n["dialing"] == "ext":
            L += [f"[dvs-net-{nid}]"] + test
            if n["type"] in _PHONE_EXT_TYPES and n.get("voicemail_access"):
                L += [f"exten => {_HOIP_VM_ALIAS},1,NoOp(voicemail)"] + _ph_cid(n)
                L += [f" same => n,Dial({_ph_dial(n, n['voicemail_access'])},60,${{DVSOPT}})", " same => n,Hangup()"]
            L += ["exten => _X.,1,NoOp(extension call)"]
            L += _ph_cid(n)
            L += [f" same => n,Dial({_ph_dial(n, '${EXTEN}')},60,${{DVSOPT}})", " same => n,Hangup()",
                  "exten => i,1,Goto(dvs-invalid,s,1)", ""]
        else:
            fmt = {"10": "${EXTEN:1}", "1": "${EXTEN}", "+1": "+${EXTEN}"}[n.get("dial_format", "10")]
            L += [f"[dvs-net-{nid}]"] + test
            if n["type"] in _PHONE_EXT_TYPES and n.get("voicemail_access"):
                L += [f"exten => {_HOIP_VM_ALIAS},1,NoOp(voicemail)"] + _ph_cid(n)
                L += [f" same => n,Dial({_ph_dial(n, n['voicemail_access'])},60,${{DVSOPT}})", " same => n,Hangup()"]
            if n.get("e911"):
                L += ["exten => 911,1,NoOp(911 - E911 is set up on this network)"] + _ph_cid(n)
                L += [f" same => n,Dial({_ph_dial(n, '911')},60)", " same => n,Hangup()"]
            L += ["exten => _NXXNXXXXXX,1,Goto(dvs-net-%s-r,1${EXTEN},1)" % nid,
                  "exten => _1NXXNXXXXXX,1,Goto(dvs-net-%s-r,${EXTEN},1)" % nid]
            if n.get("allow_intl"):
                L += ["exten => _011.,1,NoOp(international)"] + _ph_cid(n)
                L += [f" same => n,Dial({_ph_dial(n, '${EXTEN}')},60,${{DVSOPT}})", " same => n,Hangup()"]
            L += ["exten => _X.,1,Goto(dvs-invalid,s,1)", "exten => i,1,Goto(dvs-invalid,s,1)", "",
                  f"[dvs-net-{nid}-r]"]
            for pat in _PH_BLOCKED:
                L.append(f"exten => {pat},1,Goto(dvs-invalid,s,1)")
            L += ["exten => _1NXXNXXXXXX,1,NoOp(dialing)"] + _ph_cid(n)
            L += [f" same => n,Dial({_ph_dial(n, fmt)},60,${{DVSOPT}})", " same => n,Hangup()", ""]
        L.append(f"[dvs-in-{nid}]")
        gate = (f" same => n,GotoIf($[\"${{DB(dvsphone/open)}}\" = \"1\" & "
                f"\"${{DB(dvsphone/active)}}\" = \"{nid}\"]?open)")
        mode = n.get("incoming")
        if mode == "open":
            trusted = [f" same => n,GotoIf($[\"${{CALLERID(num):-10}}\" = \"{t}\"]?connect)"
                       for t in n.get("trusted", [])]
            for pat in ("_[+0-9].", "s"):
                L += [f"exten => {pat},1,NoOp(incoming call from ${{CALLERID(num)}})",
                      gate,
                      " same => n,Busy(20)", " same => n,Hangup()",
                      " same => n(open),NoOp()"]
                if trusted:
                    L += trusted + [" same => n,Busy(20)", " same => n,Hangup()"]
                L += [" same => n(connect),Answer()", " same => n,Wait(1)",
                      " same => n,Playback(rpt/connected)",
                      f" same => n,rpt({node},Pv)", " same => n,Hangup()"]
        elif mode == "pin" and n.get("pin"):
            trusted = [f" same => n,GotoIf($[\"${{CALLERID(num):-10}}\" = \"{t}\"]?connect)"
                       for t in n.get("trusted", [])]
            for pat in ("_[+0-9].", "s"):
                L += [f"exten => {pat},1,NoOp(incoming call from ${{CALLERID(num)}})",
                      gate,
                      " same => n,Busy(20)", " same => n,Hangup()",
                      " same => n(open),NoOp()"]
                L += trusted
                L += [" same => n,Answer()", " same => n,Wait(1)", " same => n,Set(TRIES=0)",
                      " same => n(ask),Read(PIN,beep,8,,1,10)",
                      f" same => n,GotoIf($[\"${{PIN}}\" = \"{n['pin']}\"]?connect)",
                      " same => n,Set(TRIES=$[${TRIES} + 1])",
                      " same => n,GotoIf($[${TRIES} >= 3]?bye)",
                      " same => n,Playback(confbridge-invalid)", " same => n,Goto(ask)",
                      " same => n(bye),Playback(confbridge-pin-bad)", " same => n,Hangup()",
                      " same => n(connect),Answer()", " same => n,Playback(rpt/connected)",
                      f" same => n,rpt({node},Pv)", " same => n,Hangup()"]
        else:
            L += ["exten => _[+0-9].,1,Hangup()", "exten => s,1,Hangup()"]
        L.append("")
    if _hl_ready(doc):
        hn = _hl_node(doc["hoip_link"])
        say = "&".join(["rpt/node"] + [f"digits/{c}" for c in hn] + ["rpt/connected"])
        L += ["; Hams Over IP AllStar Link (incoming only, IAX2)", "[dvs-hoiplink]",
              f"exten => {hn},1,NoOp(HOIP AllStar Link from ${{CALLERID(name)}})",
              " same => n,Answer()", " same => n,Wait(1)", f" same => n,Playback({say})",
              " same => n,Set(CALLERID(name)=HOIP-${CALLERID(name)})",
              f" same => n,rpt({hn},P)", " same => n,Hangup()",
              "exten => i,1,Hangup()", ""]
    return "\n".join(L) + "\n"

def _pjsip_has_transport() -> bool:
    txt = _ph_read(_ph_path("pjsip.conf")) or ""
    txt = _ph_strip(txt)
    return bool(re.search(r"^\s*type\s*=\s*transport", txt, re.M | re.I))

def _pjsip_foreign_transports() -> List[dict]:
    txt = _ph_strip(_ph_read(_ph_path("pjsip.conf")) or "")
    secs: List[dict] = []
    cur: Optional[dict] = None
    for raw in txt.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^\[([^\]]+)\]", line)
        if m:
            cur = {"name": m.group(1).strip(), "keys": {}}
            secs.append(cur)
            continue
        if cur is not None and "=" in line:
            k, v = line.split("=", 1)
            cur["keys"].setdefault(k.strip().lower(), v.strip())
    return [s for s in secs if s["keys"].get("type", "").lower() == "transport"]

def _phone_pi_lan_ip() -> str:
    s = None
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 53))
        return s.getsockname()[0]
    except Exception:
        return ""
    finally:
        if s is not None:
            s.close()

def _phone_router_advice(doc: dict) -> dict:
    sip = [n for n in doc.get("networks", []) if n.get("type") in _PHONE_SIP_TYPES]
    if not sip:
        return {}
    lan = next((n["lan_net"] for n in sip if n.get("lan_net")), "")
    wan = next((n["wan_ip"] for n in sip if n.get("wan_ip")), "")
    ip = _phone_pi_lan_ip()
    try:
        private = bool(ip) and ipaddress.ip_address(ip).is_private
    except ValueError:
        private = False
    try:
        foreign = _pjsip_foreign_transports()
    except Exception:
        foreign = []
    if foreign:
        t = foreign[0]
        if t["keys"].get("external_media_address"):
            return {}
        name = t["name"]
        if lan or wan:
            lines = ([f"local_net={lan}", "local_net=127.0.0.1/32"] if lan else [])
            lines += ([f"external_media_address={wan}", f"external_signaling_address={wan}"] if wan else [])
            return {"text": (f"Your pjsip.conf already has its own connection section [{name}], so the "
                             f"Home network and Public IP entered here aren't used. Add these lines under "
                             f"[{name}] in /etc/asterisk/pjsip.conf, then restart Asterisk:"),
                    "lines": lines}
        if private:
            return {"text": (f"The Pi is on a home network address ({ip}) and your pjsip.conf has its own "
                             f"connection section [{name}]. If the far end can't hear you, fill in Home "
                             f"network and Public IP address below and Save Phone to get the lines to add."),
                    "lines": []}
        return {}
    if private and not (lan and wan):
        return {"text": (f"The Pi is on a home network address ({ip}). If the far end can't hear you, "
                         f"fill in Home network and Public IP address below and Save Phone."),
                "lines": []}
    return {}

def _phone_signin_mode(doc: dict) -> str:
    return "all" if doc.get("signin_mode") == "all" else "picked"

def _phone_signin_id(doc: dict) -> str:
    nets = doc.get("networks") or []
    act = next((n for n in nets if n.get("id") == doc.get("active")), None)
    if act is not None:
        return act["id"] if act.get("register") else ""
    first = next((n for n in nets if n.get("register")), None)
    return first["id"] if first else ""

def _phone_signs_in(doc: dict, n: dict) -> bool:
    if not n.get("register"):
        return False
    return _phone_signin_mode(doc) == "all" or n.get("id") == _phone_signin_id(doc)

def _phone_render_pjsip(doc: dict) -> str:
    sip = [n for n in doc["networks"] if n["type"] in _PHONE_SIP_TYPES]
    L = ["; asl_dvs_dashboard - Phone tab SIP accounts (rewritten on every apply)"]
    if not sip:
        return "\n".join(L + ["; no SIP networks"]) + "\n"
    if not _pjsip_has_transport():
        lan = next((n["lan_net"] for n in sip if n.get("lan_net")), "")
        wan = next((n["wan_ip"] for n in sip if n.get("wan_ip")), "")
        L += ["", "[dvs-transport]", "type=transport", "protocol=udp", "bind=0.0.0.0:5060"]
        if lan:
            L += [f"local_net={lan}", "local_net=127.0.0.1/32"]
        if wan:
            L += [f"external_media_address={wan}", f"external_signaling_address={wan}"]
    for n in sip:
        nid, host = n["id"], n["host"]
        hp = f"{host}:{n['port']}" if n.get("port") else host
        L += ["", f"; ---- {n['name']} ----"]
        if n["type"] in _PHONE_LOGIN_SIP:
            L += [f"[{nid}-auth]", "type=auth", "auth_type=userpass",
                  f"username={n.get('auth_id') or n['username']}", f"password={n['password']}", ""]
            if _phone_signs_in(doc, n):
                L += [f"[{nid}-reg]", "type=registration", f"outbound_auth={nid}-auth",
                      f"server_uri=sip:{hp}", f"client_uri=sip:{n['username']}@{host}",
                      "retry_interval=60", f"contact_user={n['username']}"]
                if n["type"] in _PHONE_EXT_TYPES:
                    L += ["expiration=3600", "line=yes", f"endpoint={nid}"]
                L += [""]
        L += [f"[{nid}]", "type=aor", f"contact=sip:{hp}", "qualify_frequency=60", "",
              f"[{nid}]", "type=endpoint", f"context=dvs-in-{nid}", "disallow=all",
              "allow=ulaw", "allow=alaw", "allow=gsm", f"aors={nid}", "direct_media=no",
              "rtp_symmetric=yes", "force_rport=yes", "rewrite_contact=yes", f"dtmf_mode={_phone_tone_mode(n)}"]
        if n["type"] in _PHONE_LOGIN_SIP:
            L += [f"outbound_auth={nid}-auth", f"from_user={n['username']}", f"from_domain={host}"]
        if n.get("caller_id"):
            L += [f"callerid=\"{n['display_name']}\" <{n['caller_id']}>" if n.get("display_name")
                  else f"callerid=<{n['caller_id']}>"]
        L += ["", f"[{nid}]", "type=identify", f"endpoint={nid}", f"match={host}"]
    return "\n".join(L) + "\n"

def _phone_render_iax(doc: dict) -> Tuple[str, str]:
    iax = [n for n in doc["networks"] if n["type"] == "iax2"]
    reg = ["; asl_dvs_dashboard - Phone tab IAX2 registrations (rewritten on every apply)"]
    peers = ["; asl_dvs_dashboard - Phone tab IAX2 accounts (rewritten on every apply)"]
    for n in iax:
        hp = f"{n['host']}:{n['port']}" if n.get("port") else n["host"]
        if _phone_signs_in(doc, n):
            reg.append(f"register => {n['username']}:{n['password']}@{hp}")
        peers += ["", f"; ---- {n['name']} ----", f"[{n['id']}]", "type=friend",
                  f"username={n['username']}", f"secret={n['password']}", f"host={n['host']}"]
        if n.get("port"):
            peers.append(f"port={n['port']}")
        peers += [f"context=dvs-in-{n['id']}", "disallow=all", "allow=ulaw", "allow=g726aal2",
                  "allow=gsm", "codecpriority=host", "insecure=port,invite",
                  "requirecalltoken=yes", "qualify=yes"]
    if _hl_ready(doc):
        hl = doc["hoip_link"]
        peers += ["", "; ---- Hams Over IP AllStar Link (incoming) ----", f"[{hl['username']}]",
                  f"username={hl['username']}", "type=friend", "context=dvs-hoiplink",
                  "host=dynamic", "auth=md5", f"secret={hl['password']}", "disallow=all",
                  "allow=ulaw", "allow=g726aal2", "allow=gsm", "codecpriority=host",
                  "transfer=no", "requirecalltoken=no"]
    return "\n".join(reg) + "\n", "\n".join(peers) + "\n"

def _phone_rpt_targets(doc: dict) -> List[Tuple[str, str]]:
    out = [(n["node"], f"dvs-node-{n['id']}") for n in doc.get("networks", []) if n.get("node")]
    if _phone_node() not in {o[0] for o in out}:
        out.append((_phone_node(), "dvs-phone-out"))
    return out

def _phone_render_rpt(targets: List[Tuple[str, str]], existing: str) -> Tuple[str, str, Optional[str]]:
    plain = _ph_strip(existing)
    live = "\n".join(l for l in plain.splitlines() if not l.lstrip().startswith(";"))
    for node, _c in targets:
        if re.search(r"^\s*\[" + re.escape(node) + r"\]", live, re.M) or \
           re.search(r"^\s*\[functions" + re.escape(node) + r"\]", live, re.M):
            return "", "", (f"rpt.conf already has a [{node}] or [functions{node}] section that "
                            f"the dashboard didn't write — remove it, or give that phone network "
                            f"another node number on the Edit page")
    if not re.search(r"^\s*\[node-main\]", live, re.M):
        return "", "", "rpt.conf has no [node-main] template section — add the Phone node by hand"
    ip = _iax_bindport()
    nb_lines = [(f"{node} = radio@127.0.0.1/{node},NONE" if ip == "4569"
                 else f"{node} = radio@127.0.0.1:{ip}/{node},NONE")
                for node, _c in targets if not re.search(r"^\s*" + re.escape(node) + r"\s*=", live, re.M)]
    nodes_body = "\n".join(nb_lines)
    pdoc = _phone_load()
    dt = pdoc.get("dialtime", _PHONE_DIALTIME_DEF)
    sx = pdoc.get("simplex", _PHONE_SIMPLEX_DEF)
    sx_lines = ([ "duplex = 1", f"voxtimeout = {sx['voxtimeout']}", f"voxrecover = {sx['voxrecover']}",
                  f"simplexpatchdelay = {sx['patchdelay']}", f"simplexphonedelay = {sx['phonedelay']}"]
                if sx.get("enabled") else [])
    if str(pdoc.get("hangtime", "")).isdigit():
        sx_lines.append(f"hangtime = {int(pdoc['hangtime'])}")
    stanzas = []
    for node, ctx in targets:
        stanzas.append("\n".join([
            f"[{node}](node-main)", "rxchannel = Local/pseudo", f"context = {ctx}",
            'callerid = "Phone" <0000000000>', f"functions = functions{node}",
            f"phone_functions = functions{node}", f"link_functions = functions{node}"]
            + sx_lines + ["",
            f"[functions{node}]",
            f"61 = autopatchup,noct=1,farenddisconnect=1,dialtime={dt},context={ctx},quiet=1",
            f"62 = cmd,{HANGUP_SCRIPT}", "63 = cop,9", "64 = cop,10", "65 = autopatchdn",
            "99 = cop,6"]
            + [f"{_TONE_CODE_PFX}{i} = cmd,{TONECODE_SCRIPT} {i}" for i in range(8)]))
    return nodes_body, "\n\n".join(stanzas), None

_PH_CODE_SCRIPT = """#!/bin/bash
# asl_dvs_dashboard - radio tone code (written by the dashboard)
# Leaves a note for the dashboard; the dashboard sends the tones.
case "$1" in [0-7]) ;; *) exit 0 ;; esac
d=/run/asl_dvs_tones/req
[ -d "$d" ] || exit 0
: > "$d/code$1" 2>/dev/null
exit 0
"""

_PH_SCRIPT = """#!/bin/bash
# asl_dvs_dashboard - hang up every Phone-tab call (written by the dashboard)
asterisk -rx "core show channels concise" | awk -F'!' '{print $1}' \\
  | grep -E '^(IAX2|PJSIP)/dvs' | while read -r ch; do
    asterisk -rx "channel request hangup $ch"
done
"""

def _phone_node_up(node: str, wait: bool = False) -> bool:
    for i in range(5 if wait else 1):
        out, ok = ami_command(f"{_AMI_RPT_SHOW_VARS} {node}", timeout=4)
        if ok and "RPT_" in (out or "").upper():
            return True
        if wait and i < 4:
            time.sleep(1.0)
    return False

def action_phone_apply(restart: bool = False) -> Tuple[bool, str]:
    with _phone_lock:
        if not os.path.isdir(AST_DIR):
            return False, f"{AST_DIR} not found — is Asterisk installed?"
        doc  = _phone_load()
        if not doc.get("activated"):
            return True, "settings saved; the phone is off, so Asterisk was not changed (Activate to set it up)"
        targets = _phone_rpt_targets(doc)
        sip  = any(n["type"] in _PHONE_SIP_TYPES for n in doc["networks"])
        iax  = any(n["type"] == "iax2" for n in doc["networks"]) or _hl_ready(doc)
        if _hl_ready(doc) and doc["hoip_link"]["username"].lower() in _iax_foreign_sections():
            return False, (f"iax.conf already has a [{doc['hoip_link']['username']}] section the dashboard "
                           f"didn't write — pick another HOIP AllStar Link username")
        rpt_path = _ph_path("rpt.conf")
        rpt_old  = _ph_read(rpt_path)
        if rpt_old is None:
            return False, f"{rpt_path} not found"
        nodes_body, stanza, err = _phone_render_rpt(targets, rpt_old)
        if err:
            return False, err
        iax_reg, iax_peers = _phone_render_iax(doc)
        owned = {"ext": _phone_render_dialplan(doc), "pjsip": _phone_render_pjsip(doc),
                 "iax_reg": iax_reg, "iax": iax_peers}
        want_file = {"ext": True, "pjsip": sip, "iax_reg": iax, "iax": iax}
        mods = "\n".join([f"load => {m}" for m in _PH_MODULES] +
                         ([f"load => {m}" for m in _PH_PJSIP_MODULES] if sip else []))
        _mods_old = _ph_read(_ph_path("modules.conf")) or ""
        sip_mods_new = sip and any(f"load => {m}" not in _mods_old for m in _PH_PJSIP_MODULES)
        edits: Dict[str, str] = {}
        rpt_new = _ph_place(rpt_old, nodes_body, "after:[nodes]")
        rpt_new = rpt_new.rstrip("\n") + "\n"
        if stanza:
            rpt_new = rpt_new + "\n" + _PH_BEGIN + "\n" + stanza + "\n" + _PH_END + "\n"
        edits["rpt.conf"] = rpt_new
        for fname, body, where, needed in (
                ("extensions.conf", "#tryinclude " + _PH_OWNED["ext"], "end", True),
                ("pjsip.conf",      "#tryinclude " + _PH_OWNED["pjsip"], "end", sip),
                ("modules.conf",    mods, "before:[global]", True)):
            old = _ph_read(_ph_path(fname))
            if old is None:
                if not needed:
                    continue
                old = ""
            edits[fname] = _ph_place(old, body if needed else "", where)
        old = _ph_read(_ph_path("iax.conf"))
        if old is not None or iax:
            old = old or ""
            t = _ph_place(old, "#tryinclude " + _PH_OWNED["iax_reg"] if iax else "", "after:[general]")
            t = _ph_place_second(t, "#tryinclude " + _PH_OWNED["iax"] if iax else "")
            edits["iax.conf"] = t
        changed: List[str] = []
        removed: List[str] = []
        try:
            for key, fname in _PH_OWNED.items():
                p = _ph_path(fname)
                if not want_file[key]:
                    if _ph_remove_owned(p):
                        changed.append(fname); removed.append(fname)
                    continue
                if _ph_read(p) != owned[key]:
                    _ph_write(p, owned[key]); changed.append(fname)
            for spath, sbody in ((HANGUP_SCRIPT, _PH_SCRIPT), (TONECODE_SCRIPT, _PH_CODE_SCRIPT)):
                hp = Path(spath)
                if _ph_read(str(hp)) != sbody:
                    hp.parent.mkdir(parents=True, exist_ok=True)
                    _ph_write(str(hp), sbody, 0o755); os.chmod(hp, 0o755)
                    changed.append(hp.name)
            _phone_req_dir()
            for fname, text in edits.items():
                if _ph_read(_ph_path(fname)) != text:
                    _ph_write(_ph_path(fname), text); changed.append(fname)
        except Exception as e:
            log.exception("phone apply failed")
            return False, f"Apply failed part-way: {e}"
    notes: List[str] = []
    clash = _phone_radio_code_clash()
    if clash:
        notes.append(f"heads-up: radio node {_cfg.asl_node} already has code(s) "
                     + ", ".join("*" + c for c in clash)
                     + f" that overlap the radio tone codes *{_TONE_CODE_PFX}0-*{_TONE_CODE_PFX}7")
    if sip and _phone_router_advice(doc):
        notes.append("see the router note under 'Behind a router' on the Edit page")
    running = _svc_is_active("asterisk")
    if sip:
        notes.append("SIP needs UDP 5060 and the audio ports open: use the sysmon Ports/Firewall tab "
                     "for the Pi, and forward them on your router")
    if _hl_ready(doc) and _hl_node(doc["hoip_link"]) != str(_cfg.asl_node):
        hn = _hl_node(doc["hoip_link"])
        owner = next((n for n in doc["networks"] if n.get("node") == hn), None)
        if owner is None or owner["id"] != doc.get("active"):
            notes.append(f"HOIP AllStar Link callers land on node {hn}, which reaches your radio only while "
                         + (f"{owner['name']} is the picked network" if owner else "no network is picked"))
    if _hl_ready(doc):
        notes.append(f"HOIP AllStar Link needs UDP {doc['hoip_link'].get('port') or _iax_bindport()} forwarded "
                     f"on your router to this Pi")
    if running:
        if "modules.conf" in changed:
            for mod in _PH_MODULES:
                ami_command(f"module load {mod}", timeout=10)
        if "modules.conf" in changed and sip_mods_new:
            if restart:
                run(["systemctl", "restart", "asterisk"], timeout=60)
                notes.append("Asterisk restarted")
            else:
                notes.append("Asterisk must be restarted once to load the SIP modules")
        else:
            if "rpt.conf" in changed:
                ami_command("module reload app_rpt", timeout=20)
            if _PH_OWNED["ext"] in changed or "extensions.conf" in changed:
                ami_command("dialplan reload", timeout=15)
            if any(c.startswith("dvs_phone_iax") or c == "iax.conf" for c in changed):
                ami_command("iax2 reload", timeout=15)
            if any(c in ("dvs_phone_pjsip.conf", "pjsip.conf") for c in changed):
                ami_command("module reload res_pjsip.so", timeout=15)
                ami_command("module reload res_pjsip_outbound_registration.so", timeout=15)
        restarted = "Asterisk restarted" in notes
        if not restarted and not ("modules.conf" in changed and sip_mods_new):
            missing: List[str] = []
            for nd, _c in targets:
                if not _phone_node_up(nd, wait=("rpt.conf" in changed and not missing)):
                    missing.append(nd)
            if missing:
                one = len(missing) == 1
                who = ("Node " if one else "Nodes ") + ", ".join(missing)
                if restart:
                    run(["systemctl", "restart", "asterisk"], timeout=60)
                    notes.append(f"{who} {'wasn' if one else 'weren'}'t running, so Asterisk was restarted")
                    restarted = True
                else:
                    notes.append(f"{who} {'isn' if one else 'aren'}'t running in Asterisk yet — tick 'Restart "
                                 f"Asterisk if needed' and save again (or run: systemctl restart asterisk)")
        if not restarted:
            if doc.get("active"):
                _phone_astdb("put", "active", doc["active"])
            _phone_astdb("put", "patch", "1" if doc.get("patch_enabled", True) else "0")
    else:
        notes.append("Asterisk isn't running — changes take effect when it starts")
    upd = [c for c in changed if c not in removed]
    what = ("nothing needed changing" if not changed else
            "; ".join(x for x in ("updated " + ", ".join(upd) if upd else "",
                                  "removed unused " + ", ".join(removed) if removed else "") if x))
    return True, what + ("; " + "; ".join(notes) if notes else "")

def _ph_place_second(text: str, body: str) -> str:
    key = _PH_OWNED["iax"]
    pat = re.compile(re.escape(_PH_BEGIN) + r"(?:(?!" + re.escape(_PH_END) + r").)*?" +
                     re.escape(key) + r".*?" + re.escape(_PH_END) + r"\n?\n?", re.S)
    text = pat.sub("", text)
    if not body:
        return text
    return text.rstrip("\n") + "\n\n" + _PH_BEGIN + "\n" + body + "\n" + _PH_END + "\n"


_PH_CH_RE   = re.compile(r"^(IAX2|PJSIP)/dvs")
_PH_PATTERNS = {"N": "[2-9]", "X": "[0-9]"}
_PH_BLOCKED_RES = [re.compile("^" + "".join(_PH_PATTERNS.get(c, re.escape(c)) for c in p[1:]) + "$")
                   for p in _PH_BLOCKED]
_phone_state_cache: list = [0.0, {"state": "idle", "who": ""}]
_phone_reg_cache:   list = [0.0, {}]
_phone_open_state: Optional[bool] = None
_phone_live_chan: list = [""]
_phone_dialed: list = [""]

def action_phone_activate(restart: bool = False) -> Tuple[bool, str]:
    with _phone_lock:
        doc = _phone_load()
        if doc.get("activated"):
            return True, "The phone is already on"
        doc["activated"] = True
        ok, msg = _phone_write(doc)
        if not ok:
            return False, msg
    ok, msg = action_phone_apply(restart)
    if not ok:
        with _phone_lock:
            doc = _phone_load()
            doc["activated"] = False
            _phone_write(doc)
        log.warning("phone: switching on failed: %s", msg)
        return False, f"The phone is still off — {msg}"
    log.info("phone: switched on (%s)", msg)
    return True, "Phone on — " + msg

_PH_EDITED = ("rpt.conf", "extensions.conf", "pjsip.conf", "iax.conf", "modules.conf")

def action_phone_revert(restart: bool = False) -> Tuple[bool, str]:
    with _phone_lock:
        doc = _phone_load()
        nodes = _phone_all_nodes(doc)
        mods_txt = _ph_read(_ph_path("modules.conf")) or ""
        ours = "".join(m.group(0) for m in _PH_BLOCK_RE.finditer(mods_txt))
        sip_was = any(f"load => {m}" in ours for m in _PH_PJSIP_MODULES)
        doc["activated"] = False
        ok, msg = _phone_write(doc)
        if not ok:
            return False, msg
    running = _svc_is_active("asterisk")
    if running:
        _phone_hangup_all()
        if _link_enter(timeout=20):
            try:
                for nd in (_query_linked_nodes() or []):
                    if nd in nodes:
                        _drop_one_link(nd)
                        time.sleep(_LINK_DROP_PACING_SEC)
            finally:
                _link_exit()
    changed: List[str] = []
    removed: List[str] = []
    with _phone_lock:
        try:
            for fname in _PH_EDITED:
                p = _ph_path(fname)
                old = _ph_read(p)
                if old is not None and _ph_strip(old) != old:
                    _ph_write(p, _ph_strip(old))
                    changed.append(fname)
            for fname in _PH_OWNED.values():
                if _ph_remove_owned(_ph_path(fname)):
                    removed.append(fname)
            for sp in (HANGUP_SCRIPT, TONECODE_SCRIPT):
                txt = _ph_read(sp)
                if txt is not None and txt.startswith("#!/bin/bash\n# asl_dvs_dashboard"):
                    os.unlink(sp)
                    removed.append(os.path.basename(sp))
        except Exception as e:
            log.exception("phone revert failed")
            return False, f"Revert stopped part-way: {e} — press Revert again"
    notes: List[str] = []
    if running:
        ami_command("database deltree dvsphone", timeout=4)
        if "rpt.conf" in changed:
            ami_command("module reload app_rpt", timeout=20)
        if "extensions.conf" in changed or _PH_OWNED["ext"] in removed:
            ami_command("dialplan reload", timeout=15)
        if "iax.conf" in changed:
            ami_command("iax2 reload", timeout=15)
        if "pjsip.conf" in changed:
            ami_command("module reload res_pjsip.so", timeout=15)
        time.sleep(1.0)
        still = [nd for nd in nodes if _phone_node_up(nd)]
        if sip_was or still:
            why = (("node" + ("s " if len(still) > 1 else " ") + ", ".join(still) + " still running")
                   if still else "the SIP modules still loaded")
            if restart:
                run(["systemctl", "restart", "asterisk"], timeout=60)
                notes.append(f"Asterisk restarted ({why})")
            else:
                notes.append(f"Asterisk has {why} until it restarts — restart it when no one is on: "
                             f"systemctl restart asterisk, or sysmon Console → Restart Asterisk when idle")
    else:
        notes.append("Asterisk isn't running — it starts without the phone")
    global _phone_open_state
    _phone_open_state = False
    _phone_state_cache[0] = 0.0
    what = "; ".join(x for x in ("took the phone out of " + ", ".join(changed) if changed else "",
                                  "removed " + ", ".join(removed) if removed else "") if x) \
        or "nothing of the phone was left in Asterisk"
    log.info("phone: switched off (%s)", what)
    return True, "Phone off — " + what + ("; " + "; ".join(notes) if notes else "") + \
        ". Your phone settings are kept for when you turn it on again"

def _phone_doc() -> dict:
    now = time.monotonic()
    with _phone_lock:
        if _phone_doc_cache[1] is None or now - _phone_doc_cache[0] > 5.0:
            _phone_doc_cache[1] = _phone_load()
            _phone_doc_cache[0] = now
        return _phone_doc_cache[1]

def _phone_channels() -> List[List[str]]:
    out, ok = ami_command("core show channels concise", timeout=3)
    if not ok or not out:
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split("!")
        if len(parts) >= 8 and _PH_CH_RE.match(parts[0]):
            rows.append(parts)
    return rows

def _phone_call_state(max_age: float = 2.0) -> dict:
    now = time.monotonic()
    if now - _phone_state_cache[0] < max_age:
        return dict(_phone_state_cache[1])
    state, who, outgoing = "idle", "", False
    rank = {"idle": 0, "dialing": 1, "incoming": 2, "in_call": 3}
    rows = _phone_channels()
    for p in rows:
        ctx, st_, app, cid = p[1], p[4], p[5], p[7]
        if app.lower() == "appdial":
            cur, who_, out_ = ("in_call" if st_ == "Up" else "dialing"), "", True
        elif ctx.startswith("dvs-in-"):
            cur = "in_call" if (st_ == "Up" and app.lower() == "rpt") else "incoming"
            who_ = cid if cid not in ("", "<unknown>") else ""
            out_ = False
        else:
            cur, who_, out_ = ("in_call" if st_ == "Up" else "dialing"), "", True
        if rank[cur] > rank[state]:
            state, who, outgoing = cur, who_, out_
    res = {"state": state, "who": _strip_ctrl(who)[:32]}
    if state != "idle" and outgoing and _phone_dialed[0]:
        res["number"] = _phone_dialed[0]
    up = sorted((r for r in rows if r[4] == "Up"), key=lambda r: r[5].lower() != "appdial")
    _phone_live_chan[0] = up[0][0] if (state == "in_call" and up) else ""
    _phone_state_cache[0], _phone_state_cache[1] = now, res
    return dict(res)

def _phone_reg_states(doc: dict) -> dict:
    now = time.monotonic()
    if now - _phone_reg_cache[0] < 15.0:
        return dict(_phone_reg_cache[1])
    need_iax  = any(n["type"] == "iax2" and n.get("register") for n in doc["networks"])
    need_sip  = any(n["type"] in _PHONE_LOGIN_SIP and n.get("register") for n in doc["networks"])
    iax_txt   = ami_command("iax2 show registry", timeout=3)[0] if need_iax else ""
    sip_txt   = ami_command("pjsip show registrations", timeout=3)[0] if need_sip else ""
    res: dict = {}
    for n in doc["networks"]:
        if n["type"] == "iax2" and _phone_signs_in(doc, n):
            res[n["id"]] = any(n["username"] in l and "Registered" in l for l in iax_txt.splitlines())
        elif n["type"] in _PHONE_LOGIN_SIP and _phone_signs_in(doc, n):
            res[n["id"]] = any(f"{n['id']}-reg" in l and "Registered" in l for l in sip_txt.splitlines())
        else:
            res[n["id"]] = None
    _phone_reg_cache[0], _phone_reg_cache[1] = now, res
    return dict(res)

_hl_state_cache: list = [0.0, {}]

def _hl_state(doc: dict) -> dict:
    if not _hl_ready(doc):
        return {}
    now = time.monotonic()
    if now - _hl_state_cache[0] < 2.0:
        return dict(_hl_state_cache[1])
    user = doc["hoip_link"]["username"]
    rows = [r for r in _phone_all_channels() if r[0].startswith(f"IAX2/{user}-")]
    up = [r for r in rows if r[4] == "Up"]
    who = ""
    if up:
        try:
            det = ami_command(f"core show channel {up[0][0]}", timeout=5)[0] or ""
        except Exception:
            det = ""
        m = re.search(r"Caller ID Name:\s*(.+)", det)
        name = m.group(1).strip() if m else ""
        num = up[0][7] if len(up[0]) > 7 else ""
        if name and name not in ("(N/A)", "<unknown>"):
            who = _strip_ctrl(name)[:32] + (f" ({_strip_ctrl(num)[:20]})" if num and num not in ("", "<unknown>") else "")
        elif num not in ("", "<unknown>"):
            who = _strip_ctrl(num)[:32]
    res = {"on": True, "node": _hl_node(doc["hoip_link"]), "callers": len(up), "who": who}
    _hl_state_cache[0], _hl_state_cache[1] = now, res
    return dict(res)

def action_hl_dialstring() -> Tuple[bool, str]:
    doc = _phone_load()
    hl = doc.get("hoip_link") or {}
    if not (hl.get("username") and hl.get("password") and hl.get("fqdn")):
        return False, "Fill in the HOIP AllStar Link username, password and internet name, then Save Phone"
    return True, f"IAX2/{hl['username']}:{hl['password']}@{hl['fqdn']}:{hl.get('port') or _iax_bindport()}/{_hl_node(hl)}"

def _phone_signin_status(doc: dict) -> dict:
    if _phone_signin_mode(doc) == "all":
        return {"state": "all"}
    sid = _phone_signin_id(doc)
    if not sid:
        return {"state": "off"}
    job = _phone_signin_job
    busy = job["id"] == sid and time.monotonic() - job["started"] < _PHONE_SIGNIN_WAIT
    if busy:
        _phone_reg_cache[0] = 0.0 if time.monotonic() - _phone_reg_cache[0] > 3 else _phone_reg_cache[0]
    ok = _phone_reg_states(doc).get(sid)
    if job["error"] and job["id"] == sid:
        return {"id": sid, "state": "failed", "error": job["error"]}
    if ok:
        return {"id": sid, "state": "signed"}
    return {"id": sid, "state": "signing" if busy else ("failed" if ok is False else "off")}

def _phone_status() -> dict:
    doc = _phone_doc()
    if not doc["networks"]:
        return {"configured": False}
    on_tab = get_state_fields("page")["page"] == "PHONE"
    call = _phone_call_state() if on_tab else {"state": "idle", "who": ""}
    live = _phone_live_node(doc)
    linked = live in get_state_fields("bridge_linked_nodes")["bridge_linked_nodes"] if on_tab else None
    return {"configured": True, "active": doc["active"], "patch": bool(doc["patch_enabled"]),
            "node": live, "node_linked": linked,
            "activated": bool(doc.get("activated")),
            "call": call,
            "tone": _phone_tone_live_info(doc) if call["state"] == "in_call" else {},
            "reg":  _phone_reg_states(doc) if on_tab else {},
            "signin": _phone_signin_status(doc) if on_tab else {},
            "tot": _tot_status() if on_tab else {},
            "tone_path": doc.get("tone_path", _PHONE_TONE_PATH_DEF),
            "hoip_link": _hl_state(doc) if on_tab else {},
            "notice": _phone_notice[0] if time.monotonic() < _phone_notice[1] else ""}

def _phone_check_number(net: dict, num: str) -> Tuple[Optional[str], Optional[str]]:
    num = str(num or "").strip().replace(" ", "").replace("-", "")
    if not num or not num.isdigit() or len(num) > 20:
        return None, "Type a number to dial (digits only)"
    if net["dialing"] == "ext":
        return num, None
    if num == "911":
        if not net.get("e911"):
            return None, (f"911 is off on {net['name']} — set up E911 with the provider, "
                          f"then tick 'E911 is set up' on the Edit page")
        return num, None
    if num.startswith("011"):
        if not net.get("allow_intl") or not (10 <= len(num) <= 20):
            return None, f"International calls are off on {net['name']}"
        return num, None
    full = "1" + num if len(num) == 10 else num
    if len(full) == 11 and re.match(r"^1[2-9][0-9]{2}[2-9]", full):
        if any(r.match(full) for r in _PH_BLOCKED_RES):
            return None, "That number is blocked (toll-free, premium or not a real number)"
        return num, None
    return None, "Dial a 10-digit number, area code first"

def action_phone_dial(number: str) -> Tuple[bool, str]:
    st = get_state()
    if not _phone_on():
        return False, "The phone is off — turn it on with Activate on the Edit page"
    if st.page != "PHONE":
        return False, "Open the Phone tab first"
    if not st.has_asl:
        return False, "AllStarLink isn't running"
    doc = _phone_load()
    if not doc.get("patch_enabled", True):
        return False, "Phone patch is off — turn it on first"
    net = next((n for n in doc["networks"] if n["id"] == doc.get("active")), None)
    if net is None:
        return False, "Pick a phone network first"
    if str(number).strip() == _PHONE_TEST_ALIAS and net.get("test_number"):
        num, err = _PHONE_TEST_ALIAS, None
    elif str(number).strip() == _HOIP_VM_ALIAS and net.get("type") in _PHONE_EXT_TYPES and net.get("voicemail_access"):
        num, err = _HOIP_VM_ALIAS, None
    else:
        num, err = _phone_check_number(net, number)
    if err:
        return False, err
    node = _phone_net_node(net)
    if node not in st.bridge_linked_nodes:
        return False, f"Phone node {node} ({net['name']}) isn't linked yet — wait a moment and try again"
    if _phone_call_state(0.0)["state"] != "idle":
        return False, "A call is already in progress — hang up first"
    _phone_astdb("put", "active", net["id"])
    tones = _phone_fav_tones(net, num, number)
    by_asterisk = _phone_then_prepare(tones)
    out, ok = ami_command(f"rpt fun {node} *61{num}", timeout=6, priority=True)
    if not ok:
        if by_asterisk:
            _phone_astdb("del", "then")
        log.warning("phone dial failed: %r", out)
        return False, "Couldn't start the call — check Asterisk"
    _phone_dialed[0] = num
    _phone_state_cache[0] = 0.0
    if tones:
        if not by_asterisk:
            threading.Thread(target=_phone_after_answer, args=(tones, doc.get("dialtime")),
                             name="phone-then-send", daemon=True).start()
        return True, f"Dialing {num} on {net['name']}… (saved tones go out when it answers)"
    return True, f"Dialing {num} on {net['name']}…"

def action_phone_voicemail() -> Tuple[bool, str]:
    doc = _phone_load()
    net = next((n for n in doc["networks"] if n["id"] == doc.get("active")), None)
    if net is None or net.get("type") not in _PHONE_EXT_TYPES or not net.get("voicemail_access"):
        return False, "Pick your Hams Over IP network first (and save its Voicemail Access code on the Edit page)"
    ok, msg = action_phone_dial(_HOIP_VM_ALIAS)
    if ok:
        _phone_dialed[0] = f"VM {net['voicemail_access']}"
    return (True, f"Calling voicemail ({net['voicemail_access']}) on {net['name']}…") if ok else (False, msg)

def action_phone_test() -> Tuple[bool, str]:
    doc = _phone_load()
    net = next((n for n in doc["networks"] if n["id"] == doc.get("active")), None)
    if net is None or not net.get("test_number"):
        return False, "Pick a network with a test number first (set it on the Edit page)"
    ok, msg = action_phone_dial(_PHONE_TEST_ALIAS)
    if ok:
        _phone_dialed[0] = "TEST"
        return True, f"Test call ({net['test_number']}) on {net['name']}…"
    return False, msg

def _phone_hangup_all() -> int:
    n = 0
    for row in _phone_channels():
        ami_command(f"channel request hangup {row[0]}", timeout=4)
        n += 1
    for nd in _phone_all_nodes():
        ami_command(f"rpt fun {nd} *65", timeout=4)
    _phone_state_cache[0] = 0.0
    return n

_PHONE_TONES_RE  = re.compile(r"^[0-9*#,]{1,32}$")
_PHONE_TONE_MS   = 250
_PHONE_TONE_GAP  = 0.35
_phone_tone_lock = threading.Lock()

def _phone_clean_tones(v) -> Optional[str]:
    v = str(v or "").replace(" ", "")
    if not v:
        return ""
    return v if _PHONE_TONES_RE.match(v) else None

def _phone_live_channel() -> Optional[str]:
    rows = [r for r in _phone_channels() if r[4] == "Up"]
    rows.sort(key=lambda r: r[5].lower() != "appdial")
    return rows[0][0] if rows else None

def _phone_tone_err(out: str) -> str:
    m = re.search(r"^Message:\s*(.+)$", out or "", re.M)
    why = (m.group(1).strip() if m else (out or "").strip()) or "no reply"
    if "unknown command" in why.lower():
        return ("Asterisk doesn't have its tone module loaded (app_senddtmf.so) — "
                "Save Phone on the Edit page to load it")
    if "permission" in why.lower():
        return ("Asterisk won't let the dashboard send tones — add 'call' to the "
                "write= line of the dashboard's login in manager.conf")
    if "not connected" in why.lower() or "not available" in why.lower():
        return "Can't reach Asterisk's manager connection, so tones can't be sent"
    return f"Asterisk didn't send the tones ({why[:80]})"

_phone_dtmf_ready = [False]

def _phone_dtmf_listed() -> Tuple[bool, bool, str]:
    out, ok = ami_action([("Action", "ListCommands")], timeout=6)
    return ok, bool(re.search(r"^PlayDTMF:", out or "", re.M | re.I)), out

def _phone_senddtmf_loaded() -> bool:
    out, _ = ami_command("module show like senddtmf", timeout=5)
    return "app_senddtmf.so" in (out or "")

def _phone_dtmf_check() -> Tuple[bool, str]:
    if _phone_dtmf_ready[0]:
        return True, ""
    ok, has, out = _phone_dtmf_listed()
    if not ok:
        return False, _phone_tone_err(out)
    if not has and not _phone_senddtmf_loaded():
        log.info("phone: loading app_senddtmf.so for the tone buttons")
        ami_command("module load app_senddtmf.so", timeout=10)
        ok, has, out = _phone_dtmf_listed()
    if not has:
        if not _phone_senddtmf_loaded():
            return False, ("Asterisk's tone module (app_senddtmf.so) won't load — "
                           "check that it's installed, then Save Phone on the Edit page")
        return False, ("Asterisk won't let the dashboard send tones — add 'call' to the "
                       "write= line of the dashboard's login in manager.conf, then run: "
                       "asterisk -rx \"manager reload\"")
    _phone_dtmf_ready[0] = True
    return True, ""

_phone_ast_major: list = [None]

def _phone_asterisk_major() -> int:
    if _phone_ast_major[0] is None:
        out, ok = ami_command("core show version", timeout=4)
        m = re.search(r"Asterisk\s+(?:certified/)?(\d+)", out or "") if ok else None
        if not m:
            return 0
        _phone_ast_major[0] = int(m.group(1))
    return _phone_ast_major[0]

def _phone_all_channels() -> List[List[str]]:
    out, ok = ami_command("core show channels concise", timeout=3)
    if not ok or not out:
        return []
    return [l.split("!") for l in out.splitlines() if l.count("!") >= 12]

def _phone_node_side(chan: str) -> Optional[str]:
    rows = _phone_all_channels()
    me = next((r for r in rows if r[0] == chan), None)
    if not me or len(me) < 13 or not me[12].strip():
        return None
    bid = me[12].strip()
    peers = [r[0] for r in rows if r[0] != chan and len(r) > 12 and r[12].strip() == bid]
    return peers[0] if peers else None

def _phone_tone_path() -> str:
    p = _phone_doc().get("tone_path", _PHONE_TONE_PATH_DEF)
    return p if p in PHONE_TONE_PATHS else _PHONE_TONE_PATH_DEF

def _phone_play_one(chan: str, ch: str, receive: bool) -> Tuple[str, bool]:
    f = [("Action", "PlayDTMF"), ("Channel", chan), ("Digit", ch), ("Duration", str(_PHONE_TONE_MS))]
    if receive:
        f.append(("Receive", "true"))
    return ami_action(f, timeout=4)

_TONE_DIR      = "/run/asl_dvs_tones"
_TONE_RATE     = 8000
_TONE_ON_MS    = 200
_TONE_GAP_MS   = 120
_TONE_AMPL     = 7000
_DTMF_FREQ     = {"1": (697, 1209), "2": (697, 1336), "3": (697, 1477),
                  "4": (770, 1209), "5": (770, 1336), "6": (770, 1477),
                  "7": (852, 1209), "8": (852, 1336), "9": (852, 1477),
                  "*": (941, 1209), "0": (941, 1336), "#": (941, 1477)}
_TONE_NAME     = {**{d: f"t{d}" for d in "0123456789"}, "*": "tstar", "#": "thash"}
_phone_sound_ready = [False]

def _ulaw_byte(s: int) -> int:
    sign = 0x80 if s < 0 else 0
    s = min(-s if s < 0 else s, 32635) + 0x84
    exp, mask = 7, 0x4000
    while exp > 0 and not (s & mask):
        exp -= 1
        mask >>= 1
    return ~(sign | (exp << 4) | ((s >> (exp + 3)) & 0x0F)) & 0xFF

def _tone_bytes(f1: int, f2: int, ms: int) -> bytes:
    import math
    n, fade = _TONE_RATE * ms // 1000, _TONE_RATE * 5 // 1000
    out = bytearray()
    for i in range(n):
        g = min(1.0, i / fade, (n - 1 - i) / fade)
        v = _TONE_AMPL * g * (math.sin(2 * math.pi * f1 * i / _TONE_RATE) +
                              math.sin(2 * math.pi * f2 * i / _TONE_RATE))
        out.append(_ulaw_byte(int(v)))
    return bytes(out)

def _phone_tone_files() -> bool:
    want = {name: _tone_bytes(*_DTMF_FREQ[d], _TONE_ON_MS) for d, name in _TONE_NAME.items()}
    want["gap"] = b"\xff" * (_TONE_RATE * _TONE_GAP_MS // 1000)
    want["wait1"] = b"\xff" * _TONE_RATE
    try:
        os.makedirs(_TONE_DIR, exist_ok=True)
        os.chmod(_TONE_DIR, 0o755)
        for name, data in want.items():
            p = os.path.join(_TONE_DIR, name + ".ulaw")
            try:
                if os.path.getsize(p) == len(data):
                    continue
            except OSError:
                pass
            with open(p + ".tmp", "wb") as fh:
                fh.write(data)
            os.chmod(p + ".tmp", 0o644)
            os.replace(p + ".tmp", p)
        return True
    except OSError as e:
        log.warning("phone: couldn't make the tone recordings in %s: %s", _TONE_DIR, e)
        return False

def _phone_sound_check() -> Tuple[bool, str]:
    if _phone_sound_ready[0]:
        return True, ""
    if not _phone_tone_files():
        return False, f"Couldn't make the tone recordings in {_TONE_DIR}"
    missing = []
    for mod in ("app_chanspy.so", "app_playback.so", "format_pcm.so"):
        if mod not in (ami_command(f"module show like {mod[:-3]}", timeout=5)[0] or ""):
            ami_command(f"module load {mod}", timeout=10)
            if mod not in (ami_command(f"module show like {mod[:-3]}", timeout=5)[0] or ""):
                missing.append(mod)
    if missing:
        return False, ("Asterisk can't load " + ", ".join(missing) +
                       " — needed to send tones as sound; check it's installed, then Save Phone")
    if "dvs-tones" not in (_ph_read(_ph_path(_PH_OWNED["ext"])) or ""):
        return False, "The Phone dialplan is out of date — Save Phone on the Edit page once"
    _phone_sound_ready[0] = True
    return True, ""

def _phone_send_sound(chan: str, tones: str) -> Tuple[bool, str]:
    ready, why = _phone_sound_check()
    if not ready:
        return False, why
    parts: List[str] = []
    ms = 0
    for ch in tones:
        if ch == ",":
            parts.append("wait1"); ms += 1000
        elif ch in _TONE_NAME:
            parts += [_TONE_NAME[ch], "gap"]; ms += _TONE_ON_MS + _TONE_GAP_MS
    if not parts:
        return False, "No tones to send"
    files = "&".join(f"{_TONE_DIR}/{p}" for p in parts)
    with _phone_tone_lock:
        out, ok = ami_action([("Action", "Originate"), ("Channel", "Local/s@dvs-tones/n"),
                              ("Application", "ChanSpy"), ("Data", f"{chan},qwE"),
                              ("Variable", f"DVSTONES={files}"), ("CallerID", '"Tones" <0>'),
                              ("Timeout", "8000"), ("Async", "true")], timeout=6)
        if not ok:
            m = re.search(r"^Message:\s*(.+)$", out or "", re.M)
            why = (m.group(1).strip() if m else (out or "").strip()) or "no reply"
            log.warning("phone: tones as sound refused: %s", why[:160])
            if "permission" in why.lower():
                return False, ("Asterisk won't let the dashboard start the tone player — add "
                               "'originate' to the write= line of the dashboard's login in manager.conf, "
                               "then run: asterisk -rx \"manager reload\"")
            _phone_sound_ready[0] = False
            return False, f"Asterisk didn't play the tones ({why[:80]})"
        time.sleep(0.8 + ms / 1000.0)
    log.info("phone: played %d tone(s) as sound into %s", sum(1 for c in tones if c != ","), chan)
    return True, "sent"

def _phone_send_tones(tones: str) -> Tuple[bool, str]:
    chan = _phone_live_channel()
    if not chan:
        return False, "No call in progress"
    path = _phone_tone_path()
    if path == "sound":
        return _phone_send_sound(chan, tones)
    ready, why = _phone_dtmf_check()
    if not ready:
        return False, why
    target, receive = chan, False
    if path == "node":
        side = _phone_node_side(chan)
        if side and _phone_asterisk_major() >= 16:
            target, receive = side, True
        else:
            log.info("phone: no node side to send tones from (%s) — sending the old way",
                     "too old an Asterisk" if side else "not a joined call")
    sent = 0
    with _phone_tone_lock:
        for ch in tones:
            if ch == ",":
                time.sleep(1.0)
                continue
            out, ok = _phone_play_one(target, ch, receive)
            if not ok and receive:
                log.warning("phone: node side wouldn't take a tone (%s) — switching to the old way",
                            (out or "").strip().replace("\r\n", " | ")[:120])
                target, receive = chan, False
                out, ok = _phone_play_one(target, ch, receive)
            if not ok:
                _phone_dtmf_ready[0] = False
                log.warning("phone: tone send stopped after %d tone(s): %s", sent,
                            (out or "").strip().replace("\r\n", " | ")[:160])
                return False, _phone_tone_err(out)
            sent += 1
            time.sleep(_PHONE_TONE_GAP)
    log.info("phone: sent %d tone(s) into %s%s", sent, target, " (node side)" if receive else "")
    return True, "sent"

def action_phone_tone_path(path: str) -> Tuple[bool, str]:
    path = str(path or "").strip()
    if path not in PHONE_TONE_PATHS:
        return False, "Pick a way to send tones from the list"
    with _phone_lock:
        doc = _phone_load()
        if doc.get("tone_path") != path or not doc.get("tone_path_user"):
            doc["tone_path"], doc["tone_path_user"] = path, True
            ok, msg = _phone_write(doc)
            if not ok:
                return False, msg
    return True, f"Tones now go: {_PHONE_TONE_PATH_LBL[path]} — try a tone"

_phone_notice: list = ["", 0.0]

def _phone_set_notice(text: str, secs: float = 6.0) -> None:
    _phone_notice[0], _phone_notice[1] = text, time.monotonic() + secs

def _phone_fav_tones(net: dict, num: str, typed: str) -> str:
    typed_c = _phone_clean_number(typed) or ""
    for f in (net or {}).get("favorites", []):
        n = str(f.get("number", ""))
        if n and n in (num, typed_c) and f.get("tones"):
            return str(f["tones"])
    return ""

def _phone_after_answer(tones: str, dialtime_ms) -> None:
    try:
        limit = float(dialtime_ms) / 1000.0
    except (TypeError, ValueError):
        limit = _PHONE_DIALTIME_DEF / 1000.0
    start = time.monotonic()
    deadline, seen = start + limit + 15.0, False
    while time.monotonic() < deadline:
        state = _phone_call_state(0.0)["state"]
        if state == "in_call":
            time.sleep(1.0)
            ok, msg = _phone_send_tones(tones)
            _phone_set_notice("Sent the favorite's saved tones" if ok else msg)
            return
        if state != "idle":
            seen = True
        elif seen or time.monotonic() - start > 8.0:
            log.info("phone: the call ended before it answered — saved tones not sent")
            return
        time.sleep(0.5)
    log.info("phone: no answer in time — saved tones not sent")

def _phone_dstring(tones: str) -> str:
    return "ww" + tones.replace(",", "ww")

def _phone_dialplan_has_then() -> bool:
    return "dvsphone/then" in (_ph_read(_ph_path(_PH_OWNED["ext"])) or "")

def _phone_then_prepare(tones: str) -> bool:
    if not _phone_dialplan_has_then():
        return False
    if not tones or _phone_tone_path() != "node":
        _phone_astdb("del", "then")
        return False
    if _phone_astdb("put", "then", _phone_dstring(tones)):
        return True
    log.warning("phone: couldn't hand the saved tones to Asterisk — sending them after answer")
    return False

def _phone_refresh_on_start() -> None:
    time.sleep(20)
    try:
        doc = _phone_load()
        ext = _ph_path(_PH_OWNED["ext"])
        if not doc.get("activated") or not doc.get("networks") or _ph_read(ext) is None \
                or not _svc_is_active("asterisk"):
            return
        if not _phone_setup_stale(doc):
            return
        ok, msg = action_phone_apply(False)
        log.info("phone: refreshed the Phone setup after an upgrade: %s", msg if ok else "failed — " + msg)
    except Exception as e:
        log.warning("phone: start-up refresh failed: %s", e)

def _phone_setup_stale(doc: dict) -> bool:
    if _ph_read(_ph_path(_PH_OWNED["ext"])) != _phone_render_dialplan(doc):
        return True
    if any(n["type"] in _PHONE_SIP_TYPES for n in doc["networks"]):
        if _ph_read(_ph_path(_PH_OWNED["pjsip"])) != _phone_render_pjsip(doc):
            return True
    if any(n["type"] == "iax2" for n in doc["networks"]):
        if _ph_read(_ph_path(_PH_OWNED["iax_reg"])) != _phone_render_iax(doc)[0]:
            return True
    rpt = _ph_read(_ph_path("rpt.conf")) or ""
    try:
        nb, st_, err = _phone_render_rpt(_phone_rpt_targets(doc), rpt)
        if not err and ((nb and nb not in rpt) or (st_ and st_ not in rpt)):
            return True
    except Exception:
        pass
    return TONECODE_SCRIPT not in rpt or _ph_read(TONECODE_SCRIPT) != _PH_CODE_SCRIPT

def action_phone_vm_pin() -> Tuple[bool, str]:
    net = _phone_active_net(_phone_load())
    if net is None or net.get("type") not in _PHONE_EXT_TYPES:
        return False, "The picked network has no voicemail (Hams Over IP or AmateurWire)"
    pin = str(net.get("voicemail_pin") or "")
    if not pin:
        return False, "No voicemail PIN saved — add it on the Edit page (Phone, Voicemail PIN)"
    ok, msg = _phone_send_tones(pin + "#")
    return (True, "Sent the voicemail PIN") if ok else (False, msg)

def action_phone_send_tones(tones: str) -> Tuple[bool, str]:
    t = _phone_clean_tones(tones)
    if t is None:
        return False, "Tones can only use 0-9, * and # (a comma waits 1 second), up to 32"
    if not t:
        return False, "Type the tones to send"
    ok, msg = _phone_send_tones(t)
    return (True, f"Sent {t}") if ok else (False, msg)

_phone_tone_live: dict = {"chan": "", "mode": ""}
_phone_tone_live_lock = threading.Lock()

def _phone_net_id_of(chan: str) -> str:
    m = re.match(r"^PJSIP/(dvs[a-z0-9]+)-[0-9a-fA-F]+$", chan or "")
    return m.group(1) if m else ""

def _phone_tone_read(chan: str) -> str:
    out, ok = ami_action([("Action", "Getvar"), ("Channel", chan),
                          ("Variable", "PJSIP_DTMF_MODE()")], timeout=4)
    m = re.search(r"^Value:\s*(\S+)", out or "", re.M) if ok else None
    return m.group(1).strip() if m and m.group(1).strip() in PHONE_TONE_MODES else ""

def _phone_tone_live_info(doc: dict) -> dict:
    chan = _phone_live_chan[0]
    if not chan.startswith("PJSIP/"):
        return {"sip": False}
    with _phone_tone_live_lock:
        if _phone_tone_live["chan"] != chan:
            _phone_tone_live.update(chan=chan, mode=_phone_tone_read(chan))
        mode = _phone_tone_live["mode"]
    nid = _phone_net_id_of(chan)
    net = next((n for n in doc.get("networks", []) if n.get("id") == nid), None)
    return {"sip": True, "mode": mode, "net": net["name"] if net else "",
            "saved": _phone_tone_mode(net) if net else ""}

def action_phone_tone_mode(mode: str) -> Tuple[bool, str]:
    mode = str(mode or "").strip()
    if mode not in PHONE_TONE_MODES:
        return False, "Pick a tone mode from the list"
    chan = _phone_live_channel()
    if not chan:
        return False, "No call in progress"
    if not chan.startswith("PJSIP/"):
        return False, "Tone mode only applies to SIP networks — IAX2 carries tones on its own"
    out, ok = ami_action([("Action", "Setvar"), ("Channel", chan),
                          ("Variable", "PJSIP_DTMF_MODE()"), ("Value", mode)], timeout=4)
    if not ok:
        m = re.search(r"^Message:\s*(.+)$", out or "", re.M)
        why = (m.group(1).strip() if m else (out or "").strip()) or "no reply"
        log.warning("phone: tone mode change refused: %s", why[:160])
        if "permission" in why.lower():
            return False, ("Asterisk won't let the dashboard change the call — add 'call' to the "
                           "write= line of the dashboard's login in manager.conf")
        return False, f"Asterisk didn't change the tone mode ({why[:80]})"
    with _phone_tone_live_lock:
        _phone_tone_live.update(chan=chan, mode=mode)
    _phone_live_chan[0] = chan
    log.info("phone: tone mode for this call set to %s", mode)
    return True, f"This call now uses: {_PHONE_TONE_MODE_LBL[mode]} — try a tone"

def action_phone_tone_keep() -> Tuple[bool, str]:
    chan = _phone_live_channel()
    if not chan:
        return False, "No call in progress"
    if not chan.startswith("PJSIP/"):
        return False, "Tone mode only applies to SIP networks"
    with _phone_tone_live_lock:
        mode = _phone_tone_live["mode"] if _phone_tone_live["chan"] == chan else ""
    mode = mode or _phone_tone_read(chan)
    if mode not in PHONE_TONE_MODES:
        return False, "Couldn't tell which tone mode this call is using — pick one first"
    nid = _phone_net_id_of(chan)
    with _phone_lock:
        doc = _phone_load()
        net = next((n for n in doc["networks"] if n.get("id") == nid), None)
        if net is None:
            return False, "Couldn't tell which network this call is on"
        if net.get("tone_mode") == mode:
            return True, f"{net['name']} already uses: {_PHONE_TONE_MODE_LBL[mode]}"
        net["tone_mode"] = mode
        ok, msg = _phone_write(doc)
        if not ok:
            return False, msg
    ok, msg = action_phone_apply(False)
    if not ok:
        return False, f"Saved, but Asterisk: {msg}"
    return True, f"Saved {_PHONE_TONE_MODE_LBL[mode]} for {net['name']}"

_phone_audio_cache: list = [0.0, {}]
_UPTIME_RE = re.compile(r"^(\d+):(\d{2}):(\d{2})$")

def _cs_num(tok: str) -> Optional[int]:
    m = re.match(r"^(\d+(?:\.\d+)?)([KkMm]?)$", tok or "")
    if not m:
        return None
    return int(float(m.group(1)) * {"": 1, "k": 1000, "m": 1000000}[m.group(2).lower()])

def _cs_float(tok: str) -> Optional[float]:
    try:
        return float(tok)
    except (TypeError, ValueError):
        return None

def _parse_channelstats(text: str, chan: str) -> Optional[dict]:
    short = chan.split("/", 1)[-1]
    for line in (text or "").splitlines():
        toks = line.split()
        up = next((i for i, t in enumerate(toks) if _UPTIME_RE.match(t)), None)
        if up is None or up < 1:
            continue
        cid = toks[up - 1]
        if len(cid) < 6 or not short.startswith(cid):
            continue
        nums = [_cs_num(t) for t in toks[up + 2:up + 8]]
        if len(nums) < 6 or nums[0] is None or nums[4] is None:
            continue
        h, mi, s = (int(x) for x in _UPTIME_RE.match(toks[up]).groups())
        rtt = _cs_float(toks[up + 10]) if len(toks) > up + 10 else None
        return {"codec": toks[up + 1], "secs": h * 3600 + mi * 60 + s,
                "in": nums[0], "in_lost": nums[1] or 0, "out": nums[4], "out_lost": nums[5] or 0,
                "in_jitter": _cs_float(toks[up + 5]), "out_jitter": _cs_float(toks[up + 9]) if len(toks) > up + 9 else None,
                "rtt": rtt, "confirmed": bool(rtt and rtt > 0)}
    return None

def action_phone_callcheck() -> dict:
    now = time.monotonic()
    if now - _phone_audio_cache[0] < 2.0:
        return dict(_phone_audio_cache[1])
    call = _phone_call_state(2.0)
    chan = _phone_live_chan[0]
    if call["state"] != "in_call" or not chan:
        res: dict = {"live": False}
    elif not chan.startswith("PJSIP/"):
        res = {"live": True, "sip": False}
    else:
        out, ok = ami_command("pjsip show channelstats", timeout=4)
        res = {"live": True, "sip": True, "stats": _parse_channelstats(out, chan) if ok else None}
    _phone_audio_cache[0], _phone_audio_cache[1] = now, res
    return dict(res)

def _phone_report_cmd(cmd: str, keep=None, limit: int = 40) -> List[str]:
    out, ok = ami_command(cmd, timeout=5)
    if not ok:
        return [f"  (no answer from Asterisk: {(out or '').strip()[:80]})"]
    lines = [l.rstrip() for l in (out or "").splitlines() if l.strip()]
    if keep:
        lines = [l for l in lines if keep(l)]
    return ["  " + l for l in lines[:limit]] or ["  (nothing)"]

def _phone_report_callcheck(call: dict, chk: dict) -> List[str]:
    if call.get("state") != "in_call" or not chk.get("live"):
        return ["  No call is up right now - place a call and press Refresh"]
    keyed = bool(get_state_fields("keyed")["keyed"])
    L = [f"  Radio side: {'Talking (node keyed - your audio goes to the call)' if keyed else 'Listening (node not keyed)'}"]
    path = _phone_tone_path()
    chan = _phone_live_chan[0]
    side = _phone_node_side(chan) if chan and path == "node" else None
    L.append(f"  Keypad tones: {_PHONE_TONE_PATH_LBL.get(path, path)}"
             + (f" (node side {side})" if side else " (no node side found - old way used)" if path == "node" else ""))
    if not chk.get("sip"):
        return L + ["  Audio numbers: not available for IAX2 calls"]
    s = chk.get("stats")
    if not s:
        return L + ["  Audio numbers: none yet (Asterisk didn't list this call)"]
    L.append(f"  Call length {s['secs']}s, audio format {s['codec']}")
    L.append(f"  Received {s['in']} packets (lost {s['in_lost']}), sent {s['out']} packets (lost {s['out_lost']})")
    if s.get("in_jitter") is not None or s.get("out_jitter") is not None:
        L.append(f"  Jitter in {s.get('in_jitter')}, out {s.get('out_jitter')}")
    if s.get("confirmed"):
        L.append(f"  Far end confirming it gets your audio: yes (round trip {int(s['rtt'] * 1000)} ms)")
    else:
        L.append("  Far end confirming it gets your audio: no reply yet")
    if s["secs"] >= 5 and s["out"] == 0:
        L.append("  WARNING: nothing is leaving the Pi - Asterisk isn't sending audio to this call")
    elif s["secs"] >= 5 and s["in"] == 0:
        L.append("  WARNING: nothing is arriving from the far end")
    elif s["secs"] >= 10 and s["out"] > 0 and not s.get("confirmed"):
        L.append("  NOTE: audio is leaving the Pi but the far end hasn't confirmed it - check the router note")
    L.append("  (Packets are sent even during silence, so these numbers show the path works,"
             " not that your voice is in them.)")
    return L

_REP_EP_KEYS = ("context", "dtmf_mode", "allow", "direct_media", "rtp_symmetric", "force_rport",
                "rewrite_contact", "media_address", "transport", "callerid", "from_user",
                "from_domain", "ice_support", "rtp_timeout")
_REP_TP_KEYS = ("protocol", "bind", "local_net", "external_media_address",
                "external_signaling_address", "external_signaling_port")
_REP_KV_RE = re.compile(r"^\s*([a-z0-9_]+)\s*:\s*(.*?)\s*$")

def _rep_kv(out: str, keys) -> List[Tuple[str, str]]:
    got: List[Tuple[str, str]] = []
    for line in (out or "").splitlines():
        m = _REP_KV_RE.match(line)
        if m and m.group(1) in keys:
            got.append((m.group(1), m.group(2)))
    return got

def _phone_report_endpoint(n: dict) -> List[str]:
    nid = n["id"]
    L = ["", f"Phone settings Asterisk is using for {n['name']} (pjsip show endpoint {nid}):"]
    out, ok = ami_command(f"pjsip show endpoint {nid}", timeout=5)
    if not ok:
        return L + [f"  (no answer from Asterisk: {(out or '').strip()[:80]})"]
    kv = _rep_kv(out, _REP_EP_KEYS)
    if not kv:
        return L + ["  (Asterisk doesn't know this network - press Save Phone with Restart Asterisk)"]
    L += [f"  {k:<18} {v or '(blank)'}" for k, v in kv]
    live = dict(kv).get("dtmf_mode", "")
    saved = _phone_tone_mode(n)
    if live and live != saved:
        L.append(f"  NOTE: saved Tone mode is {saved} but Asterisk has {live} loaded -"
                 f" press Save Phone with Restart Asterisk")
    chan = _phone_live_chan[0]
    if chan and _phone_net_id_of(chan) == nid:
        with _phone_tone_live_lock:
            cur = _phone_tone_live["mode"] if _phone_tone_live["chan"] == chan else ""
        L.append(f"  Tone mode on the call right now: {cur or _phone_tone_read(chan) or 'unknown'}")
    return L

def _phone_report_transports() -> List[str]:
    out, ok = ami_command("pjsip show transports", timeout=5)
    names = re.findall(r"^\s*Transport:\s+(\S+)", out or "", re.M) if ok else []
    L: List[str] = []
    for name in [x for x in names if not x.startswith("<")][:3]:
        o2, ok2 = ami_command(f"pjsip show transport {name}", timeout=5)
        kv = _rep_kv(o2, _REP_TP_KEYS) if ok2 else []
        L.append(f"  {name}:")
        L += [f"    {k:<27} {v or '(blank)'}" for k, v in kv] or ["    (no details)"]
    return L

_REP_VAR_RE = re.compile(r"(RPT_RXKEYED|RPT_TXKEYED|RPT_NUMLINKS)\s*=\s*(\d+)", re.I)

def _phone_report_sides() -> List[str]:
    L = ["", "All calls and links in Asterisk right now (core show channels concise):"]
    out, ok = ami_command("core show channels concise", timeout=5)
    if not ok:
        return L + [f"  (no answer from Asterisk: {(out or '').strip()[:80]})"]
    rows = [l.strip() for l in (out or "").splitlines() if l.count("!") >= 7]
    L += ["  " + r for r in rows[:20]] or ["  (nothing)"]
    chan = _phone_live_chan[0]
    if not chan:
        return L
    parts = next((r.split("!") for r in rows if r.split("!")[0] == chan), None)
    bid = parts[12].strip() if parts and len(parts) > 12 else ""
    L += ["", "Both sides of the call (bridge show):"]
    if not bid:
        return L + ["  WARNING: the phone call isn't joined to anything - the node side is missing"]
    o2, ok2 = ami_command(f"bridge show {bid}", timeout=5)
    if not ok2:
        return L + [f"  (no answer from Asterisk: {(o2 or '').strip()[:80]})"]
    chans = re.findall(r"^\s*Channel:\s*(\S+)", o2 or "", re.M)
    others = [c for c in chans if c != chan]
    L.append(f"  Phone side: {chan}")
    L.append(f"  Node side:  {', '.join(others) if others else 'MISSING - only the phone side is in the call'}")
    return L

def _rep_node_vars(node: str) -> Optional[dict]:
    out, ok = ami_command(f"{_AMI_RPT_SHOW_VARS} {node}", timeout=4)
    if not ok or not out or "RPT_" not in out:
        return None
    v = {k.upper(): int(n) for k, n in _REP_VAR_RE.findall(out)}
    v["links"] = _parse_rpt_links(out)
    return v

def _phone_report_nodes() -> List[str]:
    doc = _phone_load()
    pn, main = _phone_live_node(doc), str(_cfg.asl_node)
    L = ["", "Nodes (rpt show variables):"]
    got = {}
    lbls = [(n["node"], f"phone node for {n['name']}" + (" - picked" if n["id"] == doc.get("active") else ""))
            for n in doc["networks"] if n.get("node")]
    if _phone_node() not in {x[0] for x in lbls}:
        lbls.append((_phone_node(), "Phone Bridge, no network"))
    for node, lbl in lbls + [(main, "main node")]:
        if node in got:
            continue
        v = _rep_node_vars(node)
        got[node] = v
        if v is None:
            L.append(f"  {node} ({lbl}): no answer - is this node set up in rpt.conf?")
            continue
        yn = lambda k: "yes" if v.get(k) else "no"
        L.append(f"  {node} ({lbl}): hearing a signal {yn('RPT_RXKEYED')}, transmitting {yn('RPT_TXKEYED')},"
                 f" connected to {', '.join(v['links']) or 'nothing'}")
    a, b = got.get(pn), got.get(main)
    if pn != main and a is not None and b is not None:
        joined = main in a["links"] or pn in b["links"]
        L.append(f"  Phone node connected to main node: {'yes' if joined else 'no direct link - check how radio audio reaches the call'}")
    return L

_REP_LOG_FILES = ("/var/log/asterisk/messages.log", "/var/log/asterisk/messages", "/var/log/asterisk/full")
_REP_LOG_WORDS = ("pjsip", "rtp", "rpt", "iax", "sip", "dtmf", "dvs", "bridge", "chan_", "dial")
_REP_THROTTLE = ((0, "low voltage NOW"), (1, "speed limited NOW"), (2, "slowed down NOW"),
                 (3, "hot NOW"), (16, "low voltage since boot"), (17, "speed limited since boot"),
                 (18, "slowed down since boot"), (19, "hot since boot"))

def _phone_report_log(limit: int = 20) -> List[str]:
    path = next((f for f in _REP_LOG_FILES if os.path.isfile(f)), "")
    if not path:
        return ["", "Recent Asterisk warnings: no log file found"]
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 262144))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError as e:
        return ["", f"Recent Asterisk warnings: couldn't read {path} ({e.strerror})"]
    hits = [l for l in lines if ("WARNING" in l or "ERROR" in l)
            and any(w in l.lower() for w in _REP_LOG_WORDS)]
    L = ["", f"Recent Asterisk warnings about calls and nodes (last {limit}, from {path}):"]
    return L + (["  " + _strip_ctrl(l)[:220] for l in hits[-limit:]] or ["  (none)"])

def _phone_report_health() -> List[str]:
    L = ["", "Versions and Pi health:", f"  Dashboard: v{VERSION} ({BUILD_DATE})"]
    out, ok = ami_command("core show version", timeout=4)
    first = (out or "").strip().splitlines()[0] if ok and (out or "").strip() else "unknown"
    L.append(f"  Asterisk: {first[:120]}")
    pk, rc = run(["dpkg-query", "-W", "-f=${Package} ${Version}\\n", "asl3*", "allstar*"], timeout=5)
    pkgs = [l.strip() for l in (pk or "").splitlines() if len(l.split()) == 2]
    L.append(f"  ASL packages: {', '.join(pkgs[:6]) if pkgs else 'not found'}")
    try:
        up = float(Path("/proc/uptime").read_text().split()[0])
        L.append(f"  Pi up for {int(up // 86400)}d {int(up % 86400 // 3600)}h {int(up % 3600 // 60)}m")
    except (OSError, ValueError, IndexError):
        pass
    try:
        c = int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()) / 1000
        L.append(f"  CPU temperature: {c:.1f} C")
    except (OSError, ValueError):
        pass
    if shutil.which("vcgencmd"):
        o, rc = run(["vcgencmd", "get_throttled"], timeout=4)
        m = re.search(r"0x([0-9a-fA-F]+)", o or "")
        if rc == 0 and m:
            v = int(m.group(1), 16)
            bad = [txt for bit, txt in _REP_THROTTLE if v & (1 << bit)]
            L.append(f"  Power and heat: {'OK' if not bad else ', '.join(bad)} (0x{v:x})")
        else:
            L.append("  Power and heat: couldn't read")
    return L

_REP_SECRET_RE = re.compile(r"(?im)(\b(?:password|secret|md5_cred|pin)\s*[:=]\s*)\S+")

def _phone_report_hl() -> List[str]:
    doc = _phone_load()
    if not _hl_ready(doc):
        return ["  HOIP AllStar Link: off"]
    s = _hl_state(doc)
    peer, _ = ami_command(f"iax2 show peer {doc['hoip_link']['username']}", timeout=4)
    loaded = "Name" in (peer or "") and "not found" not in (peer or "").lower()
    return [f"  HOIP AllStar Link: on, callers land on node {s.get('node')}",
            f"  Asterisk has the IAX2 account: {'yes' if loaded else 'no - Save Phone again'}",
            f"  HOIP callers on now: {s.get('callers', 0)}"]

def _phone_report() -> str:
    doc = _phone_load()
    st = get_state_fields("page")
    sip = any(n["type"] in _PHONE_SIP_TYPES for n in doc["networks"])
    iax = any(n["type"] == "iax2" for n in doc["networks"])
    L = [f"ASL-DVS phone report - dashboard v{VERSION} - {datetime.now():%Y-%m-%d %H:%M:%S}",
         f"Phone node in use: {_phone_live_node(doc)}   Patch: {'on' if doc.get('patch_enabled', True) else 'off'}"
         f"   Page: {st['page']}   Asterisk running: {'yes' if _svc_is_active('asterisk') else 'NO'}", ""]
    L.append("Networks:")
    if not doc["networks"]:
        L.append("  (none)")
    for n in doc["networks"]:
        act = " (active)" if n["id"] == doc.get("active") else ""
        hp = f"{n['host']}:{n['port']}" if n.get("port") else n["host"]
        L.append(f"  {n['name']}{act} - {_PHONE_TYPE_LBL.get(n['type'], n['type'])} - {hp} - id {n['id']}")
        extra = [f"dialing {n.get('dialing')}", f"sign in {'yes' if n.get('register') else 'no'}",
                 f"incoming {n.get('incoming')}", f"test number {'set' if n.get('test_number') else 'none'}",
                 f"favorites {sum(1 for f in n.get('favorites', []) if f.get('number'))}"]
        if n["type"] in _PHONE_SIP_TYPES:
            extra += [f"tone mode {_phone_tone_mode(n)}",
                      f"home network {n.get('lan_net') or 'blank'}", f"public IP {n.get('wan_ip') or 'blank'}"]
        L.append("    " + ", ".join(extra))
    call = _phone_call_state(0.0)
    chk = action_phone_callcheck()
    stats = chk.get("stats") if chk.get("live") and chk.get("sip") else None
    L += ["", f"Pi address: {_phone_pi_lan_ip() or 'unknown'}"]
    adv = _phone_router_advice(doc)
    if adv.get("text") and stats and stats.get("confirmed"):
        L.append("Router note: not needed right now - the far end is confirming it gets your audio")
    else:
        L.append("Router note: " + (adv.get("text") or "none"))
        L += ["    " + l for l in adv.get("lines", [])]
    L += ["", "Call now: " + json.dumps(call)]
    L += ["", "Call check (the same numbers the keypad shows):"]
    L += _phone_report_callcheck(call, chk)
    L += ["", "HOIP AllStar Link:"] + _phone_report_hl()
    L += _phone_report_sides()
    L += _phone_report_nodes()
    if sip:
        L += ["", "Sign-in (pjsip show registrations):"]
        L += _phone_report_cmd("pjsip show registrations", keep=lambda l: "dvs" in l)
        L += ["", "Far end responding (pjsip show contacts):"]
        L += _phone_report_cmd("pjsip show contacts", keep=lambda l: "dvs" in l)
        L += ["", "Call audio (pjsip show channelstats):"]
        L += _phone_report_cmd("pjsip show channelstats", keep=lambda l: "dvs" in l or "Count" in l)
        L += ["", "Connection settings (pjsip show transports):"]
        L += _phone_report_cmd("pjsip show transports",
                               keep=lambda l: "Transport:" in l and "<" not in l)
        L += _phone_report_transports()
        for n in doc["networks"]:
            if n["type"] in _PHONE_SIP_TYPES:
                L += _phone_report_endpoint(n)
    if iax:
        L += ["", "Sign-in (iax2 show registry):"]
        L += _phone_report_cmd("iax2 show registry")
    L += ["", "Modules:"]
    for mod in ("app_senddtmf.so", "chan_pjsip.so", "chan_iax2.so", "app_rpt.so"):
        out, ok = ami_command(f"module show like {mod.split('.')[0]}", timeout=5)
        L.append(f"  {mod}: {'loaded' if ok and mod in (out or '') else 'not loaded'}")
    L += _phone_report_log()
    L += _phone_report_health()
    text = "\n".join(L) + "\n"
    for n in doc["networks"]:
        for k in ("password", "pin", "voicemail_pin"):
            v = str(n.get(k) or "")
            if len(v) >= 3:
                text = text.replace(v, "****")
    return _REP_SECRET_RE.sub(lambda m: m.group(1) + "****", text)

def action_phone_report() -> dict:
    try:
        return {"ok": True, "text": _phone_report()}
    except Exception as e:
        log.exception("phone report failed")
        return {"ok": False, "text": f"Couldn't build the report: {e}"}

def action_phone_hangup() -> Tuple[bool, str]:
    n = _phone_hangup_all()
    return True, "Call ended" if n else "No call to hang up"

def action_phone_patch(on: bool) -> Tuple[bool, str]:
    with _phone_lock:
        doc = _phone_load()
        doc["patch_enabled"] = bool(on)
        ok, msg = _phone_write(doc)
        if not ok:
            return False, msg
    _phone_astdb("put", "patch", "1" if on else "0")
    for nd in _phone_all_nodes():
        ami_command(f"rpt cmd {nd} cop {9 if on else 10} x", timeout=4)
    if not on:
        _phone_hangup_all()
    return True, "Phone patch on" if on else "Phone patch off — outgoing dialing is blocked"

def _phone_req_dir() -> None:
    try:
        os.makedirs(_TONE_REQ_DIR, exist_ok=True)
        os.chmod(os.path.dirname(_TONE_REQ_DIR), 0o755)
        try:
            import grp
            os.chown(_TONE_REQ_DIR, 0, grp.getgrnam("asterisk").gr_gid)
        except (KeyError, ImportError, PermissionError, OSError):
            pass
        os.chmod(_TONE_REQ_DIR, 0o770)
    except OSError as e:
        log.warning("phone: couldn't make %s: %s", _TONE_REQ_DIR, e)

def _phone_radio_code_clash() -> List[str]:
    try:
        live = _ph_strip(_ph_read(_ph_path("rpt.conf")) or "")
    except Exception:
        return []
    secs: Dict[str, dict] = {}
    cur = None
    for raw in live.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^\[([^\]]+)\](?:\(([^)]*)\))?", line)
        if m:
            cur = secs.setdefault(m.group(1).strip(), {"tmpl": (m.group(2) or "").strip(), "keys": {}})
            continue
        if cur is not None and "=" in line:
            k, v = line.split("=", 1)
            cur["keys"].setdefault(k.strip(), v.strip())
    node = secs.get(str(_cfg.asl_node))
    if not node:
        return []
    fname = node["keys"].get("functions") or secs.get(node["tmpl"], {}).get("keys", {}).get("functions") or "functions"
    table = secs.get(fname, {}).get("keys", {})
    codes = [f"{_TONE_CODE_PFX}{i}" for i in range(8)]
    return sorted(k for k in table if k and all(ch.isdigit() or ch in "*#ABCD" for ch in k)
                  and any(c.startswith(k) or k.startswith(c) for c in codes))

def _phone_radio_code(code: str) -> None:
    if _phone_call_state(0.0)["state"] != "in_call":
        _phone_set_notice(f"Radio code *{_TONE_CODE_PFX}{code} ignored — no call is up")
        return
    if code in _TONE_CODE_FIXED:
        tones, label = _TONE_CODE_FIXED[code]
    else:
        idx = int(code) - 3
        doc = _phone_load()
        nid = _phone_net_id_of(_phone_live_chan[0]) or doc.get("active", "")
        net = next((n for n in doc["networks"] if n.get("id") == nid), None)
        btns = (net or {}).get("buttons", [])
        if idx >= len(btns):
            _phone_set_notice(f"Radio code *{_TONE_CODE_PFX}{code}: no tone button {idx + 1} on "
                              f"{net['name'] if net else 'this network'}")
            return
        tones, label = btns[idx]["tones"], btns[idx]["label"]

    def go():
        ok, msg = _phone_send_tones(tones)
        _phone_set_notice(f"Sent {label} from the radio" if ok else msg)
    threading.Thread(target=go, name="phone-radio-code", daemon=True).start()

def _phone_radio_codes_poll() -> None:
    try:
        names = os.listdir(_TONE_REQ_DIR)
    except FileNotFoundError:
        return
    except OSError:
        return
    for nm in names:
        try:
            os.unlink(os.path.join(_TONE_REQ_DIR, nm))
        except OSError:
            continue
        m = re.fullmatch(r"code([0-7])", nm)
        if m:
            log.info("phone: radio tone code *%s%s", _TONE_CODE_PFX, m.group(1))
            _phone_radio_code(m.group(1))

def _phone_sync_open(page: str) -> None:
    global _phone_open_state
    want = (page == "PHONE")
    if want == _phone_open_state:
        return
    if want:
        doc = _phone_load()
        okk = _phone_astdb("put", "open", "1")
        if doc.get("active"):
            _phone_astdb("put", "active", doc["active"])
        _phone_astdb("put", "patch", "1" if doc.get("patch_enabled", True) else "0")
    else:
        okk = _phone_astdb("del", "open")
    if okk:
        _phone_open_state = want


_tot: dict = {"want_off": None, "ena": None, "error": "", "last_check": 0.0,
              "keyed_since": 0.0, "capped": False, "last_poll": 0.0}
_TOT_ENA_RE = re.compile(r"\btot_ena\s*=\s*(\d)")
_TOT_TX_RE = re.compile(r"RPT_TXKEYED\s*=\s*(\d)")

def _tot_read(node: str) -> Tuple[Optional[bool], Optional[bool]]:
    out, ok = ami_command(f"rpt xnode {node}", timeout=3)
    if not ok or not out:
        return None, None
    a, b = _TOT_ENA_RE.search(out), _TOT_TX_RE.search(out)
    return (a.group(1) == "1") if a else None, (b.group(1) == "1") if b else None

def _tot_fun_code(node: str, cop: int) -> str:
    try:
        txt = Path(ASL_CONF).read_text(errors="replace")
    except Exception:
        return ""
    secs: Dict[str, Dict[str, str]] = {}
    tmpl: Dict[str, str] = {}
    cur = None
    for raw in txt.splitlines():
        ln = raw.split(";", 1)[0].strip()
        m = re.match(r"^\[([^\]]+)\]\s*(?:\(([^)]*)\))?", ln)
        if m:
            cur = m.group(1).strip()
            secs.setdefault(cur, {})
            tmpl[cur] = (m.group(2) or "").strip()
            continue
        if cur and "=" in ln:
            k, v = (x.strip() for x in ln.split("=", 1))
            secs[cur].setdefault(k.lower(), v)
    def get(sec: str, key: str, depth: int = 0) -> str:
        s = secs.get(sec, {})
        if key in s or depth > 3:
            return s.get(key, "")
        return get(tmpl.get(sec, ""), key, depth + 1) if tmpl.get(sec) else ""
    table = get(node, "functions") or "functions"
    seen, t_ = set(), table
    while t_ and t_ not in seen:
        seen.add(t_)
        for k, v in secs.get(t_, {}).items():
            if re.fullmatch(r"cop\s*,\s*%d" % cop, v.replace(" ", "")) or v.replace(" ", "") == f"cop,{cop}":
                return k
        t_ = tmpl.get(t_, "")
    return ""

def _tot_set(node: str, enable: bool) -> Tuple[bool, str]:
    cop = 7 if enable else 8
    ami_command(f"rpt cmd {node} cop {cop}", timeout=3)
    time.sleep(0.3)
    ena, _tx = _tot_read(node)
    if ena is enable:
        return True, ""
    code = _tot_fun_code(node, cop)
    if code:
        ami_command(f"rpt fun {node} *{code}", timeout=3)
        time.sleep(0.5)
        ena, _tx = _tot_read(node)
        if ena is enable:
            return True, ""
    if ena is None:
        return False, "couldn't read the node's time-out state"
    return False, (f"node {node} didn't take the time-out {'on' if enable else 'off'} command"
                   + ("" if code else f" -- add a cop,{cop} code to its function list in rpt.conf"))

def _tot_sync(page: str) -> None:
    node = str(_cfg.asl_node or "")
    if not node or node == "0":
        return
    doc = _phone_doc()
    opt = doc.get("tot_phone_off", True) is not False
    on_phone = page == "PHONE"
    if not on_phone:
        _tot["capped"] = False
        _tot["keyed_since"] = 0.0
    want_off = on_phone and opt and not _tot["capped"]
    if want_off == _tot["want_off"]:
        _tot_watch(node, doc, want_off)
        return
    ok, err = _tot_set(node, not want_off)
    if ok:
        _tot["want_off"], _tot["ena"], _tot["error"] = want_off, not want_off, ""
        log.info("phone: transmitter time-out %s on node %s", "off (Phone tab)" if want_off else "on", node)
    else:
        _tot["error"] = err
        log.warning("phone: time-out %s failed: %s", "off" if want_off else "on", err)
        _tot["want_off"] = want_off

_TOT_CHECK_SEC = 60.0
_TOT_CAP_POLL = 5.0

def _tot_watch(node: str, doc: dict, want_off: bool) -> None:
    now = time.monotonic()
    if not want_off:
        if now - _tot["last_check"] < _TOT_CHECK_SEC:
            return
        _tot["last_check"] = now
        ena, _tx = _tot_read(node)
        if ena is False:
            ok, err = _tot_set(node, True)
            log.warning("phone: transmitter time-out was off on node %s outside the Phone tab -- %s",
                        node, "turned back on" if ok else "could not turn it on: " + err)
            _tot["error"] = "" if ok else err
        return
    if now - _tot["last_poll"] < _TOT_CAP_POLL:
        return
    _tot["last_poll"] = now
    _ena, tx = _tot_read(node)
    if not tx:
        _tot["keyed_since"] = 0.0
        return
    if not _tot["keyed_since"]:
        _tot["keyed_since"] = now
        return
    try:
        cap = max(5, min(60, int(doc.get("tot_cap_min", 15)))) * 60
    except (TypeError, ValueError):
        cap = 15 * 60
    if now - _tot["keyed_since"] >= cap:
        ok, err = _tot_set(node, True)
        _tot["capped"], _tot["want_off"] = True, False
        _tot["error"] = "" if ok else err
        _phone_set_notice(f"The radio was keyed over {cap // 60} minutes, so the transmitter time-out is back on", 30.0)
        log.warning("phone: safety cap -- node %s keyed %d min with the time-out off; %s", node, cap // 60,
                    "time-out back on" if ok else "could not turn it on: " + err)

def _tot_status() -> dict:
    if _tot["want_off"] is None:
        return {}
    return {"off": bool(_tot["want_off"]) and not _tot["error"], "error": _tot["error"], "capped": _tot["capped"]}

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
            f"enabled_tabs={chr(44).join(_cfg.enabled_tabs_sorted)}\n",
            f"cpuweight_enabled={str(_cfg.cpuweight_enabled).lower()}\n\n",
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
        lines.append(f"network_url={_MODE_NET_URL_DEFAULTS['FCS']}\n")
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

def _lh_url_ip_http(url: str) -> str:
    u = url.strip()
    if not u:
        return u
    m = re.match(r"(?i)^https?://(.*)$", u)
    if m:
        rest = m.group(1)
    elif "://" in u:
        return u
    else:
        rest = u
    host = re.split(r"[/?#]", rest, maxsplit=1)[0].rsplit("@", 1)[-1]
    if host.startswith("["):
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return u
    return "http://" + rest

def _validate_tg_entries(entries: list) -> Tuple[Optional[list], Optional[str]]:
    out = []
    for i, e in enumerate(entries):
        mode = str(e.get("mode", "")).strip().upper()


        name = _strip_ctrl(str(e.get("name", "")).strip())
        tg   = _strip_ctrl(str(e.get("tg",   "")).strip())
        url  = _strip_ctrl(str(e.get("url",  "")).strip().rstrip("/"))
        url  = _lh_url_ip_http(url)
        if mode == "FCS":
            url = _fcs_lh_fix(url)
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
        if _is_bridge_node(node):
            return None, f"Node row {i+1}: " + _bridge_reject_msg(node, "an ASL favorite")
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
        if len(node) > 7:
            return None, f"Echo row {i+1}: EchoLink node numbers are 1-7 digits (got '{node}')"
        if _is_bridge_node(_echolink_to_asl(node)):
            return None, f"Echo row {i+1}: " + _bridge_reject_msg(_echolink_to_asl(node),
                                                                 "an EchoLink favorite")
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

_conf_lock = threading.RLock()

def _conf_locked(fn):
    def wrapper(*args, **kwargs):
        with _conf_lock:
            return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__  = fn.__doc__
    return wrapper

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
            f"enabled_tabs={','.join(_cfg.enabled_tabs_sorted)}\n",
            f"cpuweight_enabled={str(_cfg.cpuweight_enabled).lower()}\n\n",
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
            lines.append(f"network_url={get_state().mode_net_urls.get('FCS', _MODE_NET_URL_DEFAULTS['FCS'])}\n")
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
        "cpuweight_enabled":    _cfg.cpuweight_enabled,
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

@_conf_locked
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
    if "cpuweight_enabled" in cfg:
        apply_cfg["cpuweight_enabled"] = bool(cfg["cpuweight_enabled"])
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

@_conf_locked
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

@_conf_locked
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

@_conf_locked
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

@_conf_locked
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

_DVS_MODE_TIMEOUT_SEC  = 40
_DVS_TUNE_TIMEOUT_SEC  = 40
_DVS_OTHER_TIMEOUT_SEC = 10

_DVS_TIMEOUT = "__dvs_timeout__"

def _dvs_timed_out(out) -> bool:
    return out == _DVS_TIMEOUT

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
    if subcmd == "mode":
        _tmo = _DVS_MODE_TIMEOUT_SEC
    elif subcmd == "tune":
        _tmo = _DVS_TUNE_TIMEOUT_SEC
    else:
        _tmo = _DVS_OTHER_TIMEOUT_SEC
    out, rc = run(cmd, timeout=_tmo)
    if rc == _RC_TIMEOUT:
        return False, _DVS_TIMEOUT
    return rc == 0, out

def _echolink_to_asl(node: str) -> str:
    return "3" + str(node).strip().zfill(6)

def _connect(node: str) -> None:
    _asterisk(f"rpt cmd {_cfg.asl_node} ilink 3 {node}")

def _disconnect(node: str) -> None:
    _asterisk(f"rpt cmd {_cfg.asl_node} ilink 1 {node}")

def _disconnect_perm(node: str) -> None:
    _asterisk(f"rpt cmd {_cfg.asl_node} ilink 11 {node}")

def _bridge_set() -> Set[str]:
    s = set(filter(None, _cfg.bridge_nodes))
    try:
        s.update(_phone_all_nodes())
    except Exception as e:
        log.warning("bridge set: phone nodes unreadable: %s", e)
    return s

def _slot_node(slot: Optional[int]) -> str:
    if slot is None:
        return ""
    if slot == BRIDGE_SLOT_PHONE:
        if not _phone_on():
            return ""
        try:
            return _phone_live_node()
        except Exception as e:
            log.warning("bridge slot: phone node unreadable: %s", e)
    return _cfg.bridge_nodes[slot] if slot < len(_cfg.bridge_nodes) else ""

def _bridge_slot_of(node: str) -> Optional[int]:
    node = str(node).strip()
    if not node:
        return None
    for slot, nd in enumerate(_cfg.bridge_nodes):
        if nd and nd == node:
            return slot
    try:
        if node in _phone_all_nodes():
            return BRIDGE_SLOT_PHONE
    except Exception:
        pass
    return None

def _is_bridge_node(node: str) -> bool:
    return _bridge_slot_of(node) is not None

def _bridge_reject_msg(node: str, what: str) -> str:
    slot = _bridge_slot_of(node)
    label = BRIDGE_SLOT_LABELS[slot] if slot is not None and slot < len(BRIDGE_SLOT_LABELS) else "bridge"
    return (f"Node {node} is bridge slot {(slot or 0)+1} ({label}) — it is managed by "
            f"the dashboard and cannot be used as {what}")

def _drop_one_link(node: str, perms: Optional[FrozenSet[str]] = None) -> bool:
    if perms is None:
        perms = _read_perm_links()
    if node in perms:
        _disconnect_perm(node)
        return True
    _disconnect(node)
    return False

_LINK_DROP_PACING_SEC = 0.25
_LINK_DROP_MAX        = 16

def _ilink6_pair() -> None:
    _asterisk(f"rpt cmd {_cfg.asl_node} ilink 6")
    time.sleep(0.2)
    _asterisk(f"rpt cmd {_cfg.asl_node} ilink 6")
    time.sleep(0.2)

def _drop_links(keep: Optional[str] = None, what: str = "drop-links") -> Optional[List[str]]:
    linked = _query_linked_nodes()
    if linked is None:
        log.warning("%s: link query failed — falling back to ilink 6", what)
        _ilink6_pair()
        _log_teardown_survivors_async(what + " (ilink 6 fallback)")
        return None

    perms      = _read_perm_links()
    bridge_set = _bridge_set()
    dropped: List[str] = []

    for nd in linked:
        if nd == keep:
            continue
        if len(dropped) >= _LINK_DROP_MAX:
            log.warning("%s: hit drop cap of %d — leaving the rest to the poller",
                        what, _LINK_DROP_MAX)
            break
        if _drop_one_link(nd, perms):
            log.info("%s: dropped permanent link %s (ilink 11)%s", what, nd,
                     " [bridge slot]" if nd in bridge_set else "")
        dropped.append(nd)
        time.sleep(_LINK_DROP_PACING_SEC)

    if not dropped:
        log.info("%s: nothing to drop (linked=%s, keep=%s)", what, linked or "none", keep)
        return dropped

    _log_teardown_survivors_async(f"{what} keep={keep or 'none'}")
    return dropped

def _disconnect_all() -> None:
    _drop_links(keep=None, what="disconnect-all")

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

class _ListCache:

    def __init__(self, ttl: float, build, on_missing=None, sticky: bool = False):
        self.ttl         = ttl
        self._build      = build
        self._on_missing = on_missing
        self._sticky     = sticky
        self._lock       = threading.Lock()
        self._value      = None
        self._ts         = 0.0
        self._warned     = False

    def get(self):
        with self._lock:
            if self._value is not None and (time.monotonic() - self._ts) < self.ttl:
                return self._value
            prev = self._value
        value, missing = self._build(prev)
        with self._lock:
            self._value  = value
            self._ts     = time.monotonic()
            warn         = missing and not self._warned
            self._warned = missing or (self._sticky and self._warned)
        if warn and self._on_missing:
            self._on_missing(value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._value, self._ts = None, 0.0

_YSF_HOSTS_PATH  = "/var/lib/mmdvm/YSFHosts.txt"
_YSF_HOSTS_TTL   = 300.0

_YSFGW_INI_PATH   = "/opt/YSFGateway/YSFGateway.ini"
_YSFGW_DIR        = "/opt/YSFGateway"
_YSFGW_INI_TTL    = 300.0
_ysfgw_paths_cache: "dict | None" = None
_ysfgw_paths_ts   = 0.0
_ysfgw_paths_lock = threading.Lock()

_YSF_ID_RE        = re.compile(r"\d{1,5}")
_YSF_CC_RE        = re.compile(r"^([A-Z]{2,3})(?=$|[\s\-_./:,|()\[\]])")
_YSF_CC_ALIASES   = {"USA": "US", "GBR": "GB", "DEU": "DE", "ITA": "IT",
                     "ESP": "ES", "FRA": "FR", "CAN": "CA", "AUS": "AU",
                     "BRA": "BR", "MEX": "MX", "JPN": "JP", "NLD": "NL"}
_YSF_CC_CODES     = frozenset((
    "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI "
    "BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN "
    "CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK "
    "FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM "
    "HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN "
    "KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK "
    "ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP "
    "NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW "
    "SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF "
    "TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI "
    "VN VU WF WS YE YT ZA ZM ZW UK EU").split())


_FCS_HOSTS_PATH  = "/var/lib/mmdvm/FCSRooms.txt"
_FCS_HOSTS_TTL   = 300.0
_FCS_ID_RE       = re.compile(r"FCS(\d{3})(\d{2})")
_FCS_PLACEHOLDER = "nn"
_FCS_LH_HOST_FMT = "fcs{sid}.xreflector.net"
_FCS_LH_PATH     = ""
_FCS_LH_SCHEMES  = {"001": "http", "002": "https", "003": "http", "004": "http"}
_FCS_LH_HOST_RE  = re.compile(r"(?i)^(?:https?://)?fcs(\d{3})\.xreflector\.net(?:[:/?#].*)?$")

def _fcs_lh_url(sid: str) -> str:
    scheme = _FCS_LH_SCHEMES.get(sid)
    if not scheme:
        return ""
    return scheme + "://" + _FCS_LH_HOST_FMT.format(sid=sid) + _FCS_LH_PATH

def _fcs_lh_fix(url: str) -> str:
    m = _FCS_LH_HOST_RE.match((url or "").strip())
    if m and m.group(1) in _FCS_LH_SCHEMES:
        return _fcs_lh_url(m.group(1))
    return url

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

def _gw_path(val: str, base_dir: str) -> str:
    val = _strip_ctrl(val).strip().strip('"').strip("'")
    if not val:
        return ""
    if not os.path.isabs(val):
        val = os.path.join(base_dir, val)
    return os.path.normpath(val)

def _parse_ysfgw_ini_paths(lines, base_dir: str = _YSFGW_DIR) -> dict:
    out = {"ysf": "", "fcs": ""}
    section = ""
    for raw in lines:
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            continue
        if "=" not in line or "network" not in section:
            continue
        key, _, val = line.partition("=")
        key = key.strip().lower()
        if key in ("hosts", "ysfhosts") and not out["ysf"]:
            out["ysf"] = _gw_path(val, base_dir)
        elif key in ("rooms", "fcsrooms") and not out["fcs"]:
            out["fcs"] = _gw_path(val, base_dir)
    return out

def _ysfgw_ini_paths() -> dict:
    global _ysfgw_paths_cache, _ysfgw_paths_ts
    with _ysfgw_paths_lock:
        if (_ysfgw_paths_cache is not None
                and (time.monotonic() - _ysfgw_paths_ts) < _YSFGW_INI_TTL):
            return _ysfgw_paths_cache
    try:
        with open(_YSFGW_INI_PATH, "r", encoding="utf-8", errors="replace") as f:
            result = _parse_ysfgw_ini_paths(f, os.path.dirname(_YSFGW_INI_PATH))
    except OSError:
        result = {"ysf": "", "fcs": ""}
    with _ysfgw_paths_lock:
        _ysfgw_paths_cache = result
        _ysfgw_paths_ts    = time.monotonic()
    return result

def _pick_list_path(ini_val: str, fallback: str) -> str:
    cands: "list[str]" = []
    for p in (ini_val,
              os.path.join(_YSFGW_DIR, os.path.basename(ini_val or fallback)),
              fallback):
        if p and p not in cands:
            cands.append(p)
    for p in cands:
        if os.path.isfile(p):
            return p
    return ini_val or fallback

def _ysf_hosts_path() -> str:
    return _pick_list_path(_ysfgw_ini_paths()["ysf"], _YSF_HOSTS_PATH)

def _fcs_hosts_path() -> str:
    return _pick_list_path(_ysfgw_ini_paths()["fcs"], _FCS_HOSTS_PATH)

def _ysf_country(name: str) -> str:
    head = _strip_ctrl(name or "").strip().upper()
    m = _YSF_CC_RE.match(head)
    if not m:
        return ""
    code = m.group(1)
    code = _YSF_CC_ALIASES.get(code, code)
    return code if code in _YSF_CC_CODES else ""

def _ysf_port_ok(port: str) -> bool:
    return port.isdigit() and 0 < int(port) < 65536

def _parse_ysf_hosts(lines) -> "tuple[dict, dict]":
    names: "dict[str, str]" = {}
    rows: "list[list]" = []
    seen: "set[str]" = set()
    counts: "dict[str, int]" = {}
    updated = ""
    stats = {"reflectors": 0, "no_address": 0, "duplicates": 0, "malformed": 0}
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if not updated:
                m = re.match(r"#\s*Last Update:\s*(.+)$", line, re.I)
                if m:
                    updated = _strip_ctrl(m.group(1)).strip()
            continue
        parts = [_strip_ctrl(p).strip() for p in line.split(";")]
        rid  = parts[0]
        name = parts[1] if len(parts) > 1 else ""
        if not _YSF_ID_RE.fullmatch(rid) or not name:
            stats["malformed"] += 1
            continue
        if rid in seen:
            stats["duplicates"] += 1
            continue
        seen.add(rid)
        names.setdefault(rid, name)
        names.setdefault(name, name)
        desc = parts[2] if len(parts) > 2 else ""
        addr = parts[3] if len(parts) > 3 else ""
        port = parts[4] if len(parts) > 4 else ""
        if not addr or any(c.isspace() for c in addr) or not _ysf_port_ok(port):
            stats["no_address"] += 1
            continue
        names.setdefault(f"{addr}:{port}".lower(), name)
        link = ""
        for extra in parts[6:]:
            if re.match(r"(?i)^https?://\S+$", extra):
                link = extra
                break
        cc = _ysf_country(name)
        counts[cc] = counts.get(cc, 0) + 1
        rows.append([rid, name, desc, addr, port, cc, link])
    rows.sort(key=lambda r: (len(r[0]) != 5, r[0].zfill(5)))
    stats["reflectors"] = len(rows)
    countries = sorted(([c, n] for c, n in counts.items() if c),
                       key=lambda x: x[0])
    if counts.get(""):
        countries.append(["", counts[""]])
    payload = {"ok": True, "found": True, "path": "", "reflectors": rows,
               "countries": countries, "updated": updated, "mtime": 0,
               "note": "", "stats": stats}
    return payload, names

def _build_ysf_data(_prev):
    path = _ysf_hosts_path()
    empty = {"ok": True, "found": False, "path": path, "reflectors": [],
             "countries": [], "updated": "", "mtime": 0, "note": "",
             "stats": {"reflectors": 0, "no_address": 0, "duplicates": 0,
                       "malformed": 0}}
    if path.lower().endswith(".json"):
        payload = dict(empty)
        payload["note"] = "json"
        return (payload, {}), True
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            payload, names = _parse_ysf_hosts(f)
            payload["mtime"] = int(os.fstat(f.fileno()).st_mtime)
            payload["path"]  = path
    except OSError:
        payload = dict(empty)
        payload["note"] = "missing"
        return (payload, {}), True
    return (payload, names), False

def _ysf_missing(value) -> None:
    payload = value[0]
    path = payload["path"]
    what = ("is a .json list, which this dashboard does not read yet"
            if payload["note"] == "json" else "was not found")
    log.warning("YSF host list %s at %s — YSF names and the reflector "
                "menu will be empty", what, path)
    st = get_state()
    set_state(conf_warnings=list(st.conf_warnings) + [
        f"YSF host list {what} at {path} — room names will show as raw TG IDs"
    ])

_ysf_cache = _ListCache(_YSF_HOSTS_TTL, _build_ysf_data, _ysf_missing, sticky=True)

def _load_ysf_data() -> "tuple[dict, dict]":
    return _ysf_cache.get()

def _load_ysf_hosts() -> "dict[str, str]":
    return _load_ysf_data()[1]

def action_get_ysf_hosts() -> dict:
    return _load_ysf_data()[0]

def _resolve_ysf_name(tg: str, ambe_mode: str) -> str:
    tg = str(tg or "").strip()
    if (ambe_mode.upper() in ("YSFN", "YSFW")
            and len(tg) == 6 and tg.isdigit() and tg.startswith("9")):
        return ""
    names = _load_ysf_hosts()
    return names.get(tg, "") or names.get(tg.lower(), "")

_TGH_GATEWAYS = {
    "P25":  {"ini": "/opt/P25Gateway/P25Gateway.ini",   "dir": "/opt/P25Gateway",
             "fallback": "/var/lib/mmdvm/P25Hosts.txt"},
    "NXDN": {"ini": "/opt/NXDNGateway/NXDNGateway.ini", "dir": "/opt/NXDNGateway",
             "fallback": "/var/lib/mmdvm/NXDNHosts.txt"},
}
_TGH_TTL        = 300.0
_TGH_DATE_RE    = re.compile(r"#\s*(?:Generated|Last Update):\s*(.+)$", re.I)

def _parse_tgh_ini_paths(lines, base_dir: str) -> dict:
    out = {"main": "", "private": ""}
    alt = ""
    for raw in lines:
        line = raw.strip()
        if not line or line[0] in "#;[" or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip().lower()
        path = _gw_path(val, base_dir)
        if not path:
            continue
        if key == "hostsfile1" and not out["main"]:
            out["main"] = path
        elif key == "hostsfile2" and not out["private"]:
            out["private"] = path
        elif key in ("hosts", "hostsfile") and not alt:
            alt = path
    if not out["main"]:
        out["main"] = alt
    return out

def _tgh_paths(mode: str) -> "tuple[str, str]":
    gw = _TGH_GATEWAYS[mode]
    try:
        with open(gw["ini"], "r", encoding="utf-8", errors="replace") as f:
            p = _parse_tgh_ini_paths(f, gw["dir"])
    except OSError:
        p = {"main": "", "private": ""}
    cands: "list[str]" = []
    for c in (p["main"],
              os.path.join(gw["dir"], os.path.basename(p["main"] or gw["fallback"])),
              gw["fallback"]):
        if c and c not in cands:
            cands.append(c)
    main = next((c for c in cands if os.path.isfile(c)), p["main"] or gw["fallback"])
    priv = p["private"] if p["private"] and os.path.isfile(p["private"]) else ""
    if priv == main:
        priv = ""
    return main, priv

def _parse_tg_hosts(lines, private: bool = False) -> dict:
    rows: "list[list]" = []
    seen: "set[str]" = set()
    updated = ""
    stats = {"reflectors": 0, "duplicates": 0, "malformed": 0}
    for raw in lines:
        line = _strip_ctrl(raw.replace("\t", " ")).strip()
        if not line:
            continue
        if line.startswith("#"):
            if not updated:
                m = _TGH_DATE_RE.match(line)
                if m:
                    updated = m.group(1).strip()
            continue
        parts = line.split()
        if (len(parts) < 3 or not parts[0].isdigit() or len(parts[0]) > 8
                or not _ysf_port_ok(parts[2])):
            stats["malformed"] += 1
            continue
        tg = str(int(parts[0]))
        if tg in seen:
            stats["duplicates"] += 1
            continue
        seen.add(tg)
        rows.append([tg, parts[1], parts[2], 1 if private else 0])
    stats["reflectors"] = len(rows)
    return {"rows": rows, "updated": updated, "stats": stats}

def _build_tg_hosts(mode: str):
    main, priv = _tgh_paths(mode)
    rows: "list[list]" = []
    seen: "set[str]" = set()
    stats = {"reflectors": 0, "duplicates": 0, "malformed": 0}
    updated, mtime, found = "", 0, False
    used: "list[str]" = []
    for path, is_priv in ((priv, True), (main, False)):
        if not path:
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                part = _parse_tg_hosts(f, private=is_priv)
                st_m = int(os.fstat(f.fileno()).st_mtime)
        except OSError:
            continue
        used.append(path)
        if not is_priv:
            found, updated, mtime = True, part["updated"], st_m
        stats["malformed"]  += part["stats"]["malformed"]
        stats["duplicates"] += part["stats"]["duplicates"]
        for r in part["rows"]:
            if r[0] in seen:
                stats["duplicates"] += 1
                continue
            seen.add(r[0])
            rows.append(r)
    rows.sort(key=lambda r: int(r[0]))
    stats["reflectors"] = len(rows)
    result = {"ok": True, "found": found, "mode": mode, "path": main,
              "paths": used, "reflectors": rows if found else [],
              "updated": updated, "mtime": mtime, "stats": stats}
    return result, not found

_tgh_caches: "dict[str, _ListCache]" = {}
_tgh_caches_lock = threading.Lock()

def _tgh_cache(mode: str) -> _ListCache:
    with _tgh_caches_lock:
        c = _tgh_caches.get(mode)
        if c is None:
            c = _tgh_caches[mode] = _ListCache(
                _TGH_TTL, lambda _prev, m=mode: _build_tg_hosts(m),
                lambda r, m=mode: log.warning(
                    "%s host list not found at %s — the %s talkgroup menu will be empty",
                    m, r["path"], m))
        return c

def _load_tg_hosts(mode: str) -> dict:
    return _tgh_cache(mode).get()

def action_get_tg_hosts(mode: str) -> dict:
    return _load_tg_hosts(mode)

_STFU_TG_PATH   = "/var/lib/mmdvm/TGList_BM.txt"
_STFU_TG_TTL    = 300.0
_STFU_NAME_MAX  = 64
_STFU_DESC_MAX  = 96
_STFU_DATE_RE   = re.compile(r"#.*?File updated on\s+(.+?)\s*$", re.I)

def _parse_stfu_tgs(lines) -> dict:
    rows: "list[list]" = []
    seen: "set[str]" = set()
    updated = ""
    stats = {"reflectors": 0, "malformed": 0, "duplicates": 0, "other": 0}
    for raw in lines:
        line = _strip_ctrl(str(raw)).strip()
        if not line:
            continue
        if line.startswith("#"):
            if not updated:
                m = _STFU_DATE_RE.match(line)
                if m:
                    updated = m.group(1)[:64]
            continue
        parts = [p.strip() for p in line.split(";")]
        if (len(parts) < 3 or not parts[0].isdigit() or len(parts[0]) > 8
                or parts[1] not in ("0", "1", "2")):
            stats["malformed"] += 1
            continue
        if parts[1] != "0":
            stats["other"] += 1
            continue
        tg = str(int(parts[0]))
        if tg in seen:
            stats["duplicates"] += 1
            continue
        seen.add(tg)
        name = parts[2][:_STFU_NAME_MAX] or f"TG{tg}"
        desc = (parts[3] if len(parts) > 3 else "")[:_STFU_DESC_MAX]
        rows.append([tg, name, desc])
    rows.sort(key=lambda r: int(r[0]))
    stats["reflectors"] = len(rows)
    return {"rows": rows, "updated": updated, "stats": stats}

def _build_stfu_tgs(_prev):
    found = True
    try:
        with open(_STFU_TG_PATH, "r", encoding="utf-8", errors="replace") as f:
            part = _parse_stfu_tgs(f)
            mtime = int(os.fstat(f.fileno()).st_mtime)
    except OSError:
        found, mtime = False, 0
        part = {"rows": [], "updated": "",
                "stats": {"reflectors": 0, "malformed": 0, "duplicates": 0, "other": 0}}
    result = {"ok": True, "found": found, "mode": "STFU", "path": _STFU_TG_PATH,
              "paths": [_STFU_TG_PATH] if found else [],
              "reflectors": part["rows"], "updated": part["updated"],
              "mtime": mtime, "stats": part["stats"]}
    return result, not found

_stfu_cache = _ListCache(_STFU_TG_TTL, _build_stfu_tgs,
                         lambda r: log.warning("BrandMeister talkgroup list not found at %s "
                                               "— the STFU talkgroup menu will be empty",
                                               r["path"]))

def _load_stfu_tgs() -> dict:
    return _stfu_cache.get()

def action_get_stfu_tgs() -> dict:
    return _load_stfu_tgs()

def _parse_fcs_hosts(lines) -> dict:
    by_server: "dict[str, list]" = {}
    seen: "set[str]" = set()
    updated = ""
    stats = {"servers": 0, "rooms": 0, "placeholders": 0,
             "duplicates": 0, "malformed": 0}
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if not updated:
                m = re.match(r"#\s*Last Update:\s*(.+)$", line, re.I)
                if m:
                    updated = _strip_ctrl(m.group(1)).strip()
            continue
        parts = line.split(";")
        rid = parts[0].strip()
        m = _FCS_ID_RE.fullmatch(rid)
        if not m or len(parts) < 2:
            stats["malformed"] += 1
            continue
        name = _strip_ctrl(parts[1]).strip()
        if not name or name.lower() == _FCS_PLACEHOLDER:
            stats["placeholders"] += 1
            continue
        if rid in seen:
            stats["duplicates"] += 1
            continue
        seen.add(rid)
        by_server.setdefault(m.group(1), []).append([m.group(2), name])
        stats["rooms"] += 1
    servers = []
    for sid in sorted(by_server):
        servers.append({
            "id":     "FCS" + sid,
            "lh_url": _fcs_lh_url(sid),
            "rooms":  sorted(by_server[sid], key=lambda r: r[0]),
        })
    stats["servers"] = len(servers)
    return {"ok": True, "found": True, "servers": servers,
            "updated": updated, "mtime": 0, "stats": stats}

def _build_fcs_hosts(_prev):
    missing = False
    path = _fcs_hosts_path()
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            result = _parse_fcs_hosts(f)
            result["mtime"] = int(os.fstat(f.fileno()).st_mtime)
    except OSError:
        missing = True
        result = {"ok": True, "found": False, "servers": [], "updated": "",
                  "mtime": 0, "stats": {"servers": 0, "rooms": 0, "placeholders": 0,
                                        "duplicates": 0, "malformed": 0}}
    result["path"] = path
    return result, missing

_fcs_cache = _ListCache(_FCS_HOSTS_TTL, _build_fcs_hosts,
                        lambda r: log.warning("FCSRooms.txt not found at %s — FCS room "
                                              "menus will be empty", r["path"]))

def _load_fcs_hosts() -> dict:
    return _fcs_cache.get()

def action_get_fcs_hosts() -> dict:
    return _load_fcs_hosts()

_M17_HOSTS_PATH   = "/var/lib/mmdvm/M17Hosts.json"
_M17_HOSTS_TTL    = 300.0
_M17_PORT         = 17000
_M17_ID_MAX       = 16
_M17_ADDR_MAX     = 128
_M17_URL_MAX      = 256

def _m17_empty(found: bool = False) -> dict:
    return {"ok": True, "found": found, "reflectors": [], "updated": "",
            "mtime": 0,
            "stats": {"reflectors": 0, "other_ports": 0, "ipv6_only": 0,
                      "duplicates": 0, "malformed": 0, "bad_modules": 0,
                      "other_mode": 0, "no_m17": 0}}

def _m17_text(val, limit: int) -> str:
    if not isinstance(val, str):
        return ""
    out = _strip_ctrl(val).strip()
    return out[:limit] if out else ""

_M17_MODULE_MODES = ("ALL", "M17")

def _m17_module_ok(mode) -> bool:
    return str(mode or "").strip().upper() in _M17_MODULE_MODES

def _m17_modules(val, stats: dict) -> "tuple[list, bool]":
    if not isinstance(val, list):
        if val is not None:
            stats["bad_modules"] += 1
        return [], False
    out = set()
    for m in val:
        if isinstance(m, str):
            letter, mode, is_obj = m, None, False
        elif isinstance(m, dict):
            letter, mode, is_obj = m.get("module"), m.get("mode"), True
        else:
            stats["bad_modules"] += 1
            continue
        if not (isinstance(letter, str) and len(letter.strip()) == 1
                and letter.strip().isalpha()):
            stats["bad_modules"] += 1
            continue
        if is_obj and not _m17_module_ok(mode):
            stats["other_mode"] += 1
            continue
        out.add(letter.strip().upper())
    return sorted(out), True

def _parse_m17_hosts(text: str) -> dict:
    try:
        doc = json.loads(text)
    except Exception:
        return _m17_empty()
    if not isinstance(doc, dict):
        return _m17_empty()
    raw = doc.get("reflectors")
    if not isinstance(raw, list) or not raw:
        return _m17_empty()

    meta = doc.get("_refcheck_metadata")
    updated = _m17_text(meta.get("generated"), 64) if isinstance(meta, dict) else ""

    stats = {"reflectors": len(raw), "other_ports": 0, "ipv6_only": 0,
             "duplicates": 0, "malformed": 0, "bad_modules": 0,
             "other_mode": 0, "no_m17": 0}
    seen: "set[str]" = set()
    out = []
    for e in raw:
        if not isinstance(e, dict):
            stats["malformed"] += 1
            continue
        rid = _m17_text(e.get("designator"), _M17_ID_MAX)
        if not rid:
            stats["malformed"] += 1
            continue

        port = e.get("port")
        if port is not None:
            try:
                if int(port) != _M17_PORT:
                    stats["other_ports"] += 1
                    continue
            except (TypeError, ValueError):
                stats["malformed"] += 1
                continue

        addr = _m17_text(e.get("dns"), _M17_ADDR_MAX) or \
               _m17_text(e.get("ipv4"), _M17_ADDR_MAX)
        if not addr:
            if _m17_text(e.get("ipv6"), _M17_ADDR_MAX):
                stats["ipv6_only"] += 1
            else:
                stats["malformed"] += 1
            continue

        key = rid.upper()
        if key in seen:
            stats["duplicates"] += 1
            continue
        seen.add(key)

        label = (_m17_text(e.get("name"), 64)
                 or _m17_text(e.get("sponsor"), 64)
                 or rid)
        url = _m17_text(e.get("url"), _M17_URL_MAX)
        if not url.startswith(("http://", "https://")):
            url = ""

        en = e.get("enabled_modes")
        if isinstance(en, list) and en and not any(
                str(x or "").strip().upper() == "M17" for x in en):
            stats["no_m17"] += 1
            continue

        mods, had_list = _m17_modules(e.get("modules"), stats)
        if had_list and not mods:
            stats["no_m17"] += 1
            continue

        row = {"id": rid, "label": label, "addr": addr, "lh_url": url}
        if mods:
            row["modules"] = mods
        out.append(row)

    out.sort(key=lambda r: r["id"])
    return {"ok": True, "found": True, "reflectors": out,
            "updated": updated, "mtime": 0, "stats": stats}

def _build_m17_hosts(_prev):
    try:
        with open(_M17_HOSTS_PATH, "r", encoding="utf-8", errors="replace") as f:
            result = _parse_m17_hosts(f.read())
            result["mtime"] = int(os.fstat(f.fileno()).st_mtime)
    except OSError:
        return _m17_empty(), True
    return result, False

_m17_cache = _ListCache(_M17_HOSTS_TTL, _build_m17_hosts,
                        lambda _r: log.warning("M17Hosts.json not found at %s — M17 reflector "
                                               "menus will be empty (install "
                                               "m17hosts_update.sh)", _M17_HOSTS_PATH))

def _load_m17_hosts() -> dict:
    return _m17_cache.get()

def action_get_m17_hosts() -> dict:
    return _load_m17_hosts()


_XLX_HOSTS_PATH   = "/var/lib/mmdvm/XLXHosts.txt"
_XLX_HOSTS_TTL    = 300.0
_XLX_ID_MAX       = 16
_XLX_ADDR_MAX     = 128
_XLX_CODE_LEN     = 3
_XLX_DMR_TG_BASE  = 4001


def _xlx_empty(found: bool = False) -> dict:
    return {"ok": True, "found": found, "reflectors": [], "updated": "",
            "mtime": 0,
            "stats": {"reflectors": 0, "malformed": 0, "duplicates": 0,
                      "bad_addr": 0}}


def _xlx_text(val, limit: int) -> str:
    if not isinstance(val, str):
        return ""
    out = _strip_ctrl(val).strip()
    return out[:limit] if out else ""


def _xlx_id(code: str) -> str:
    if not isinstance(code, str):
        return ""
    code = _strip_ctrl(code).strip().upper()
    if len(code) != _XLX_CODE_LEN or not code.isalnum():
        return ""
    return "XLX" + code


def _xlx_dmr_module(val) -> str:
    try:
        n = int(str(val).strip())
    except (TypeError, ValueError):
        return ""
    off = n - _XLX_DMR_TG_BASE
    return chr(65 + off) if 0 <= off <= 25 else ""


def _parse_xlx_hosts(text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        return _xlx_empty()

    stats = {"reflectors": 0, "malformed": 0, "duplicates": 0, "bad_addr": 0}
    seen: "set[str]" = set()
    out = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        stats["reflectors"] += 1

        parts = line.split(";")
        if len(parts) != 3:
            stats["malformed"] += 1
            continue

        rid = _xlx_id(parts[0])
        if not rid:
            stats["malformed"] += 1
            continue

        key = rid.upper()
        if key in seen:
            stats["duplicates"] += 1
            continue

        addr = _xlx_text(parts[1], _XLX_ADDR_MAX)
        if addr and ("|" in addr or " " in addr):
            stats["bad_addr"] += 1
            addr = ""

        seen.add(key)
        row = {"id": rid, "addr": addr}
        mod = _xlx_dmr_module(parts[2])
        if mod:
            row["dmr_default_module"] = mod
        out.append(row)

    if not out:
        return _xlx_empty()

    out.sort(key=lambda r: r["id"])
    return {"ok": True, "found": True, "reflectors": out,
            "updated": "", "mtime": 0, "stats": stats}


def _build_xlx_hosts(_prev):
    try:
        with open(_XLX_HOSTS_PATH, "r", encoding="utf-8", errors="replace") as f:
            result = _parse_xlx_hosts(f.read())
            result["mtime"] = int(os.fstat(f.fileno()).st_mtime)
    except OSError:
        return _xlx_empty(), True
    return result, False

_xlx_cache = _ListCache(_XLX_HOSTS_TTL, _build_xlx_hosts,
                        lambda _r: log.warning("XLXHosts.txt not found at %s — XLX reflector "
                                               "menus will be empty (it is normally refreshed "
                                               "by cron.daily/DVSM_Update)", _XLX_HOSTS_PATH))

def _load_xlx_hosts() -> dict:
    return _xlx_cache.get()


def action_get_xlx_hosts() -> dict:
    return _load_xlx_hosts()


_DSTAR_HOSTS_DIR   = "/var/lib/mmdvm"
_DSTAR_HOSTS_FILES = (("REF", "DPlus_Hosts.txt"),
                      ("XRF", "DExtra_Hosts.txt"),
                      ("DCS", "DCS_Hosts.txt"))
_DSTAR_TYPE_ORDER  = {t: i for i, (t, _f) in enumerate(_DSTAR_HOSTS_FILES)}
_DSTAR_HOSTS_TTL   = 300.0
_DSTAR_ADDR_MAX    = 128
_DSTAR_ID_RE       = re.compile(r"^([A-Z]{3})(\d{3})$")
_DSTAR_DATE_RE     = re.compile(r"#.*?File updated on\s+(.+?)\s*$", re.I)


def _parse_dstar_hosts(lines, kind: str) -> dict:
    rows: "list[dict]" = []
    seen: "set[str]" = set()
    updated = ""
    stats = {"reflectors": 0, "malformed": 0, "duplicates": 0, "xlx": 0}
    for raw in lines:
        line = _strip_ctrl(str(raw).replace("\t", " ")).strip()
        if not line:
            continue
        if line.startswith("#"):
            if not updated:
                m = _DSTAR_DATE_RE.match(line)
                if m:
                    updated = m.group(1)[:64]
            continue
        parts = line.split()
        name = parts[0].upper()
        if name.startswith("XLX"):
            stats["xlx"] += 1
            continue
        m = _DSTAR_ID_RE.match(name)
        if len(parts) < 2 or not m or m.group(1) != kind:
            stats["malformed"] += 1
            continue
        addr = parts[1][:_DSTAR_ADDR_MAX]
        if "|" in addr or "/" in addr:
            stats["malformed"] += 1
            continue
        if name in seen:
            stats["duplicates"] += 1
            continue
        seen.add(name)
        rows.append({"id": name, "addr": addr})
    stats["reflectors"] = len(rows)
    return {"rows": rows, "updated": updated, "stats": stats}


def _build_dstar_hosts(_prev):
    rows: "list[dict]" = []
    seen: "set[str]" = set()
    stats = {"reflectors": 0, "malformed": 0, "duplicates": 0, "xlx": 0}
    updated, mtime = "", 0
    used: "list[str]" = []
    missing: "list[str]" = []
    for kind, fname in _DSTAR_HOSTS_FILES:
        path = os.path.join(_DSTAR_HOSTS_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                part = _parse_dstar_hosts(f, kind)
                mtime = max(mtime, int(os.fstat(f.fileno()).st_mtime))
        except OSError:
            missing.append(fname)
            continue
        used.append(path)
        if not updated:
            updated = part["updated"]
        for k in ("malformed", "duplicates", "xlx"):
            stats[k] += part["stats"][k]
        for r in part["rows"]:
            if r["id"] in seen:
                stats["duplicates"] += 1
                continue
            seen.add(r["id"])
            rows.append(r)
    rows.sort(key=lambda r: (_DSTAR_TYPE_ORDER.get(r["id"][:3], 9), r["id"]))
    stats["reflectors"] = len(rows)
    found = bool(used)
    result = {"ok": True, "found": found, "reflectors": rows if found else [],
              "path": _DSTAR_HOSTS_DIR + "/ (DPlus, DExtra and DCS host lists)",
              "paths": used, "missing": missing, "updated": updated,
              "mtime": mtime, "stats": stats}
    return result, not found

_dstar_cache = _ListCache(_DSTAR_HOSTS_TTL, _build_dstar_hosts,
                          lambda _r: log.warning("D-STAR host lists not found in %s — the "
                                                 "D-STAR reflector menu will be empty",
                                                 _DSTAR_HOSTS_DIR))

def _load_dstar_hosts() -> dict:
    return _dstar_cache.get()


def action_get_dstar_hosts() -> dict:
    return _load_dstar_hosts()


_FAV_SLOTS = 10


def _tg_blank_row(r) -> bool:
    return _tg_row_is_blank(r[1], r[2])


def _same_tg_number(t, tg: str) -> bool:
    t = str(t).strip()
    return t.isdigit() and str(int(t)) == tg


def _fav_full_msg(what: str) -> str:
    return (f"All {_FAV_SLOTS} {what} favorite slots are in use. "
            "Free one in the Edit tab first.")


def _fav_place(rows, entry, is_blank, is_same):
    for slot, r in enumerate(rows, 1):
        if not is_blank(r) and is_same(r):
            return "dup", slot, rows
    new_rows = list(rows)
    for slot, r in enumerate(new_rows, 1):
        if is_blank(r):
            new_rows[slot - 1] = entry
            return "new", slot, new_rows
    if len(new_rows) >= _FAV_SLOTS:
        return "full", None, rows
    new_rows.append(entry)
    return "new", len(new_rows), new_rows


def _commit_conf(**changes) -> Tuple[bool, str]:
    st   = get_state()
    prev = {k: getattr(st, k) for k in changes}
    set_state(**changes)
    st = get_state()
    ok, msg = _write_conf(list(st.asl_nodes), list(st.talkgroups), list(st.echo_nodes))
    if not ok:
        set_state(**prev)
    return ok, msg


def _add_favorite(field: str, entry, is_same, what: str, label: str, *,
                  mode: Optional[str] = None, is_blank=None, saved: str = "",
                  dup=None, after=None) -> Tuple[bool, str]:
    is_blank = is_blank or _tg_blank_row
    with _conf_lock:
        rows = list(getattr(get_state(), field))
        idx  = ([i for i, r in enumerate(rows) if r[0] == mode] if mode is not None
                else list(range(len(rows))))
        kind, slot, view = _fav_place([rows[i] for i in idx], entry, is_blank, is_same)
        if kind == "dup":
            shown = dup(view[slot - 1]) if dup else label
            return True, f"{shown} is already in favorites (slot {slot})"
        if kind == "full":
            return False, _fav_full_msg(what)
        if slot <= len(idx):
            rows[idx[slot - 1]] = entry
        else:
            rows.append(entry)
        ok, msg = _commit_conf(**{field: rows})
        if not ok:
            return False, msg
        if after:
            after()
    return True, f"Saved {saved or label} to favorite slot {slot}"


def action_save_dstar_favorite(base: str, module: str) -> Tuple[bool, str]:
    base = str(base or "").strip().upper()
    if not base or len(base) > 16 or _has_ctrl_chars(base):
        return False, "D-STAR reflector is required (e.g. REF001)"
    if not _DSTAR_ID_RE.match(base) or base[:3] not in _DSTAR_TYPE_ORDER:
        return False, f"'{base}' is not a D-STAR reflector name (REF, XRF or DCS plus 3 digits)"
    mod = str(module or "").strip().upper()
    if len(mod) != 1 or not mod.isalpha():
        return False, f"Invalid module: '{module}' (must be a single letter A-Z)"
    hosts = _load_dstar_hosts()
    if not hosts.get("found"):
        return False, "D-STAR reflector list not found - can't verify the reflector"
    ref = next((r for r in hosts["reflectors"] if r["id"] == base), None)
    if ref is None:
        return False, f"{base} is not in the D-STAR reflector list"
    tune  = f"{base.ljust(_DSTAR_BASE_LEN)}{mod}L"
    label = f"{base} Mod-{mod}"
    san, err = _validate_tg_entries([{"mode": "DSTAR", "name": label, "tg": tune,
                                       "url": _lh_link(ref.get("addr", ""))}])
    if err:
        return False, err
    return _add_favorite("talkgroups", san[0],
                         lambda r: r[2].strip().upper() == tune,
                         "D-STAR", label, mode="DSTAR")


def _lh_link(addr: str) -> str:
    a = _strip_ctrl(str(addr or "")).strip()
    if not a or "|" in a or " " in a or "/" in a:
        return ""
    if ":" in a and not a.startswith("["):
        a = f"[{a}]"
    return f"http://{a}"


def _xlx_row_is_blank(name: str, tg: str) -> bool:
    return str(name).strip().lower() == TG_BLANK_NAME or str(tg).strip() == TG_BLANK_ADDR


def action_save_xlx_favorite(base: str, module: str) -> Tuple[bool, str]:
    base = str(base or "").strip().upper()
    if not base or len(base) > _XLX_ID_MAX or _has_ctrl_chars(base):
        return False, "XLX reflector is required (e.g. XLX307)"

    code = base[3:] if (len(base) == 3 + _XLX_CODE_LEN
                        and base.startswith("XLX")) else base
    rid  = _xlx_id(code)
    if not rid:
        return False, f"'{base}' is not a valid XLX reflector name"

    mod = str(module or "").strip().upper()
    if mod == "@ALL":
        return False, "XLX has no All-Modules option - pick a single module A-Z"
    if len(mod) != 1 or not mod.isalpha():
        return False, f"Invalid module: '{module}' (must be a single letter A-Z)"

    hosts = _load_xlx_hosts()
    if not hosts.get("found"):
        return False, "XLX reflector list not found - can't verify the reflector"
    ref = next((r for r in hosts["reflectors"] if r["id"].upper() == rid), None)
    if ref is None:
        return False, f"{rid} is not in the XLX reflector list"

    tune = f"{rid}{mod}L"

    name = _clip_label(_conf_field(f"{rid} Mod-{mod}")) or rid
    url  = _conf_field(_lh_link(ref.get("addr", "")), url=True)
    tg   = _conf_field(tune)
    if tg != tune:
        return False, f"{rid} produced a malformed tune string"
    entry = (name, tg, url)

    return _add_favorite("xlx_reflectors", entry,
                         lambda r: str(r[1]).strip().upper() == tune,
                         "XLX", f"{rid} Mod-{mod}",
                         is_blank=lambda r: _xlx_row_is_blank(r[0], r[1]))


def _m17_row_is_blank(name: str, ip: str) -> bool:
    return str(name).strip().lower() == TG_BLANK_NAME or str(ip).strip() == TG_BLANK_ADDR

def action_save_m17_favorite(base: str, module: str) -> Tuple[bool, str]:
    base = str(base or "").strip()
    if not base or len(base) > _M17_ID_MAX or _has_ctrl_chars(base):
        return False, "M17 reflector is required (e.g. M17-003)"

    raw_mod = str(module or "").strip().upper()
    if raw_mod != "@ALL" and not (len(raw_mod) == 1 and raw_mod.isalpha()):
        return False, f"Invalid module: '{module}' (must be A-Z or @ALL)"
    module = _norm_m17_module(raw_mod)

    hosts = _load_m17_hosts()
    if not hosts.get("found"):
        return False, "M17 reflector list not found - can't verify the reflector"
    ref = next((r for r in hosts["reflectors"] if r["id"].upper() == base.upper()), None)
    if ref is None:
        return False, f"{base} is not in the M17 reflector list"

    pub = ref.get("modules") or []
    if module != "@ALL" and pub and module not in pub:
        return False, (f"{ref['id']} does not publish module {module} "
                       f"(it has {', '.join(pub)})")

    raw_addr = _strip_ctrl(str(ref.get("addr") or "")).strip()
    if "|" in raw_addr:
        return False, f"{ref['id']} has a malformed address in the reflector list"
    label = _clip_label(_conf_field(ref.get("label") or ref["id"])) or ref["id"]
    addr  = raw_addr
    url   = _conf_field(ref.get("lh_url"), url=True).rstrip("/")
    if not addr:
        return False, f"{ref['id']} has no usable address in the reflector list"
    entry = (label, ref["id"], module, addr, url)

    return _add_favorite("m17_reflectors", entry,
                         lambda r: (str(r[1]).upper() == ref["id"].upper()
                                    and str(r[2]).upper() == module),
                         "M17", f"{ref['id']} Mod-{module}",
                         is_blank=lambda r: _m17_row_is_blank(r[0], r[3]))


def _tg_row_is_blank(name: str, tg: str) -> bool:
    return name.strip().lower() == TG_BLANK_NAME or tg.strip() == TG_BLANK_ADDR

def action_save_fcs_favorite(room: str) -> Tuple[bool, str]:
    room = str(room or "").strip()
    if not room or len(room) > 16 or _has_ctrl_chars(room):
        return False, "FCS room is required (e.g. FCS00102)"
    try:
        tune = _fcs_to_tune(room)
    except ValueError as e:
        return False, str(e)
    sid, nn = "FCS" + tune[1:4], tune[4:6]
    hosts = _load_fcs_hosts()
    if not hosts.get("found"):
        return False, "FCS room list not found - can't verify the room"
    server = next((sv for sv in hosts["servers"] if sv["id"] == sid), None)
    row    = next((r for r in server["rooms"] if r[0] == nn), None) if server else None
    if row is None:
        return False, f"{sid}-{nn} is not in the FCS room list"
    label = f"{sid}-{nn} {row[1]}"
    san, err = _validate_tg_entries([{"mode": "FCS", "name": label,
                                       "tg": tune, "url": server["lh_url"]}])
    if err:
        return False, err
    def same(r):
        try:
            return _fcs_to_tune(r[2]) == tune
        except ValueError:
            return False
    return _add_favorite("talkgroups", san[0], same, "FCS", label, mode="FCS")


def action_save_ysf_favorite(ref: str) -> Tuple[bool, str]:
    ref = str(ref or "").strip()
    if not ref or len(ref) > 64 or _has_ctrl_chars(ref) or ":" not in ref:
        return False, "YSF reflector is required (address:port)"
    key = ref.lower()
    hosts = _load_ysf_data()[0]
    if not hosts.get("found"):
        return False, "YSF reflector list not found - can't verify the reflector"
    row = next((r for r in hosts["reflectors"]
                if f"{r[3]}:{r[4]}".lower() == key), None)
    if row is None:
        return False, f"{ref} is not in the YSF reflector list"
    rid, rname, addr, port = row[0], row[1], row[3], row[4]
    tune  = f"{addr}:{port}"
    host  = f"[{addr}]" if ":" in addr and not addr.startswith("[") else addr
    link  = f"http://{host}"
    label = f"{rid} {rname}"
    san, err = _validate_tg_entries([{"mode": "YSF", "name": label,
                                       "tg": tune, "url": link}])
    if err:
        return False, err
    def same(r):
        t = r[2].strip()
        return t.lower() == key or (t.isdigit() and len(t) <= 5
                                    and t.zfill(5) == rid.zfill(5))
    return _add_favorite("talkgroups", san[0], same, "YSF", label, mode="YSF")


def action_save_stfu_favorite(tg: str) -> Tuple[bool, str]:
    tg = str(tg or "").strip()
    if not tg.isdigit() or len(tg) > 8:
        return False, "STFU talkgroup must be a number"
    tg = str(int(tg))
    hosts = _load_stfu_tgs()
    if not hosts.get("found"):
        return False, "BrandMeister talkgroup list not found - can't verify the talkgroup"
    row = next((r for r in hosts["reflectors"] if r[0] == tg), None)
    if row is None:
        return False, f"TG {tg} is not in the BrandMeister talkgroup list"
    label = _clip_label(f"{tg} {row[1]}")
    san, err = _validate_tg_entries([{"mode": "STFU", "name": label, "tg": tg, "url": ""}])
    if err:
        return False, err
    return _add_favorite("talkgroups", san[0], lambda r: _same_tg_number(r[2], tg),
                         "STFU", label, mode="STFU", saved=f"STFU {label}")


def action_save_tg_favorite(mode: str, tg: str) -> Tuple[bool, str]:
    mode = str(mode or "").strip().upper()
    if mode == "STFU":
        return action_save_stfu_favorite(tg)
    if mode not in _TGH_GATEWAYS:
        return False, "Talkgroup saving is only for STFU, P25 and NXDN"
    tg = str(tg or "").strip()
    if not tg.isdigit() or len(tg) > 8:
        return False, f"{mode} talkgroup must be a number"
    tg = str(int(tg))
    hosts = _load_tg_hosts(mode)
    if not hosts.get("found"):
        return False, f"{mode} talkgroup list not found - can't verify the talkgroup"
    row = next((r for r in hosts["reflectors"] if r[0] == tg), None)
    if row is None:
        return False, f"{mode} TG {tg} is not in the talkgroup list"
    addr  = row[1]
    host  = f"[{addr}]" if ":" in addr and not addr.startswith("[") else addr
    label = f"{tg} {addr}"
    san, err = _validate_tg_entries([{"mode": mode, "name": label,
                                       "tg": tg, "url": f"http://{host}"}])
    if err:
        return False, err
    return _add_favorite("talkgroups", san[0], lambda r: _same_tg_number(r[2], tg),
                         mode, label, mode=mode, saved=f"{mode} {label}")


def _dmr_is_brandmeister(srv: dict) -> bool:
    name = str(srv.get("name", "")).lower()
    url  = str(srv.get("net_url", "")).lower()
    return "brandmeister" in name or "brandmeister" in url

def action_save_dmr_favorite(network: str, tg: str) -> Tuple[bool, str]:
    network = str(network or "").strip()
    tg = str(tg or "").strip()
    if not tg.isdigit() or len(tg) > 8:
        return False, "DMR talkgroup must be a number (up to 8 digits)"
    tg = str(int(tg))
    if tg == "0":
        return False, "DMR talkgroup 0 can't be saved"
    srv = next((s for s in get_state().dmr_servers if s.get("name") == network), None)
    if srv is None:
        return False, f"Unknown DMR network '{network}'"
    label = f"TG {tg}"
    if _dmr_is_brandmeister(srv):
        hosts = _load_stfu_tgs()
        row = next((r for r in hosts.get("reflectors", []) if r[0] == tg), None)
        if row is not None and str(row[1]).strip():
            label = f"{tg} {str(row[1]).strip()}"
    label = _clip_label(_sf({"n": label}, "n"))
    key = _server_key(network)
    blank = ("DMR", TG_BLANK_NAME, TG_BLANK_ADDR, "")
    with _conf_lock:
        st   = get_state()
        rows = list(st.dmr_server_tgs.get(key, []))
        rows = (rows + [blank] * _FAV_SLOTS)[:_FAV_SLOTS]
        kind, slot, rows = _fav_place(rows, ("DMR", label, tg, ""), _tg_blank_row,
                                      lambda r: _same_tg_number(r[2], tg))
        if kind == "dup":
            return True, f"{network} {label} is already in favorites (slot {slot})"
        if kind == "full":
            return False, _fav_full_msg(network)
        srv_tgs = {k: [{"name": n, "tg": t} for _m, n, t, _u in v]
                   for k, v in st.dmr_server_tgs.items()}
        srv_tgs[key] = [{"name": n, "tg": t} for _m, n, t, _u in rows]
        ok, msg = action_save_dmr_server_tgs(srv_tgs)
        if not ok:
            return False, msg
        if key == _server_key(get_state().active_dmr_server or ""):
            _seed_dmr_tgs()
    return True, f"Saved {network} {label} to favorite slot {slot}"

_ASTDB_PATH        = "/var/lib/asterisk/astdb.txt"
_ASTDB_TTL         = 300.0
_ASTDB_MAX_MATCHES = 200
_ASTDB_MIN_QUERY   = 2

def _parse_astdb(f) -> dict:
    rows, by_node = [], {}
    for raw in f:
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        parts = [_strip_ctrl(p.strip()) for p in line.split("|")]
        node = parts[0]
        if not node.isdigit() or len(node) > 7:
            continue
        node = str(int(node))
        if node in by_node:
            continue
        call = parts[1] if len(parts) > 1 else ""
        desc = parts[2] if len(parts) > 2 else ""
        loc  = parts[3] if len(parts) > 3 else ""
        row = (node, call, desc, loc, f"{node} {call} {desc} {loc}".lower())
        rows.append(row)
        by_node[node] = row
    return {"rows": rows, "by_node": by_node}

def _build_astdb(prev):
    try:
        mtime = int(os.stat(_ASTDB_PATH).st_mtime)
    except OSError:
        return {"found": False, "mtime": 0, "rows": [], "by_node": {}}, True
    if prev and prev.get("found") and prev["mtime"] == mtime:
        return prev, False
    try:
        with open(_ASTDB_PATH, "r", encoding="utf-8", errors="replace") as f:
            part = _parse_astdb(f)
    except OSError as e:
        log.warning("Could not read %s: %s", _ASTDB_PATH, e)
        part = {"rows": [], "by_node": {}}
    return {"found": True, "mtime": mtime, **part}, False

_astdb_cache = _ListCache(_ASTDB_TTL, _build_astdb,
                          lambda _r: log.warning("AllStar node list not found at %s — the ASL "
                                                 "node menu will be empty (turn on "
                                                 "asl3-update-astdb)", _ASTDB_PATH))

def _load_astdb() -> dict:
    return _astdb_cache.get()

def _dir_search(path: str, db: dict, min_q: int, limit: int, text_col: int,
                ncols: int, to_asl=None, extra: Optional[dict] = None) -> dict:
    try:
        q = parse_qs(urlparse(path).query).get("q", [""])[0]
    except Exception:
        q = ""
    q = _strip_ctrl(q).strip().lower()[:40]
    out = {"ok": True, "found": db["found"], **(extra or {}), "mtime": db["mtime"],
           "total": len(db["rows"]), "min": min_q,
           "limit": limit, "count": 0, "matches": []}
    if not db["found"] or len(q) < min_q:
        return out
    bridges = _bridge_set()
    words = q.split()
    if len(words) == 1 and words[0].isdigit():
        pre = words[0].lstrip("0") or "0"
        test = lambda r: r[0].startswith(pre)
    else:
        test = lambda r: all(w in r[text_col] for w in words)
    count, matches = 0, []
    for r in db["rows"]:
        if (to_asl(r[0]) if to_asl else r[0]) in bridges or not test(r):
            continue
        count += 1
        if len(matches) < limit:
            matches.append(list(r[:ncols]))
    out["count"] = count
    out["matches"] = matches
    return out

def _save_node_favorite(field: str, node: str, label: str, what: str) -> Tuple[bool, str]:
    def same(r):
        nd = str(r[1]).strip()
        return nd.isdigit() and str(int(nd)) == node
    def clear_etag():
        global _status_etag
        with _lock:
            _status_etag = ""
    return _add_favorite(field, (label, node), same, what, label,
                         is_blank=lambda r: _tg_row_is_blank(r[0], r[1]),
                         dup=lambda r: r[0], saved=f"{what} {label}", after=clear_etag)

def action_asl_directory(path: str) -> dict:
    return _dir_search(path, _load_astdb(), _ASTDB_MIN_QUERY, _ASTDB_MAX_MATCHES,
                       text_col=4, ncols=4, extra={"path": _ASTDB_PATH})

def _astdb_label(node: str) -> str:
    row = _load_astdb()["by_node"].get(node)
    if not row:
        return f"Node {node}"
    place = row[3] or row[2]
    return " ".join(x for x in (node, row[1], place) if x)

def action_save_asl_favorite(node: str) -> Tuple[bool, str]:
    node = str(node or "").strip()
    if not node.isdigit() or len(node) > 7:
        return False, "ASL node must be a number (up to 7 digits)"
    node = str(int(node))
    if node == "0":
        return False, "ASL node 0 can't be saved"
    if _is_bridge_node(node):
        return False, _bridge_reject_msg(node, "an ASL favorite")
    label = _clip_label(_sf({"n": _astdb_label(node)}, "n"))
    return _save_node_favorite("asl_nodes", node, label, "ASL")

_ECHODB_CMD         = "echolink dbdump"
_ECHODB_TTL         = 300.0
_ECHODB_MAX_MATCHES = 200
_ECHODB_MIN_QUERY   = 2

def _parse_echodb(text: str) -> dict:
    rows, by_node = [], {}
    for raw in text.splitlines():
        parts = [_strip_ctrl(p.strip()) for p in raw.split("|")]
        if len(parts) < 2:
            continue
        node, call = parts[0], parts[1]
        if not node.isdigit() or len(node) > 7:
            continue
        node = str(int(node))
        if node == "0" or node in by_node:
            continue
        call = call[:24]
        row = (node, call, f"{node} {call}".lower())
        rows.append(row)
        by_node[node] = row
    rows.sort(key=lambda r: int(r[0]))
    return {"rows": rows, "by_node": by_node}

def _build_echodb(prev):
    out, ok = ami_command(_ECHODB_CMD, timeout=8)
    if ok and "no such command" not in out.lower():
        part = _parse_echodb(out)
        return {"found": True, "mtime": int(time.time()), **part}, False
    if prev and prev.get("found"):
        return prev, False
    return {"found": False, "mtime": 0, "rows": [], "by_node": {}}, True

_echodb_cache = _ListCache(_ECHODB_TTL, _build_echodb,
                           lambda _r: log.warning("EchoLink station list not available "
                                                  "(%s failed -- is chan_echolink loaded?)",
                                                  _ECHODB_CMD))

def _load_echodb() -> dict:
    return _echodb_cache.get()

def action_echo_directory(path: str) -> dict:
    return _dir_search(path, _load_echodb(), _ECHODB_MIN_QUERY, _ECHODB_MAX_MATCHES,
                       text_col=2, ncols=2, to_asl=_echolink_to_asl)

def action_save_echo_favorite(node: str) -> Tuple[bool, str]:
    node = str(node or "").strip()
    if not node.isdigit() or len(node) > 7:
        return False, "EchoLink node must be a number (1-7 digits)"
    node = str(int(node))
    if node == "0":
        return False, "EchoLink node 0 can't be saved"
    if _is_bridge_node(_echolink_to_asl(node)):
        return False, _bridge_reject_msg(_echolink_to_asl(node), "an EchoLink favorite")
    row = _load_echodb()["by_node"].get(node)
    label = _clip_label(_sf({"n": f"{node} {row[1]}" if row and row[1] else f"Node {node}"}, "n"))
    return _save_node_favorite("echo_nodes", node, label, "Echo")

def _is_root_owned(path: str) -> bool:
    try:
        return os.stat(path).st_uid == 0
    except OSError:
        return False

def _read_abinfo() -> "dict | None":
    try:
        files = _glob.glob("/tmp/ABInfo_*.json")
        if not files:
            return None
        owned = [f for f in files if _is_root_owned(f)]
        if not owned:
            return None
        newest = max(owned, key=os.path.getmtime)
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

_KEYED_RE     = re.compile(r"RPT_(?:RX|TX)KEYED[ \t]*=[ \t]*1", re.IGNORECASE)
_LINKS_RE     = re.compile(r"RPT_LINKS[ \t]*=[ \t]*([^\r\n]*)", re.IGNORECASE)
_ALINKS_RE    = re.compile(r"RPT_ALINKS[ \t]*=[ \t]*([^\r\n]*)", re.IGNORECASE)
_ALINK_TOK_RE = re.compile(r"^(\d+)([TRLC])([KU])$", re.IGNORECASE)
_LINK_FILLER  = "000000"

def _parse_rpt_links_full(out: str) -> List[str]:
    nodes: List[str] = []
    m = _LINKS_RE.search(out)
    if not m:
        return nodes
    raw = m.group(1).strip()
    if "," in raw:
        raw = raw[raw.index(",")+1:].strip()
    for tok in re.split(r"[,\s]+", raw):
        tok = tok.strip()
        if not tok or tok == "(none)":
            continue
        if tok[0].upper() in ("T", "R", "L", "C") and len(tok) > 1 and tok[1:].isdigit():
            tok = tok[1:]
        if not tok.isdigit() or tok == "0" or tok == _LINK_FILLER:
            continue
        if tok not in nodes:
            nodes.append(tok)
    return nodes

def _parse_rpt_links(out: str) -> List[str]:
    m = _ALINKS_RE.search(out)
    if m is None:
        return _parse_rpt_links_full(out)
    nodes: List[str] = []
    toks = [t.strip() for t in m.group(1).split(",")]
    for tok in toks[1:]:
        mt = _ALINK_TOK_RE.match(tok)
        if not mt:
            continue
        nd = mt.group(1)
        if nd == "0" or nd == _LINK_FILLER:
            continue
        if nd not in nodes:
            nodes.append(nd)
    return nodes

def _query_linked_nodes(timeout: int = 3) -> Optional[List[str]]:
    out, ok = ami_command(f"{_AMI_RPT_SHOW_VARS} {_cfg.asl_node}", timeout=timeout)
    if not ok or not out or "RPT_" not in out:
        return None
    return _parse_rpt_links(out)

_TEARDOWN_CHECK_SETTLE_SEC = 1.0

def _log_teardown_survivors(what: str) -> None:
    try:
        time.sleep(_TEARDOWN_CHECK_SETTLE_SEC)
        left = _query_linked_nodes()
        if left is None:
            log.warning("teardown check (%s): link query failed — cannot confirm", what)
            return
        if not left:
            log.info("teardown check (%s): all links cleared", what)
            return
        perms      = _read_perm_links()
        bridge_set = _bridge_set()
        for nd in left:
            log.warning("teardown check (%s): node %s STILL LINKED%s%s", what, nd,
                        " [PERMANENT - listed in rpt.conf nodes=]" if nd in perms else "",
                        " [BRIDGE SLOT]" if nd in bridge_set else "")
    except Exception as e:
        log.warning("teardown check (%s): error: %s", what, e)

def _log_teardown_survivors_async(what: str) -> None:
    threading.Thread(target=_log_teardown_survivors, args=(what,),
                     daemon=True, name="teardown-check").start()

_connecting_lock  = threading.Lock()
_connecting_depth = 0
_link_action_lock = threading.RLock()
_LINK_BUSY_WAIT_SEC = 2.0
_LINK_BUSY_MSG = ("Busy — another connect, disconnect or tab switch is still running. "
                  "Try again in a moment.")

def _is_connecting() -> bool:
    with _connecting_lock:
        return _connecting_depth > 0

def _link_enter(timeout: float = -1) -> bool:
    global _connecting_depth
    if timeout == 0:
        got = _link_action_lock.acquire(blocking=False)
    else:
        got = _link_action_lock.acquire(timeout=timeout)
    if not got:
        return False
    with _connecting_lock:
        _connecting_depth += 1
    return True

def _link_try_enter() -> bool:
    return _link_enter(timeout=0)

def _link_exit() -> None:
    global _connecting_depth
    with _connecting_lock:
        _connecting_depth -= 1
    _link_action_lock.release()

@contextlib.contextmanager
def _link_guard():
    _link_enter()
    try:
        yield
    finally:
        _link_exit()

def _link_locked(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not _link_enter(timeout=_LINK_BUSY_WAIT_SEC):
            log.info("%s refused: another link action is still running", fn.__name__)
            return False, _LINK_BUSY_MSG
        try:
            return fn(*args, **kwargs)
        finally:
            _link_exit()
    return wrapper
_multi_link_count = 0

_poll_ok = True

_MULTI_LINK_CLEANUP_ENABLED = True
_multi_link_run_lock        = threading.Lock()
_multi_link_left_alone: FrozenSet[str] = frozenset()

def _multi_link_targets(adjacent: List[str], keep: Optional[str]) -> List[str]:
    st = get_state()
    bridge_set = _bridge_set()
    ours = {ASL_PARROT_NODE}
    for _, nd, *_r in st.asl_nodes:
        nd = str(nd or "").strip()
        if nd and nd != TG_BLANK_ADDR:
            ours.add(nd)
    for _, nd, *_r in st.echo_nodes:
        nd = str(nd or "").strip()
        if nd and nd != TG_BLANK_ADDR:
            ours.add(_echolink_to_asl(nd))
    return [nd for nd in adjacent
            if nd != keep and nd not in bridge_set and nd in ours]

def _multi_link_cleanup(keep: Optional[str]) -> None:
    global _multi_link_left_alone
    if not _multi_link_run_lock.acquire(blocking=False):
        return
    try:
        if not _link_try_enter():
            return
        try:
            adjacent = _query_linked_nodes()
            if adjacent is None:
                log.warning("multi-link cleanup: link query failed — nothing dropped")
                return
            targets = _multi_link_targets(adjacent, keep)
            if not targets:
                _multi_link_left_alone = frozenset(adjacent)
                log.info("multi-link cleanup: no dashboard favourites among the extra links "
                         "(%s) — left alone", ",".join(adjacent) or "none")
                return
            perms = _read_perm_links()
            for nd in targets:
                was_perm = _drop_one_link(nd, perms)
                log.warning("multi-link cleanup: dropped %s%s (keeping %s)", nd,
                            " (permanent, ilink 11)" if was_perm else "", keep)
                time.sleep(_LINK_DROP_PACING_SEC)
        finally:
            _link_exit()
    finally:
        _multi_link_run_lock.release()

def _poll_asl_state() -> "Tuple[bool, Optional[str], bool, FrozenSet[str]]":
    global _multi_link_count, _poll_ok, _multi_link_left_alone
    out, ok = ami_command(f"{_AMI_RPT_SHOW_VARS} {_cfg.asl_node}", timeout=2)
    _poll_ok = bool(ok and out and "RPT_" in out)
    if not _poll_ok:
        return False, None, False, frozenset()
    keyed = bool(_KEYED_RE.search(out))
    linked_node: Optional[str] = None


    bridge_set = _bridge_set()
    bridge_linked_nodes: Set[str] = set()
    adjacent = _parse_rpt_links(out)
    for tok in adjacent:
        if tok in bridge_set:
            bridge_linked_nodes.add(tok)
            continue
        if linked_node is None:
            linked_node = tok
    bridge_linked = bool(bridge_linked_nodes)
    page = get_state_fields("page")["page"]
    connecting_now = _is_connecting()
    others = [nd for nd in adjacent if nd not in bridge_set]
    if _MULTI_LINK_CLEANUP_ENABLED and page in ("ASL", "ECHO") and not connecting_now:
        if len(others) > 1 and frozenset(adjacent) != _multi_link_left_alone:
            _multi_link_count += 1
            if _multi_link_count >= 2:
                _multi_link_count = 0
                _intended = None
                _st_now = get_state()
                if page == "ASL":
                    if _st_now.current_fav:
                        _intended = _st_now.current_fav
                elif page == "ECHO":
                    if _st_now.echo_fav and _st_now.echo_fav.strip() and _st_now.echo_fav != TG_BLANK_ADDR:
                        _intended = _echolink_to_asl(_st_now.echo_fav)
                _keep = _intended or linked_node
                if not _multi_link_run_lock.locked():
                    log.warning("more than one direct link (%s) — dropping extras, keeping %s",
                                ",".join(others), _keep)
                    threading.Thread(target=_multi_link_cleanup, args=(_keep,),
                                     daemon=True, name="multi-link-cleanup").start()
        else:
            _multi_link_count = 0
            if len(others) <= 1:
                _multi_link_left_alone = frozenset()
    else:
        _multi_link_count = 0
    return keyed, linked_node, bridge_linked, frozenset(bridge_linked_nodes)

def _dvs_settle() -> None:
    global _dvs_settle_until
    _dvs_settle_until = time.monotonic() + _DVS_SETTLE_MS / 1000.0

_bridge_slot_last_reconnect = {BRIDGE_SLOT_DIGITAL: 0.0, BRIDGE_SLOT_M17: 0.0, BRIDGE_SLOT_PHONE: 0.0}
_bridge_slot_down_polls     = {BRIDGE_SLOT_DIGITAL: 0,   BRIDGE_SLOT_M17: 0,   BRIDGE_SLOT_PHONE: 0}
_BRIDGE_RECONNECT_COOLDOWN = 8.0
_BRIDGE_DOWN_THRESHOLD     = 3

_bridge_node_up_polls:  Dict[str, int]   = {}
_bridge_node_last_reap: Dict[str, float] = {}
_BRIDGE_UP_THRESHOLD    = 3
_BRIDGE_REAP_COOLDOWN   = 8.0
_bridge_reaper_armed    = False

def _arm_bridge_reaper() -> None:
    global _bridge_reaper_armed
    if not _bridge_reaper_armed:
        _bridge_reaper_armed = True
        log.info("bridge reaper armed — page state is now dashboard-owned")

def _bridge_reaper(page: str, active_slot: Optional[int],
                   bridge_linked_nodes: "FrozenSet[str]", has_asl: bool) -> None:
    if not has_asl or not _bridge_reaper_armed:
        _bridge_node_up_polls.clear()
        return

    now = time.monotonic()
    owns = _slot_node(active_slot)

    for node in list(_bridge_node_up_polls):
        if node == owns or node not in bridge_linked_nodes:
            del _bridge_node_up_polls[node]

    for node in sorted(bridge_linked_nodes):
        slot = _bridge_slot_of(node)
        if slot is None or node == owns:
            continue
        _bridge_node_up_polls[node] = _bridge_node_up_polls.get(node, 0) + 1
        if _bridge_node_up_polls[node] < _BRIDGE_UP_THRESHOLD:
            continue
        if (now - _bridge_node_last_reap.get(node, 0.0)) < _BRIDGE_REAP_COOLDOWN:
            continue
        if not _link_try_enter():
            continue
        try:
            _bridge_node_last_reap[node] = now
            _bridge_node_up_polls[node]  = 0
            log.warning("reaper: %s (slot %d, node %s) linked but the %s tab owns %s — dropping",
                        BRIDGE_SLOT_LABELS[slot], slot, node, page, owns or "no bridge")
            _drop_one_link(node)
        finally:
            _link_exit()

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

    _bridge_reaper(page, active_slot, bridge_linked_nodes, st["has_asl"])

    if active_slot is None or not st["has_asl"]:
        return
    if active_slot == BRIDGE_SLOT_M17 and not st["has_m17"]:
        return

    node = _slot_node(active_slot)
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

    if not _link_try_enter():
        return
    try:
        if get_state_fields("page")["page"] != page:
            return
        _bridge_slot_last_reconnect[active_slot] = time.monotonic()
        log.warning("watchdog: %s (slot %d, node %s) not linked on %s tab — reconnecting",
                    BRIDGE_SLOT_LABELS[active_slot], active_slot, node, page)
        _connect(node)
    finally:
        _link_exit()

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
                    _pg = get_state_fields("page")["page"]
                    if _pg == "PHONE" and not _phone_on():
                        _pg = "ASL"
                    _phone_sync_open(_pg)
                    _tot_sync(_pg)
                    _phone_radio_codes_poll()
                except Exception as e:
                    log.warning("_link_poll_loop: phone sync error: %s", e)
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
            return _slot_node(slot) or None
    return None

_PAGE_ENTER = {
    "ASL":   {"dvs_mode": None,    "settle": 1.0, "status": "ASL | Ready",
              "msg": "ASL | Ready"},
    "ECHO":  {"dvs_mode": None,    "settle": 1.0, "status": "Echo | Ready",
              "msg": "Echo | Ready"},
    "DMR":   {"dvs_mode": "DMR",   "settle": 0.0, "status": "DMR | Ready — pick a TG",
              "msg": "DMR ready — pick a TG"},
    "STFU":  {"dvs_mode": "STFU",  "settle": 0.0, "status": "STFU | Ready — pick a TG",
              "msg": "STFU ready — pick a TG"},
    "YSF":   {"dvs_mode": "YSF",   "settle": 0.0, "status": "YSF | Ready — pick a TG",
              "msg": "YSF ready — pick a TG"},
    "FCS":   {"dvs_mode": "YSF",   "settle": 0.0, "status": "FCS | Ready — pick a room",
              "msg": "FCS ready — pick a room"},
    "P25":   {"dvs_mode": "P25",   "settle": 0.0, "status": "P25 | Ready — pick a TG",
              "msg": "P25 ready — pick a TG"},
    "NXDN":  {"dvs_mode": "NXDN",  "settle": 0.0, "status": "NXDN | Ready — pick a TG",
              "msg": "NXDN ready — pick a TG"},
    "DSTAR": {"dvs_mode": "DSTAR", "settle": 0.0, "status": "DSTAR | Ready — pick a TG",
              "msg": "DSTAR ready — pick a TG"},
    "XLX":   {"dvs_mode": "DSTAR", "settle": 0.0, "status": "XLX | Ready — pick a reflector",
              "msg": "XLX ready — pick a reflector"},
    "M17":   {"dvs_mode": None,    "settle": 0.0, "status": "M17 | Ready — pick a reflector",
              "msg": "M17 ready — pick a reflector"},
    "PHONE": {"dvs_mode": None,    "settle": 1.0, "status": "Phone | Ready",
              "msg": "Phone ready"},
}

def _leave_page(prev_page: str, next_page: str, force: bool = False) -> None:
    if prev_page == next_page and not force:
        return
    try:
        if prev_page in ("DSTAR", "XLX"):
            _dvs("tune", DSTAR_UNLINK)
        elif prev_page == "PHONE" and prev_page != next_page:
            _phone_hangup_all()
        elif prev_page == "M17" and prev_page != next_page:
            ok, err = _write_m17_ini(_m17_ini_placeholder(_effective_callsign(get_state())))
            if ok:
                _svc_restart(M17_SERVICE)
            else:
                log.warning("_leave_page: M17 placeholder ini write failed: %s", err)
    except Exception as e:
        log.warning("_leave_page: %s -> %s teardown error: %s", prev_page, next_page, e)
    _gateway_svc_leave(prev_page, next_page)

def _enter_page(page: str, retune: bool = False) -> None:
    spec = _PAGE_ENTER.get(page)
    if spec is None:
        log.warning("_enter_page: unknown page %r — ignored", page)
        return
    dvs_mode = spec["dvs_mode"]
    _link_enter()
    try:
        _arm_bridge_reaper()
        st        = get_state()
        prev_page = st.page
        keep      = _active_bridge_node(page)

        if prev_page != page or retune:
            _leave_page(prev_page, page, force=retune)
        if prev_page == "M17" and page != "M17":
            _bridge_slot_down_polls[BRIDGE_SLOT_M17] = 0

        if st.has_asl:
            dropped = _drop_links(keep=keep, what=f"enter-{page}")
            if dropped and spec["settle"]:
                time.sleep(spec["settle"])

        if not _gateway_svc_enter(page):
            set_state(page=page, current_fav=None, current_fav_node=None, echo_fav=None,
                      status=f"{page} | Gateway service failed to start — check systemctl",
                      **({"current_dvs_mode": dvs_mode} if dvs_mode else {}))
            return

        _dvs("tune", TG_DISCONNECT)
        if dvs_mode:
            _dvs_settle()
            _dvs("mode", dvs_mode)

        if keep and st.has_asl and (page != "M17" or st.has_m17):
            _connect(keep)

        set_state(page=page, current_fav=None, current_fav_node=None, echo_fav=None,
                  status=spec["status"],
                  **({"current_dvs_mode": dvs_mode} if dvs_mode else {}))
        try:
            _cpuweight_apply_for_page(page)
        except Exception:
            log.warning("_cpuweight_apply_for_page failed for %s", page, exc_info=True)
    finally:
        _link_exit()

def _clear_foreign_link() -> Optional[str]:
    st = get_state()
    node = st.linked_node
    if not node or node == "0" or _is_bridge_node(node):
        return None
    _dash = st.current_fav_node or (
        _echolink_to_asl(st.echo_fav)
        if st.echo_fav and st.echo_fav.strip() and st.echo_fav != TG_BLANK_ADDR
        else None
    )
    if node == _dash:
        return None
    was_perm = _drop_one_link(node)
    log.info("Auto-clearing foreign link: node %s%s (page %s)", node,
             " (permanent, ilink 11)" if was_perm else "", st.page)
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

def _ensure_page(page: str) -> None:
    cur = get_state().page
    if cur != page:
        log.info("%s connect asked for while the server page is %s — entering %s first",
                 page, cur, page)
        _enter_page(page)

@_link_locked
def action_switch_tab(page: str) -> Tuple[bool, str]:
    page = page.upper()
    spec = _PAGE_ENTER.get(page)
    if spec is None:
        return False, f"Unknown page '{page}'"
    _enter_page(page)
    if page == "STFU":
        threading.Thread(
            target=lambda: set_state(stfu_server=detect_stfu_server()),
            daemon=True,
        ).start()
    return True, spec["msg"]

_PAGE_RETUNE_MSG = {
    "ASL":   "ASL re-tuned",
    "ECHO":  "Echo re-tuned",
    "M17":   "M17 re-tuned",
    "XLX":   "XLX re-tuned",
    "FCS":   "FCS re-tuned",
    "DMR":   "DMR mode re-tuned",
    "STFU":  "STFU mode re-tuned — services restarted",
    "YSF":   "YSF mode re-tuned",
    "P25":   "P25 mode re-tuned",
    "NXDN":  "NXDN mode re-tuned",
    "DSTAR": "DSTAR mode re-tuned",
    "PHONE": "Phone re-tuned",
}

@_link_locked
def action_retune_tab(page: str, server_name: str = "") -> Tuple[bool, str]:
    page = page.upper()
    if page not in _PAGE_ENTER:
        return False, f"Unknown page '{page}'"
    st = get_state()

    if page == "STFU":
        _svc_restart("stfu.service")
        _svc_restart("mmdvm_bridge")

    _enter_page(page, retune=True)

    if page == "STFU":
        threading.Thread(
            target=lambda: set_state(stfu_server=detect_stfu_server()),
            daemon=True,
        ).start()

    if page == "DMR":
        target = server_name.strip() or st.active_dmr_server
        if target:
            ok, msg = action_switch_dmr_server(target)
            if not ok:
                return False, msg
            return True, f"DMR re-tuned → {target}"

    return True, _PAGE_RETUNE_MSG[page]

@_link_locked
def action_tune(mode: str, tg: str, name: str) -> Tuple[bool, str]:
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
        if st.page != mode:
            return True, f"{mode} | Disconnected"
        if st.has_asl:
            _clear_foreign_link()
        set_state(current_fav=None, current_fav_node=None, echo_fav=None,
                  status=f"{mode} | DISCONNECTED")
        return True, f"{mode} | Disconnected"

    dvs_mode = "YSF" if mode == "FCS" else mode
    try:
        tune_str = _fcs_to_tune(tg) if mode == "FCS" else tg
    except ValueError as exc:
        return False, str(exc)

    _ensure_page(mode)
    st = get_state()
    _clear_foreign_link()

    bridge = _cfg.bridge_nodes[BRIDGE_SLOT_DIGITAL]
    if st.has_asl and bridge and bridge not in st.bridge_linked_nodes:
        _link_enter()
        try:
            _connect(bridge)
        finally:
            _link_exit()

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
        if _dvs_timed_out(out):
            return False, (f"Tune to {tune_str} is taking longer than "
                           f"{_DVS_TUNE_TIMEOUT_SEC}s (a 44net tunnel can slow the "
                           f"system) — it may still be completing. Check the tab "
                           f"before retrying.")
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

@_link_locked
def _do_dstar_family_connect(page: str, base: str, module: str, name: str) -> Tuple[bool, str]:
    base   = base.strip().upper()
    module = module.strip().upper()[:1]
    is_xlx = (page == "XLX")
    if not base:
        return False, ("XLX reflector base must not be empty" if is_xlx
                        else "Reflector base must not be empty")
    if not module or not module.isalpha():
        return False, f"Invalid module letter: '{module}'"

    if len(base) > _DSTAR_BASE_LEN:
        return False, (f"'{base}' is too long for a D-Star callsign field "
                       f"(max {_DSTAR_BASE_LEN} characters before the module)")
    tune_str = f"{base.ljust(_DSTAR_BASE_LEN)}{module}L"
    _ensure_page(page)
    st = get_state()
    _clear_foreign_link()
    _dvs("tune", DSTAR_UNLINK)
    _dvs("tune", TG_DISCONNECT)
    _dvs_settle()
    bridge = _cfg.bridge_nodes[BRIDGE_SLOT_DIGITAL]
    if st.has_asl and bridge and bridge not in st.bridge_linked_nodes:
        _connect(bridge)
    _dvs("mode", "DSTAR")
    remaining = _dvs_settle_until - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)
    ok, out = _dvs("tune", tune_str)
    if not ok:
        fail_label = "XLX" if is_xlx else "D-STAR"
        if _dvs_timed_out(out):
            return False, (f"{fail_label} tune to {tune_str} is taking longer than "
                           f"{_DVS_TUNE_TIMEOUT_SEC}s (a 44net tunnel can slow the "
                           f"system) — it may still be completing. Check the tab "
                           f"before retrying.")
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

@_link_locked
def action_dstar_disconnect() -> Tuple[bool, str]:
    _dvs("tune", DSTAR_UNLINK)
    _dvs("tune", TG_DISCONNECT)
    _dvs_settle()
    set_state(current_fav=None, current_fav_node=None, status="DSTAR | Ready")
    return True, "D-STAR disconnected"

@_link_locked
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

@_link_locked
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
    _ensure_page("M17")
    st = get_state()


    _clear_foreign_link()


    _dvs("tune", TG_DISCONNECT)


    callsign = _effective_callsign(st)
    ok, err = _write_m17_ini(_m17_ini_content(callsign, base, ip, module))
    if not ok:
        return False, f"Could not write {M17_INI_PATH}: {err}"
    _svc_restart(M17_SERVICE)

    m17_node = _cfg.bridge_nodes[BRIDGE_SLOT_M17]
    if st.has_asl and m17_node and m17_node not in st.bridge_linked_nodes:
        _connect(m17_node)
        time.sleep(1.5)

    fav = f"{base}|{module}"
    label = f"M17 | {name} | {base} Mod-{module} ({ip})"
    set_state(page="M17", status=label, current_fav=fav, current_fav_node=(m17_node or None))
    return True, f"M17 connected: {name} ({base} Mod-{module})"

@_link_locked
def action_m17_disconnect() -> Tuple[bool, str]:
    _link_enter()
    try:
        st = get_state()
        callsign = _effective_callsign(st)


        m17_node = _cfg.bridge_nodes[BRIDGE_SLOT_M17]
        if st.has_asl and m17_node:
            _disconnect(m17_node)
        ok, err = _write_m17_ini(_m17_ini_placeholder(callsign))
        if ok:
            _svc_restart(M17_SERVICE)
        set_state(current_fav=None, current_fav_node=None, status="M17 | Ready — pick a reflector")
        if not ok:
            return False, f"Disconnected link, but ini write failed: {err}"
        return True, "M17 disconnected"
    finally:
        _link_exit()

@_link_locked
def _do_asl_connect(node: str, name: str):
    node = str(node).strip()
    if not node.isdigit():
        return False, f"Invalid node number: {node}"
    if _is_bridge_node(node):
        return False, _bridge_reject_msg(node, "an ASL node")
    _link_enter()
    _reset_perm_link_settle()
    try:
        _drop_links(keep=None, what="asl-connect")
        _connect(node)
        time.sleep(1.5)
        _arm_bridge_reaper()
        set_state(page="ASL", current_fav=node, current_fav_node=node, echo_fav=None,
                  status=f"ASL | {name} | {node}")
    finally:
        _link_exit()
    return True, f"Connected {name} ({node})"

def action_connect_by_number(node: str) -> Tuple[bool, str]:
    node = str(node).strip()
    if not node.isdigit():
        return False, f"Invalid node number: {node}"
    return _do_asl_connect(node, f"Node {node}")

def action_asl_connect(node: str, name: str) -> Tuple[bool, str]:
    return _do_asl_connect(str(node).strip(), name)

@_link_locked
def action_asl_disconnect_current() -> Tuple[bool, str]:
    st = get_state()
    if st.current_fav and st.current_fav not in _bridge_set():
        if _drop_one_link(st.current_fav):
            log.info("ASL disconnect: %s is a permanent link — dropped with ilink 11",
                     st.current_fav)
    _clear_foreign_link()
    set_state(current_fav=None, current_fav_node=None, status="ASL | Ready")
    return True, "ASL disconnected"

@_link_locked
def action_disc_perm_link() -> Tuple[bool, str]:
    st = get_state()
    node = st.linked_node
    if not node:
        return False, "No active link to disconnect"
    was_perm = _drop_one_link(node)
    set_state(linked_node=None)
    if was_perm:
        return True, f"Permanent link to node {node} disconnected"
    return True, f"Link to node {node} disconnected"

@_link_locked
def _do_echo_connect(node: str, name: str):
    node = str(node).strip()
    if not node.isdigit():
        return False, f"Invalid node number: {node}"
    if _is_bridge_node(_echolink_to_asl(node)):
        return False, _bridge_reject_msg(_echolink_to_asl(node), "an EchoLink node")
    _link_enter()
    _reset_perm_link_settle()
    try:
        asl_node = _echolink_to_asl(node)
        _drop_links(keep=None, what="echo-connect")
        _connect(asl_node)
        time.sleep(1.5)
        _arm_bridge_reaper()
        set_state(page="ECHO", echo_fav=node, status=f"Echo | {name} | {node}")
    finally:
        _link_exit()
    return True, f"Echo connected {name} ({node})"

def action_echo_connect(node: str, name: str) -> Tuple[bool, str]:
    return _do_echo_connect(str(node).strip(), name)

def action_echo_connect_by_number(node: str) -> Tuple[bool, str]:
    node = str(node).strip()
    if not node.isdigit():
        return False, f"Invalid node number: {node}"
    if len(node) > 7:
        return False, f"EchoLink node numbers are 1-7 digits (got '{node}')"
    return _do_echo_connect(node, f"Node {node}")

@_link_locked
def action_echo_disconnect() -> Tuple[bool, str]:
    st = get_state()
    if st.echo_fav and st.echo_fav.strip() and st.echo_fav != TG_BLANK_ADDR:
        _drop_one_link(_echolink_to_asl(st.echo_fav))
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

_CPUW_BASELINE = 100
_CPUW_BRIDGE   = 200
_CPUW_ACTIVE   = 300
_CPUW_CORE     = 500

_CPUW_ASTERISK_SERVICE = "asterisk.service"
_CPUW_BRIDGE_SERVICES  = ("mmdvm_bridge.service", "analog_bridge.service")
_CPUW_SYSMON_SERVICE   = "sysmon.service"
_CPUW_DIGITAL_SET = frozenset({"DMR", "YSF", "P25", "NXDN", "FCS", "DSTAR", "XLX", "STFU"})

_cpuw_lock  = threading.Lock()
_cpuw_state = {"bridge_up": False, "active_gw": None, "m17_up": False, "sysmon_up": False,
               "saved_bridge_up": False, "saved_gw": None, "saved_m17_up": False}

def _set_cpuweight(svc: str, weight: int) -> None:
    rc = run(["systemctl", "set-property", "--runtime", svc, f"CPUWeight={weight}"], timeout=5)[1]
    if rc != 0:
        log.warning("_set_cpuweight: failed to set %s CPUWeight=%d (rc=%d)", svc, weight, rc)

def _cpuweight_pin_core() -> None:
    _set_cpuweight(_CPUW_ASTERISK_SERVICE, _CPUW_CORE)

def _cpuweight_apply_for_page(page: str) -> None:
    if not _cfg.cpuweight_enabled:
        return
    with _cpuw_lock:
        if _cpuw_state["sysmon_up"]:
            return
        bridge_needed = page in _CPUW_DIGITAL_SET
        if bridge_needed and not _cpuw_state["bridge_up"]:
            for svc in _CPUW_BRIDGE_SERVICES:
                _set_cpuweight(svc, _CPUW_BRIDGE)
            _cpuw_state["bridge_up"] = True
        elif not bridge_needed and _cpuw_state["bridge_up"]:
            for svc in _CPUW_BRIDGE_SERVICES:
                _set_cpuweight(svc, _CPUW_BASELINE)
            _cpuw_state["bridge_up"] = False

        gw = _GATEWAY_SERVICE_MAP.get(page)
        if gw != _cpuw_state["active_gw"]:
            if gw:
                _set_cpuweight(gw, _CPUW_ACTIVE)
            _cpuw_state["active_gw"] = gw

        m17_needed = page == "M17"
        if m17_needed and not _cpuw_state["m17_up"]:
            _set_cpuweight(M17_SERVICE, _CPUW_ACTIVE)
            _cpuw_state["m17_up"] = True
        elif not m17_needed and _cpuw_state["m17_up"]:
            _set_cpuweight(M17_SERVICE, _CPUW_BASELINE)
            _cpuw_state["m17_up"] = False

def _cpuweight_sysmon_away() -> None:
    if not _cfg.cpuweight_enabled:
        return
    with _cpuw_lock:
        if _cpuw_state["sysmon_up"]:
            return
        _cpuw_state["saved_bridge_up"] = _cpuw_state["bridge_up"]
        _cpuw_state["saved_gw"]        = _cpuw_state["active_gw"]
        _cpuw_state["saved_m17_up"]    = _cpuw_state["m17_up"]
        if _cpuw_state["bridge_up"]:
            for svc in _CPUW_BRIDGE_SERVICES:
                _set_cpuweight(svc, _CPUW_BASELINE)
            _cpuw_state["bridge_up"] = False
        if _cpuw_state["active_gw"]:
            _set_cpuweight(_cpuw_state["active_gw"], _CPUW_BASELINE)
            _cpuw_state["active_gw"] = None
        if _cpuw_state["m17_up"]:
            _set_cpuweight(M17_SERVICE, _CPUW_BASELINE)
            _cpuw_state["m17_up"] = False
        _set_cpuweight(_CPUW_SYSMON_SERVICE, _CPUW_ACTIVE)
        _cpuw_state["sysmon_up"] = True

def _cpuweight_sysmon_resume() -> None:
    if not _cfg.cpuweight_enabled:
        return
    with _cpuw_lock:
        if not _cpuw_state["sysmon_up"]:
            return
        _set_cpuweight(_CPUW_SYSMON_SERVICE, _CPUW_BASELINE)
        _cpuw_state["sysmon_up"] = False
        if _cpuw_state["saved_bridge_up"]:
            for svc in _CPUW_BRIDGE_SERVICES:
                _set_cpuweight(svc, _CPUW_BRIDGE)
            _cpuw_state["bridge_up"] = True
        if _cpuw_state["saved_gw"]:
            _set_cpuweight(_cpuw_state["saved_gw"], _CPUW_ACTIVE)
            _cpuw_state["active_gw"] = _cpuw_state["saved_gw"]
        if _cpuw_state["saved_m17_up"]:
            _set_cpuweight(M17_SERVICE, _CPUW_ACTIVE)
            _cpuw_state["m17_up"] = True

def action_cpuweight_away() -> Tuple[bool, str]:
    try:
        _cpuweight_sysmon_away()
    except Exception:
        log.warning("action_cpuweight_away failed", exc_info=True)
    return True, "ok"

def action_cpuweight_resume() -> Tuple[bool, str]:
    try:
        _cpuweight_sysmon_resume()
    except Exception:
        log.warning("action_cpuweight_resume failed", exc_info=True)
    return True, "ok"

def _cpuweight_enable_all() -> None:
    try:
        _cpuweight_pin_core()
        with _cpuw_lock:
            _cpuw_state["bridge_up"] = False
            _cpuw_state["active_gw"] = None
            _cpuw_state["m17_up"] = False
            _cpuw_state["sysmon_up"] = False
        _cpuweight_apply_for_page(get_state().page)
    except Exception:
        log.warning("_cpuweight_enable_all failed", exc_info=True)

def _cpuweight_reset_all() -> None:
    try:
        _set_cpuweight(_CPUW_ASTERISK_SERVICE, _CPUW_BASELINE)
        for svc in _CPUW_BRIDGE_SERVICES:
            _set_cpuweight(svc, _CPUW_BASELINE)
        for svc in set(_GATEWAY_SERVICE_MAP.values()):
            _set_cpuweight(svc, _CPUW_BASELINE)
        _set_cpuweight(M17_SERVICE, _CPUW_BASELINE)
        _set_cpuweight(_CPUW_SYSMON_SERVICE, _CPUW_BASELINE)
        with _cpuw_lock:
            _cpuw_state["bridge_up"] = False
            _cpuw_state["active_gw"] = None
            _cpuw_state["m17_up"] = False
            _cpuw_state["sysmon_up"] = False
    except Exception:
        log.warning("_cpuweight_reset_all failed", exc_info=True)

def _graceful_notify(st) -> None:
    if st.page in ("DSTAR", "XLX"):
        _dvs("tune", DSTAR_UNLINK)
    _dvs("tune", TG_DISCONNECT)
    time.sleep(0.1)

    if st.has_asl:
        _drop_links(keep=None, what="graceful-notify")

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
    with _link_guard():
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

@_link_locked
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
        if _dvs_timed_out(out):
            return False, (f"{server_name}: the network tune is taking longer than "
                           f"{_DVS_TUNE_TIMEOUT_SEC}s (a 44net tunnel can slow the "
                           f"system) — it may still be completing. Check the DMR tab "
                           f"before retrying.")
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

def _write_script_no_symlink(path: str, content: str, mode: int = 0o755) -> None:
    p = Path(path)
    if p.is_symlink():
        raise OSError(f"refusing to write through pre-existing symlink at {path}")
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
    except Exception:
        raise
    os.chmod(path, mode)

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
            _write_script_no_symlink(path, script, 0o755)
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

_perm_link_since        = 0.0
_perm_link_lock         = threading.Lock()
_PERM_LINK_SETTLE_SEC   = 2.0

def _reset_perm_link_settle() -> None:
    global _perm_link_since
    with _perm_link_lock:
        _perm_link_since = 0.0

def action_get_keyed() -> dict:
    global _perm_link_since
    st = get_state()
    _dashboard_linked = st.current_fav or (
        _echolink_to_asl(st.echo_fav)
        if st.echo_fav and st.echo_fav.strip() and st.echo_fav != TG_BLANK_ADDR
        else None
    )
    raw_on_perm = bool(st.linked_node and st.linked_node != _dashboard_linked)
    _now = time.monotonic()
    with _perm_link_lock:
        if raw_on_perm:
            if _perm_link_since == 0.0:
                _perm_link_since = _now
            _settled = (_now - _perm_link_since) >= _PERM_LINK_SETTLE_SEC
        else:
            _perm_link_since = 0.0
            _settled = False
    on_perm  = raw_on_perm and _settled
    is_known = bool(on_perm and st.linked_node in st.perm_link_nodes)
    return {
        "keyed":          st.keyed,
        "linked_node":    st.linked_node,
        "on_perm_link":   on_perm,
        "perm_link_node": st.linked_node if on_perm else None,
        "is_known_perm":  is_known,
    }

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

def _dmr_servers_public(servers: list) -> list:
    return [{k: v for k, v in s.items() if k != "password"} for s in servers]

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
        "dmr_servers":       _dmr_servers_public(st["dmr_servers"]),
        "active_dmr_server": st["active_dmr_server"],
        "conf_warnings":     list(st["conf_warnings"]),
        "wifimon_shutdown":  _read_wifimon_shutdown_state(),
        "phone":             _phone_status(),
    }

def action_get_dmr_servers_full() -> list:
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
  --mono: Arial, Helvetica, sans-serif;
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
  display: grid;
  grid-template-columns: 1fr minmax(0, auto) 1fr;
  align-items: center;
  column-gap: .5rem;
  padding-bottom: .2rem;
  border-bottom: 1px solid var(--border);
  margin-bottom: .3rem;
  min-height: 2.4rem;
}

/* ── TG indicator ── */
#tg-indicator {
  grid-column: 2;
  justify-self: center;
  min-width: 0;
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
#tg-indicator.ind-phone{color:var(--green);border-color:rgba(0,255,176,.4);background:rgba(0,255,176,.07);text-shadow:0 0 8px rgba(0,255,176,.5)}
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
/* v8.9.0: tabs go grey and ignore taps while a card menu or search box is in use */
.tabs.tabs-locked .tab { opacity: .3; filter: grayscale(1); pointer-events: none; cursor: default; }
.tab.t-asl,.tab.t-echo,.tab.t-dmr,.tab.t-stfu,.tab.t-ysf,.tab.t-fcs,.tab.t-p25,.tab.t-nxdn,.tab.t-dstar,.tab.t-xlx,.tab.t-m17,.tab.t-phone,.tab.t-edit{color:var(--mc);border-color:var(--mc);background:rgba(var(--mc-rgb),.18);box-shadow:0 -2px 18px rgba(var(--mc-rgb),.35);text-shadow:0 0 14px rgba(var(--mc-rgb),1)}
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
.tab.t-phone{--mc:var(--green);--mc-rgb:0,255,176}
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
.row-grid.active-phone{--mc:var(--green);--mc-rgb:0,255,176;background:rgba(var(--mc-rgb),.1);border-left:3px solid var(--mc);padding-left:calc(.9rem - 3px);box-shadow:inset 3px 0 12px rgba(var(--mc-rgb),.1)}
.pt-call{font-family:var(--mono);font-size:.858rem;color:var(--muted);padding:.45rem .9rem;min-height:1.4em;border-bottom:1px solid var(--border)}
.pt-call.pt-live{color:var(--green)}
.pt-call.pt-warn{color:var(--amber)}
.pt-call.pt-talk{color:#ffd700}
#pt-reg-dot.pt-hide{visibility:hidden}
#pg-PHONE .quick-bar{flex-wrap:wrap}
#pg-PHONE .quick-inp{min-width:6.5rem}
#pg-PHONE .pt-signin{font-size:.8em;opacity:.8;white-space:nowrap}#pg-PHONE .pt-signin-bad{color:#ff6b6b;opacity:1}
#pg-PHONE .btn:disabled{opacity:.35;cursor:default;pointer-events:none}
.pt-tone{padding:.48rem .7rem}
.pt-callrow{display:flex;align-items:center;flex-wrap:wrap;gap:.35rem .5rem;padding:.3rem .9rem;border-bottom:1px solid var(--border)}
.pt-callrow .pt-call{border-bottom:0;padding:.15rem 0;flex:1 1 10rem}
#pt-cbtns{display:flex;flex-wrap:wrap;gap:.35rem}
#pt-cbtns:empty{display:none}
#pt-cbtns .btn{padding:.3rem .6rem;font-size:.792rem}
#pt-kp-overlay{display:none;position:fixed;inset:0;z-index:1000;background:rgba(0,0,0,.72);backdrop-filter:blur(4px);align-items:center;justify-content:center}
#pt-kp-overlay.open{display:flex}
#ph-dlg-overlay{display:none;position:fixed;inset:0;z-index:1000;background:rgba(0,0,0,.72);backdrop-filter:blur(4px);align-items:center;justify-content:center}
#ph-dlg-overlay.open{display:flex}
#ph-dlg-box{background:linear-gradient(135deg,#1a2438,#161e2e);border:1px solid var(--border2);border-radius:8px;padding:.9rem 1.1rem 1.1rem;width:min(480px,92vw);max-height:86vh;overflow-y:auto;box-shadow:0 20px 80px rgba(0,0,0,.9)}
#ph-dlg-hdr{display:flex;align-items:center;justify-content:space-between;font-family:var(--mono);color:var(--warn,#ffb020);margin-bottom:.5rem}
#ph-dlg-body{font-size:.86rem;line-height:1.45;color:var(--text)}
#ph-dlg-body ul{margin:.3rem 0 .6rem 1.1rem;padding:0}
#ph-dlg-body li{margin:.15rem 0}
#ph-dlg-btns{display:flex;gap:.5rem;justify-content:flex-end;margin-top:.8rem}
.ph-hdr-r{display:flex;align-items:center;gap:.6rem}
.ph-act-lbl{letter-spacing:.08em}
#pt-kp-box{background:linear-gradient(135deg,#1a2438,#161e2e);border:1px solid var(--border2);border-radius:8px;padding:.9rem 1.1rem 1.2rem;width:min(300px,88vw);box-shadow:0 20px 80px rgba(0,0,0,.9)}
#pt-kp-hdr{display:flex;align-items:center;justify-content:space-between;font-family:var(--mono);color:var(--text-bright);margin-bottom:.5rem}
#pt-kp-x{padding:.25rem .6rem}
#pt-kp-sent{font-family:var(--mono);font-size:1.2rem;color:var(--green);min-height:1.6em;text-align:center;letter-spacing:.2em;margin-bottom:.6rem;overflow:hidden;white-space:nowrap}
#pt-kp-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem}
#pt-kp-grid .btn{font-size:1.4rem;padding:.75rem 0}
#pt-rep-overlay{display:none;position:fixed;inset:0;z-index:1000;background:rgba(0,0,0,.72);backdrop-filter:blur(4px);align-items:center;justify-content:center}
#pt-rep-overlay.open{display:flex}
#pt-rep-box{background:linear-gradient(135deg,#1a2438,#161e2e);border:1px solid var(--border2);border-radius:8px;padding:.9rem 1.1rem 1.1rem;width:min(680px,94vw);box-shadow:0 20px 80px rgba(0,0,0,.9)}
#pt-rep-text{width:100%;box-sizing:border-box;height:min(60vh,420px);resize:vertical;font-family:var(--mono);font-size:.72rem;color:var(--text-bright);background:rgba(0,0,0,.35);border:1px solid var(--border);border-radius:4px;padding:.5rem;white-space:pre;overflow:auto}
#pt-rep-hdr{display:flex;align-items:center;justify-content:space-between;font-family:var(--mono);color:var(--text-bright);margin-bottom:.5rem}
#pt-rep-btns{display:flex;gap:.5rem;justify-content:flex-end;margin-top:.6rem}
#pt-kp-audio{margin-top:.7rem;font-family:var(--mono);font-size:.792rem;color:var(--muted);min-height:1.2em}
#pt-kp-audio .ok{color:var(--green)}
#pt-kp-audio .warn{color:var(--amber);display:block;margin-top:.2rem}
#pt-kp-mode{margin-top:.8rem;padding-top:.6rem;border-top:1px solid var(--border);font-family:var(--mono);font-size:.792rem;color:var(--muted)}
#pt-kp-mode.pt-hide{display:none}
#pt-kp-radio{margin-top:.6rem;font-family:var(--mono);font-size:.72rem;color:var(--muted);line-height:1.4}
#pt-kp-path{margin-top:.8rem;padding-top:.6rem;border-top:1px solid var(--border);font-family:var(--mono);font-size:.792rem;color:var(--muted)}
#pt-kp-path select{width:100%;margin-top:.3rem}
#pt-kp-mode-row{display:flex;gap:.4rem;margin-top:.3rem}
#pt-kp-mode-row select{flex:1 1 auto;min-width:0}
#pt-kp-keep{padding:.3rem .6rem;font-size:.792rem;white-space:nowrap}
#pt-kp-mode-note{margin-top:.35rem;min-height:1.2em}
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
/* ── Quick links (v8.8.0) — instmon Go-button look ── */
.ql-group {
  display: flex;
  gap: .35rem;
  align-items: center;
  min-width: 0;
}
.ql-left  { justify-content: flex-start; }
.ql-right { justify-content: flex-end; }
.ql {
  font-family: var(--mono);
  font-size: .72rem;
  font-weight: 700;
  letter-spacing: .04em;
  text-transform: uppercase;
  text-decoration: none;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
  color: var(--amber);
  border: 1px solid var(--amber-dim);
  background: rgba(255,61,90,.15);
  text-shadow: 0 0 8px rgba(255,208,64,.4);
  border-radius: 4px;
  padding: .26rem .55rem;
  cursor: pointer;
  transition: all .14s;
}
.ql:hover  { filter: brightness(1.5); box-shadow: 0 0 10px currentColor; }
.ql:active { transform: scale(.95); }
.ql:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.ql.ql-off {
  opacity: .4;
  cursor: default;
  filter: none;
  box-shadow: none;
  background: transparent;
  pointer-events: none;
}
@media (max-width: 900px) {
  .ql-group { gap: .28rem; }
  .ql { font-size: .66rem; padding: .24rem .42rem; }
  #tg-indicator { font-size: 1.1rem; max-width: 230px; }
}
@media (max-width: 560px) {
  .sec-lbl-row {
    grid-template-columns: repeat(6, minmax(0, 1fr));
    row-gap: .4rem;
    column-gap: .25rem;
    padding-top: .15rem;
  }
  .ql-group { display: contents; }
  #tg-indicator { grid-column: 1 / -1; grid-row: 1; max-width: 92%; }
  .ql {
    grid-row: 2;
    font-size: clamp(.45rem, 2.1vw, .66rem);
    padding: .32rem 0;
    letter-spacing: 0;
  }
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

/* ── FCS browse card (v8.4.2) ── */
.fcs-card {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: .45rem;
  padding: .55rem .9rem;
  border-bottom: 1px solid var(--border);
  background: #111828;
  transition: opacity .15s;
}
.fcs-card.grid-busy { opacity: .25; pointer-events: none; }
.fcs-select {
  font-family: var(--mono);
  font-size: .902rem;
  padding: .35rem .55rem;
  background: var(--surface2);
  color: var(--fcs);
  border: 1px solid var(--fcs-dim);
  border-radius: 3px;
  outline: none;
  cursor: pointer;
  min-width: 0;
  text-overflow: ellipsis;
  transition: border-color .15s;
}
#fcs-srv-select  { flex: 1 1 8rem;  max-width: 12rem; }
#fcs-room-select { flex: 2 1 10rem; max-width: 22rem; }
.fcs-select:focus { border-color: var(--fcs); box-shadow: 0 0 6px rgba(0,196,160,.3); }
.fcs-select:disabled { opacity: .4; cursor: default; }
.fcs-select option { background: var(--surface2); color: var(--text-bright); }
.fcs-card .btn:disabled { opacity: .35; cursor: default; pointer-events: none; }
.fcs-card .btn:focus-visible,
.fcs-card .btn-last:focus-visible { outline: 2px solid var(--fcs); outline-offset: 2px; }
.fcs-card-msg { flex: 0 0 100%; font-size: .78rem; line-height: 1.35; color: #7a9ec0; }
.fcs-card-msg.warn { color: var(--amber); }
.fcs-fav-hdr { color: var(--fcs); }
@media (prefers-reduced-motion: reduce) {
  .fcs-card, .fcs-select { transition: none; }
}

/* ── M17 browse card (v8.6.2) ── */
.m17-card {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: .45rem;
  padding: .55rem .9rem;
  border-bottom: 1px solid var(--border);
  background: #111828;
  transition: opacity .15s;
}
.m17-card.grid-busy { opacity: .25; pointer-events: none; }
.m17-select {
  font-family: var(--mono);
  font-size: .902rem;
  padding: .35rem .55rem;
  background: var(--surface2);
  color: var(--purple);
  border: 1px solid var(--purple-dim);
  border-radius: 3px;
  outline: none;
  cursor: pointer;
  min-width: 0;
  text-overflow: ellipsis;
  transition: border-color .15s;
}
#m17-ref-select { flex: 2 1 12rem; max-width: 24rem; }
#m17-mod-select { flex: 1 1 8rem;  max-width: 12rem; }
.m17-select:focus { border-color: var(--purple); box-shadow: 0 0 6px rgba(212,102,255,.3); }
.m17-select:disabled { opacity: .4; cursor: default; }
.m17-select option { background: var(--surface2); color: var(--text-bright); }
.m17-card .btn:disabled { opacity: .35; cursor: default; pointer-events: none; }
.m17-card .btn:focus-visible,
.m17-card .btn-last:focus-visible { outline: 2px solid var(--purple); outline-offset: 2px; }
.m17-card-msg { flex: 0 0 100%; font-size: .78rem; line-height: 1.35; color: #7a9ec0; }
.m17-card-msg.warn { color: var(--amber); }
.m17-fav-hdr { color: var(--purple); }
@media (prefers-reduced-motion: reduce) {
  .m17-card, .m17-select { transition: none; }
}

/* ── XLX / D-STAR browse cards (v8.9.1) — one shared look, colour per tab ── */
.rfc-card {
  --rc: var(--teal); --rc-dim: var(--teal-dim); --rc-rgb: 0,255,229;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: .45rem;
  padding: .55rem .9rem;
  border-bottom: 1px solid var(--border);
  background: #111828;
  transition: opacity .15s;
}
.rfc-card.rfc-dstar { --rc: var(--pink); --rc-dim: var(--pink-dim); --rc-rgb: 255,68,204; }
.rfc-card.grid-busy { opacity: .25; pointer-events: none; }
.rfc-input, .rfc-select {
  font-family: var(--mono);
  font-size: .902rem;
  padding: .35rem .55rem;
  background: var(--surface2);
  color: var(--rc);
  border: 1px solid var(--rc-dim);
  border-radius: 3px;
  outline: none;
  min-width: 0;
  text-overflow: ellipsis;
  transition: border-color .15s;
}
.rfc-input  { flex: 1 1 8rem; max-width: 14rem; }
.rfc-input::placeholder { color: #5a7898; }
.rfc-select { cursor: pointer; flex: 3 1 12rem; max-width: 22rem; }
.rfc-select.rfc-mod { flex: 0 0 3.6rem; max-width: 3.6rem; padding-left: .4rem; padding-right: .2rem; text-align: center; }
.rfc-btns { display: flex; gap: .45rem; align-items: center; }
.rfc-input:focus, .rfc-select:focus { border-color: var(--rc); box-shadow: 0 0 6px rgba(var(--rc-rgb),.3); }
.rfc-select:disabled, .rfc-input:disabled { opacity: .4; cursor: default; }
.rfc-select option { background: var(--surface2); color: var(--text-bright); }
.rfc-card .btn:disabled { opacity: .35; cursor: default; pointer-events: none; }
.rfc-card .btn:focus-visible,
.rfc-card .btn-last:focus-visible { outline: 2px solid var(--rc); outline-offset: 2px; }
.rfc-card-msg { flex: 0 0 100%; font-size: .78rem; line-height: 1.35; color: #7a9ec0; overflow-wrap: anywhere; }
.rfc-card-msg.warn { color: var(--amber); }
.xlx-fav-hdr { color: var(--teal); }
.dstar-fav-hdr { color: var(--pink); }
/* Phone: search on its own row, menus on the next, buttons below them. */
@media (max-width: 600px) {
  .rfc-input  { flex-basis: 100%; max-width: none; }
  .rfc-select:not(.rfc-mod) { flex: 1 1 0; max-width: none; }
  .rfc-btns   { flex-basis: 100%; }
}
@media (prefers-reduced-motion: reduce) {
  .rfc-card, .rfc-input, .rfc-select { transition: none; }
}

/* ── YSF browse card (v8.8.3) ── */
.ysf-card {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: .45rem;
  padding: .55rem .9rem;
  border-bottom: 1px solid var(--border);
  background: #111828;
  transition: opacity .15s;
}
.ysf-card.grid-busy { opacity: .25; pointer-events: none; }
.ysf-input, .ysf-select {
  font-family: var(--mono);
  font-size: .902rem;
  padding: .35rem .55rem;
  background: var(--surface2);
  color: var(--purple);
  border: 1px solid var(--purple-dim);
  border-radius: 3px;
  outline: none;
  min-width: 0;
  text-overflow: ellipsis;
  transition: border-color .15s;
}
.ysf-select { cursor: pointer; }
.ysf-input::placeholder { color: #5a7898; }
#ysf-cc-select  { flex: 1 1 7rem;  max-width: 11rem; }
#ysf-filter     { flex: 1 1 8rem;  max-width: 14rem; }
#ysf-ref-select { flex: 3 1 12rem; max-width: 26rem; }
.ysf-input:focus, .ysf-select:focus { border-color: var(--purple); box-shadow: 0 0 6px rgba(212,102,255,.3); }
.ysf-select:disabled, .ysf-input:disabled { opacity: .4; cursor: default; }
.ysf-select option { background: var(--surface2); color: var(--text-bright); }
.ysf-card .btn:disabled { opacity: .35; cursor: default; pointer-events: none; }
.ysf-card .btn:focus-visible,
.ysf-card .btn-last:focus-visible { outline: 2px solid var(--purple); outline-offset: 2px; }
.ysf-card-msg { flex: 0 0 100%; font-size: .78rem; line-height: 1.35; color: #7a9ec0; overflow-wrap: anywhere; }
.ysf-card-msg.warn { color: var(--amber); }
.ysf-fav-hdr { color: var(--purple); }
@media (prefers-reduced-motion: reduce) {
  .ysf-card, .ysf-input, .ysf-select { transition: none; }
}

/* ── P25 / NXDN browse cards (v8.8.8) — one shared look, colour per tab ── */
.tgc-card {
  --tc: var(--orange); --tc-dim: var(--orange-dim); --tc-rgb: 255,170,34;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: .45rem;
  padding: .55rem .9rem;
  border-bottom: 1px solid var(--border);
  background: #111828;
  transition: opacity .15s;
}
.tgc-card.tgc-nxdn { --tc: var(--lime); --tc-dim: var(--lime-dim); --tc-rgb: 212,255,0; }
.tgc-card.tgc-stfu { --tc: var(--green); --tc-dim: var(--green-dim); --tc-rgb: 0,255,176; }
.tgc-card.tgc-asl  { --tc: var(--teal); --tc-dim: var(--teal-dim); --tc-rgb: 0,255,229; }
.tgc-card.tgc-echo { --tc: var(--amber); --tc-dim: var(--amber-dim); --tc-rgb: 255,208,64; }   /* v9.3.60 */
.tgc-card.grid-busy { opacity: .25; pointer-events: none; }
.tgc-input, .tgc-select {
  font-family: var(--mono);
  font-size: .902rem;
  padding: .35rem .55rem;
  background: var(--surface2);
  color: var(--tc);
  border: 1px solid var(--tc-dim);
  border-radius: 3px;
  outline: none;
  min-width: 0;
  text-overflow: ellipsis;
  transition: border-color .15s;
}
.tgc-select { cursor: pointer; flex: 3 1 12rem; max-width: 26rem; }
.tgc-input  { flex: 1 1 8rem; max-width: 14rem; }
.tgc-input::placeholder { color: #5a7898; }
.tgc-input:focus, .tgc-select:focus { border-color: var(--tc); box-shadow: 0 0 6px rgba(var(--tc-rgb),.3); }
.tgc-select:disabled, .tgc-input:disabled { opacity: .4; cursor: default; }
.tgc-select option { background: var(--surface2); color: var(--text-bright); }
.tgc-card .btn:disabled { opacity: .35; cursor: default; pointer-events: none; }
.tgc-card .btn:focus-visible,
.tgc-card .btn-last:focus-visible { outline: 2px solid var(--tc); outline-offset: 2px; }
.tgc-card-msg { flex: 0 0 100%; font-size: .78rem; line-height: 1.35; color: #7a9ec0; overflow-wrap: anywhere; }
.tgc-card-msg.warn { color: var(--amber); }
.p25-fav-hdr  { color: var(--orange); }
.nxdn-fav-hdr { color: var(--lime); }
.stfu-fav-hdr { color: var(--green); }
.asl-fav-hdr  { color: var(--teal); }
@media (prefers-reduced-motion: reduce) {
  .tgc-card, .tgc-input, .tgc-select { transition: none; }
}

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
.ph-net { border: 1px solid var(--border); border-radius: 6px; padding: .5rem .6rem; margin: .45rem 0; background: #0f1522; }
.ph-net-hdr { display: flex; justify-content: space-between; align-items: center; gap: .5rem; margin-bottom: .35rem; font-family: var(--mono); font-size: .8rem; color: var(--text-bright); }
.ph-fav-row { display: grid; grid-template-columns: 1.2fr 1fr 1fr 2.2rem; gap: .4rem; margin: .25rem 0; }
.ph-fav-clr { padding: .2rem .4rem; }
@media (max-width: 560px) { .ph-fav-row { grid-template-columns: 1fr 1fr 2.2rem; } .ph-fav-row [data-fk="name"] { grid-column: 1 / -1; } }
.ph-hint { font-family: var(--mono); font-size: .68rem; color: #6f8aa8; margin: .25rem 0 0; }
.ph-hint.ph-warn { color: var(--amber); }
.ph-lines { font-family: var(--mono); font-size: .72rem; color: var(--text-bright); background: rgba(0,0,0,.3); border: 1px solid var(--border); border-radius: 4px; padding: .4rem .6rem; margin: .3rem 0 0; overflow-x: auto; user-select: all; white-space: pre; }
.ph-msg { font-family: var(--mono); font-size: .75rem; color: var(--muted); margin-top: .35rem; min-height: 1em; }
.ph-btn-pair { display: grid; grid-template-columns: 1fr 1.3fr; gap: .4rem; }
.pt-vm-pin { margin-left: .5rem; padding: .1rem .55rem; font-size: .72rem; vertical-align: middle; }
.ph-auto-tag { display: none; margin-left: .4rem; padding: 0 .3rem; border: 1px solid var(--teal, #2bb3a3); border-radius: 3px; font-size: .62rem; letter-spacing: .08em; color: var(--teal, #2bb3a3); text-transform: lowercase; }
.cfg-field.ph-auto-on .ph-auto-tag { display: inline-block; }
.ph-sub { font-family: var(--mono); font-size: .7rem; letter-spacing: .12em; text-transform: uppercase; color: #5a7898; margin: .5rem 0 .1rem; grid-column: 1 / -1; }
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

/* ── wifimon shutdown popup — dedicated, non-dismissible overlay.        ── */
/* Kept entirely separate from #modal-overlay / #err-modal-overlay so it  */
/* can never be closed, replaced, or hidden by an unrelated confirm/error */
/* dialog. z-index sits above everything else in the app.                 */
#wfm-shutdown-overlay {
  display: none;
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: rgba(0,0,0,.85);
  backdrop-filter: blur(4px);
  align-items: center;
  justify-content: center;
}
#wfm-shutdown-overlay.open { display: flex; }
#wfm-shutdown-box {
  background: linear-gradient(135deg, #2a0a0e, #1a0608);
  border: 2px solid var(--red);
  border-radius: 8px;
  padding: 2rem 2.2rem 1.6rem;
  min-width: 320px;
  max-width: 90vw;
  box-shadow: 0 20px 90px rgba(255,61,90,.4);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
  text-align: center;
  animation: wfmPulse 2s ease-in-out infinite;
}
@keyframes wfmPulse {
  0%, 100% { box-shadow: 0 20px 90px rgba(255,61,90,.4); }
  50%      { box-shadow: 0 20px 110px rgba(255,61,90,.75); }
}
#wfm-shutdown-hdr {
  font-family: var(--mono);
  font-size: .88rem;
  letter-spacing: .22em;
  text-transform: uppercase;
  color: var(--red);
  text-shadow: 0 0 12px rgba(255,61,90,.8);
}
#wfm-shutdown-msg {
  font-family: var(--mono);
  font-size: 1.02rem;
  color: #ffb0b8;
  line-height: 1.6;
}
#wfm-shutdown-sub {
  font-family: var(--mono);
  font-size: .74rem;
  color: #c98a92;
  letter-spacing: .03em;
}
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
/* ── Login overlay (v8.0.9) ── */
#login-screen {
  position: fixed; inset: 0; z-index: 9999;
  display: flex; align-items: center; justify-content: center;
  background: rgba(4,7,13,.86);
  backdrop-filter: blur(2px);
}
/* #login-screen.hidden must win on specificity — a bare .hidden{display:none}
   rule (0,0,1,0) can never beat the #login-screen ID rule above (0,1,0,0),
   so classList.add('hidden') after login would silently do nothing
   visually otherwise. */
#login-screen.hidden { display: none; }
#login-card {
  width: 90%; max-width: 320px;
  background: var(--surface); border: 1px solid var(--border2);
  border-radius: 10px; padding: 1.4rem 1.3rem;
  box-shadow: 0 12px 40px rgba(0,0,0,.5);
  font-family: var(--sans);
}
#login-card h2 {
  margin: 0 0 .2rem; font-size: 1.05rem; color: var(--amber);
  letter-spacing: .02em;
}
#login-card p.sub {
  margin: 0 0 1rem; font-size: .8rem; color: var(--muted);
}
#login-card label {
  display: block; font-size: .78rem; color: var(--muted); margin-bottom: .3rem;
}
#login-pw {
  width: 100%; box-sizing: border-box; padding: .55rem .6rem;
  background: var(--bg); border: 1px solid var(--border2); border-radius: 6px;
  color: #fff; font-size: .92rem; font-family: var(--sans);
}
#login-pw:focus { outline: none; border-color: var(--amber); }
#login-btn {
  width: 100%; margin-top: .8rem; padding: .6rem; border: none; border-radius: 6px;
  background: var(--amber); color: #1a1300; font-weight: 600; font-size: .88rem;
  cursor: pointer;
}
#login-btn:disabled { opacity: .5; cursor: default; }
#login-btn:hover:not(:disabled) { filter: brightness(1.08); }
#login-err {
  min-height: 1.1rem; margin-top: .6rem; font-size: .78rem; color: var(--red);
}
</style>
</head>
<body>
<div id="login-screen" class="hidden">
  <form id="login-card" onsubmit="_doLogin(event)">
    <h2>ASL-DVS Node Control</h2>
    <p class="sub">Sign in with this node's root password.</p>
    <label for="login-pw">Root password</label>
    <input id="login-pw" type="password" autocomplete="current-password" required>
    <button id="login-btn" type="submit">Log In</button>
    <div id="login-err"></div>
  </form>
</div>
<div id="offline-bar">SERVER UNREACHABLE — retrying…</div>
<div id="perm-link-bar">⚠ PERMANENT LINK ACTIVE · Node <span id="perm-link-node">—</span> · Bridging risk<button class="perm-disc-btn" style="margin-left:.9rem" onclick="doBannerDiscPermLink()">Disconnect</button></div>
<header>
  <div class="hdr-left">
    <div class="logo">ASL-DVS Node Control</div>
    <div class="logo-sub"><span id="hdr-callsign" style="color:var(--amber);display:none"></span><span id="hdr-callsign-sep" class="hidden"> · </span><span style="color:var(--amber)">Node</span> <span id="hdr-node" style="color:var(--amber)">…</span></div>
  </div>
  <div class="hdr-right">
    <span id="hdr-uptime">UP 0:00:00</span>
    <button onclick="doLogout()" title="Log out" style="background:transparent;border:1px solid var(--border2);color:var(--muted);border-radius:5px;padding:.2rem .5rem;font-size:.72rem;font-family:var(--sans);cursor:pointer">Log Out</button>
    <div class="hdr-ver" style="font-size:.72rem;color:var(--muted);font-family:var(--mono)">v__VERSION__</div>
  </div>
</header>
<div class="wrap">
  <div>
    <div class="sec-lbl-row">
      <div class="ql-group ql-left">
        <a class="ql" data-ql-path="/allmon3" href="#" target="_blank" rel="noopener">Allmon3</a>
        <a class="ql" data-ql-path="/dvswitch" href="#" target="_blank" rel="noopener">DVSwitch</a>
        <a class="ql" data-ql-port="9090" href="#" target="_blank" rel="noopener">Cockpit</a>
      </div>
      <span id="tg-indicator" class="ind-idle"><span class="dot dot-off" id="tg-dot-l"></span><span id="tg-value">——</span><span class="dot dot-off" id="tg-dot-r"></span></span>
      <div class="ql-group ql-right">
        <a class="ql" data-ql-path="/m17" href="#" target="_blank" rel="noopener">USRP2M17</a>
        <a class="ql" data-ql-port="8991" href="#" target="_blank" rel="noopener">WiFiMon</a>
        <a id="lnk-sysmon" class="ql ql-off" href="#" aria-disabled="true" title="SysMon is not running">SysMon</a>
      </div>
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
        <div class="tab" id="tab-phone" onclick="clickTab('PHONE')">Phone</div>
        <div class="tab" id="tab-edit"  onclick="clickEdit()">EDIT</div>
      </div>
      <div class="tab-panel">
        <div id="pg-ASL" class="hidden">
          <div class="quick-bar">
            <input id="cbn-input" class="quick-inp" type="text" inputmode="numeric"
              pattern="[0-9]*" placeholder="Node number…" maxlength="12"
              oninput="ndcQtSync('ASL')"
              onkeydown="if(event.key==='Enter')doConnectByNumber()">
            <button class="btn btn-teal" onclick="doConnectByNumber()">Tune</button>
            <button id="lh-btn-ASL" class="btn-last lh-off" onclick="openModeLast('ASL')">LH</button>
            <button id="asl-qt-save-btn" class="btn btn-muted" onclick="ndcQtSave('ASL')" disabled
              aria-label="Save this node to favorites" title="Save to favorites">Save</button>
          </div>
          <div id="asl-card" class="tgc-card tgc-asl">
            <input id="asl-filter" class="tgc-input" type="search" maxlength="40"
              placeholder="Search: node, callsign or place" aria-label="Search AllStar nodes"
              autocomplete="off" spellcheck="false" oninput="ndcSearchSoon('ASL')" disabled>
            <select id="asl-ref-select" class="tgc-select" aria-label="AllStar node"
              onchange="ndcButtons('ASL')" disabled>
              <option value="">Type to search…</option>
            </select>
            <button id="asl-connect-btn" class="btn btn-teal" onclick="ndcConnect('ASL')" disabled>Connect</button>
            <button id="lh-btn-ASLNODE" class="btn-last lh-off" onclick="ndcLast('ASL')"
              aria-label="Open this node's page on the AllStar stats site" aria-disabled="true">LH</button>
            <button id="asl-save-btn" class="btn btn-muted" onclick="ndcSave('ASL')" disabled
              aria-label="Save this node to favorites" title="Save to favorites">Save</button>
            <div id="asl-card-msg" class="tgc-card-msg" role="status" hidden></div>
          </div>
          <div class="net-sel-hdr asl-fav-hdr">Favorites</div>
          <div id="asl-grid"></div>
          <div class="act-bar">
            <button class="btn btn-red" onclick="doAslDiscCurrent()">Disconnect</button>
          </div>
        </div>
        <!-- ECHO -->
        <div id="pg-ECHO" class="hidden">
          <div class="quick-bar">
            <input id="echo-input" class="quick-inp" type="text" inputmode="numeric"
              pattern="[0-9]*" placeholder="EchoLink node (e.g. 9999)…" maxlength="7"
              oninput="ndcQtSync('ECHO')"
              onkeydown="if(event.key==='Enter')doEchoConnectByNumber()">
            <button class="btn btn-amber" onclick="doEchoConnectByNumber()">Tune</button>
            <button id="lh-btn-ECHO" class="btn-last lh-off" onclick="openModeLast('ECHO')">LH</button>
            <button id="echo-qt-save-btn" class="btn btn-muted" onclick="ndcQtSave('ECHO')" disabled
              aria-label="Save this node to favorites" title="Save to favorites">Save</button>
          </div>
          <div id="echo-card" class="tgc-card tgc-echo">
            <input id="echo-filter" class="tgc-input" type="search" maxlength="40"
              placeholder="Search: node or callsign" aria-label="Search EchoLink stations"
              autocomplete="off" spellcheck="false" oninput="ndcSearchSoon('ECHO')" disabled>
            <select id="echo-ref-select" class="tgc-select" aria-label="EchoLink station"
              onchange="ndcButtons('ECHO')" disabled>
              <option value="">Type to search…</option>
            </select>
            <button id="echo-connect-btn" class="btn btn-amber" onclick="ndcConnect('ECHO')" disabled>Connect</button>
            <button id="lh-btn-ECHONODE" class="btn-last lh-off" onclick="ndcLast('ECHO')"
              aria-label="Open the EchoLink logins page" aria-disabled="true">LH</button>
            <button id="echo-save-btn" class="btn btn-muted" onclick="ndcSave('ECHO')" disabled
              aria-label="Save this station to favorites" title="Save to favorites">Save</button>
            <div id="echo-card-msg" class="tgc-card-msg" role="status" hidden></div>
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
              oninput="dmrSaveSync()"
              onkeydown="if(event.key==='Enter')doQuickTune('DMR')">
            <button class="btn btn-blue" onclick="doQuickTune('DMR')">Tune</button>
            <button id="lh-btn-DMR" class="btn-last lh-off" onclick="openDmrLast()">LH</button>
            <button id="dmr-save-btn" class="btn btn-muted" onclick="dmrQuickSave()" disabled
              aria-label="Save this talkgroup to favorites" title="Save to favorites">Save</button>
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
          <div id="stfu-card" class="tgc-card tgc-stfu">
            <input id="stfu-filter" class="tgc-input" type="search" maxlength="40"
              placeholder="Search: number or name" aria-label="Search STFU talkgroups"
              autocomplete="off" spellcheck="false" oninput="lcFilterSoon('STFU')" disabled>
            <select id="stfu-ref-select" class="tgc-select" aria-label="STFU talkgroup"
              onchange="lcButtons('STFU')" disabled>
              <option value="">Select talkgroup…</option>
            </select>
            <button id="stfu-connect-btn" class="btn btn-green" onclick="lcConnect('STFU')" disabled>Connect</button>
            <button id="stfu-save-btn" class="btn btn-muted" onclick="lcSave('STFU')" disabled
              aria-label="Save this talkgroup to favorites" title="Save to favorites">Save</button>
            <div id="stfu-card-msg" class="tgc-card-msg" role="status" hidden></div>
          </div>
          <div class="net-sel-hdr stfu-fav-hdr">Favorites</div>
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
          <div id="ysf-card" class="ysf-card">
            <select id="ysf-cc-select" class="ysf-select" aria-label="Filter by country"
              onchange="lcFill('YSF',true)" disabled>
              <option value="*">All countries</option>
            </select>
            <input id="ysf-filter" class="ysf-input" type="search" maxlength="40"
              placeholder="Filter: name or number" aria-label="Filter reflectors by text"
              autocomplete="off" spellcheck="false" oninput="lcFilterSoon('YSF')" disabled>
            <select id="ysf-ref-select" class="ysf-select" aria-label="YSF reflector"
              onchange="lcButtons('YSF')" disabled>
              <option value="">Select reflector…</option>
            </select>
            <button id="ysf-connect-btn" class="btn btn-purple" onclick="lcConnect('YSF')" disabled>Connect</button>
            <button id="lh-btn-YSFREF" class="btn-last lh-off" onclick="lcOpenLast('YSF')"
              aria-label="Open Last Heard for this reflector" aria-disabled="true">LH</button>
            <button id="ysf-save-btn" class="btn btn-muted" onclick="lcSave('YSF')" disabled
              aria-label="Save this reflector to favorites" title="Save to favorites">Save</button>
            <div id="ysf-card-msg" class="ysf-card-msg" role="status" hidden></div>
          </div>
          <div class="net-sel-hdr ysf-fav-hdr">Favorites</div>
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
            <button id="lh-btn-FCSNET" class="btn-last lh-off" onclick="openModeLast('FCS')"
              title="FCS network Last Heard" aria-label="Open FCS network Last Heard">LH</button>
          </div>
          <div id="fcs-card" class="fcs-card">
            <select id="fcs-srv-select" class="fcs-select" aria-label="FCS server"
              onchange="fcsFillRooms(false)" disabled>
              <option value="">Select server…</option>
            </select>
            <select id="fcs-room-select" class="fcs-select" aria-label="FCS room"
              onchange="fcsCardButtons()" disabled>
              <option value="">Select room…</option>
            </select>
            <button id="fcs-connect-btn" class="btn btn-conn-fcs" onclick="fcsConnect()" disabled>Connect</button>
            <button id="lh-btn-FCS" class="btn-last lh-off" onclick="openFcsLast()"
              aria-label="Open Last Heard for this server" aria-disabled="true">LH</button>
            <button id="fcs-save-btn" class="btn btn-muted" onclick="fcsSave()" disabled
              aria-label="Save this room to favorites" title="Save to favorites">Save</button>
            <div id="fcs-card-msg" class="fcs-card-msg" role="status" hidden></div>
          </div>
          <div class="net-sel-hdr fcs-fav-hdr">Favorites</div>
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
          <div id="p25-card" class="tgc-card tgc-p25">
            <input id="p25-filter" class="tgc-input" type="search" maxlength="40"
              placeholder="Search: number or address" aria-label="Search P25 talkgroups"
              autocomplete="off" spellcheck="false" oninput="lcFilterSoon('P25')" disabled>
            <select id="p25-ref-select" class="tgc-select" aria-label="P25 talkgroup"
              onchange="lcButtons('P25')" disabled>
              <option value="">Select talkgroup…</option>
            </select>
            <button id="p25-connect-btn" class="btn btn-orange" onclick="lcConnect('P25')" disabled>Connect</button>
            <button id="lh-btn-P25REF" class="btn-last lh-off" onclick="lcOpenLast('P25')"
              aria-label="Open Last Heard for this talkgroup" aria-disabled="true">LH</button>
            <button id="p25-save-btn" class="btn btn-muted" onclick="lcSave('P25')" disabled
              aria-label="Save this talkgroup to favorites" title="Save to favorites">Save</button>
            <div id="p25-card-msg" class="tgc-card-msg" role="status" hidden></div>
          </div>
          <div class="net-sel-hdr p25-fav-hdr">Favorites</div>
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
          <div id="nxdn-card" class="tgc-card tgc-nxdn">
            <input id="nxdn-filter" class="tgc-input" type="search" maxlength="40"
              placeholder="Search: number or address" aria-label="Search NXDN talkgroups"
              autocomplete="off" spellcheck="false" oninput="lcFilterSoon('NXDN')" disabled>
            <select id="nxdn-ref-select" class="tgc-select" aria-label="NXDN talkgroup"
              onchange="lcButtons('NXDN')" disabled>
              <option value="">Select talkgroup…</option>
            </select>
            <button id="nxdn-connect-btn" class="btn btn-lime" onclick="lcConnect('NXDN')" disabled>Connect</button>
            <button id="lh-btn-NXDNREF" class="btn-last lh-off" onclick="lcOpenLast('NXDN')"
              aria-label="Open Last Heard for this talkgroup" aria-disabled="true">LH</button>
            <button id="nxdn-save-btn" class="btn btn-muted" onclick="lcSave('NXDN')" disabled
              aria-label="Save this talkgroup to favorites" title="Save to favorites">Save</button>
            <div id="nxdn-card-msg" class="tgc-card-msg" role="status" hidden></div>
          </div>
          <div class="net-sel-hdr nxdn-fav-hdr">Favorites</div>
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
          <div id="dstar-card" class="rfc-card rfc-dstar">
            <input id="dstar-filter" class="rfc-input" type="search" maxlength="40"
              placeholder="Search: REF, XRF, DCS or number" aria-label="Search D-STAR reflectors"
              autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false"
              oninput="lcFilterSoon('DSTAR')" disabled>
            <select id="dstar-ref-select" class="rfc-select" aria-label="D-STAR reflector"
              onchange="lcButtons('DSTAR')" disabled>
              <option value="">Select reflector…</option>
            </select>
            <select id="dstar-mod-select" class="rfc-select rfc-mod" aria-label="D-STAR module"
              title="Module" onchange="lcButtons('DSTAR')"></select>
            <div class="rfc-btns">
              <button id="dstar-connect-btn" class="btn btn-conn-pink" onclick="lcConnect('DSTAR')" disabled>Connect</button>
              <button id="lh-btn-DSTARREF" class="btn-last lh-off" onclick="lcOpenLast('DSTAR')"
                aria-label="Open Last Heard for this reflector" aria-disabled="true">LH</button>
              <button id="dstar-save-btn" class="btn btn-muted" onclick="lcSave('DSTAR')" disabled
                aria-label="Save this reflector to favorites" title="Save to favorites">Save</button>
            </div>
            <div id="dstar-card-msg" class="rfc-card-msg" role="status" hidden></div>
          </div>
          <div class="net-sel-hdr dstar-fav-hdr">Favorites</div>
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
          <div id="xlx-card" class="rfc-card rfc-xlx">
            <input id="xlx-filter" class="rfc-input" type="search" maxlength="40"
              placeholder="Search: 307, DAM or address" aria-label="Search XLX reflectors"
              autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false"
              oninput="lcFilterSoon('XLX')" disabled>
            <select id="xlx-ref-select" class="rfc-select" aria-label="XLX reflector"
              onchange="lcButtons('XLX')" disabled>
              <option value="">Select reflector…</option>
            </select>
            <select id="xlx-mod-select" class="rfc-select rfc-mod" aria-label="XLX module"
              title="Module" onchange="lcButtons('XLX')"></select>
            <div class="rfc-btns">
              <button id="xlx-connect-btn" class="btn btn-conn" onclick="lcConnect('XLX')" disabled>Connect</button>
              <button id="lh-btn-XLXREF" class="btn-last lh-off" onclick="lcOpenLast('XLX')"
                aria-label="Open Last Heard for this reflector" aria-disabled="true">LH</button>
              <button id="xlx-save-btn" class="btn btn-muted" onclick="lcSave('XLX')" disabled
                aria-label="Save this reflector to favorites" title="Save to favorites">Save</button>
            </div>
            <div id="xlx-card-msg" class="rfc-card-msg" role="status" hidden></div>
          </div>
          <div class="net-sel-hdr xlx-fav-hdr">Favorites</div>
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
          <div id="m17-card" class="m17-card">
            <select id="m17-ref-select" class="m17-select" aria-label="M17 reflector"
              onchange="m17FillModules(false)" disabled>
              <option value="">Loading…</option>
            </select>
            <select id="m17-mod-select" class="m17-select" aria-label="M17 module"
              onchange="m17CardButtons()" disabled>
              <option value="">Select module…</option>
            </select>
            <button id="m17-connect-btn" class="btn btn-conn" onclick="m17CardConnect()" disabled>Connect</button>
            <button id="lh-btn-M17" class="btn-last lh-off" onclick="openM17Last()"
              title="Last Heard" aria-label="Last Heard" aria-disabled="true">LH</button>
            <button id="m17-save-btn" class="btn btn-muted" onclick="m17CardSave()" disabled
              aria-label="Save this reflector to favorites" title="Save to favorites">Save</button>
            <div id="m17-card-msg" class="m17-card-msg" role="status" hidden></div>
          </div>
          <div class="net-sel-hdr m17-fav-hdr">Favorites</div>
          <div id="m17-grid"></div>
          <div class="act-bar">
            <button class="btn btn-red" onclick="doM17Disconnect()">Disconnect</button>
            <button class="btn btn-muted" onclick="doDiscAll()">Disconnect All</button>
          </div>
        </div>
        <div id="pg-PHONE" class="hidden">
          <div class="quick-bar">
            <select id="pt-net-select" class="dmr-srv-select" onchange="ptSwitchNet(this.value)" title="Phone network"></select>
            <div id="pt-reg-dot" class="dot dot-off pt-hide" title=""></div>
            <span id="pt-signin" class="pt-signin pt-hide"></span>
            <span id="pt-tot" class="pt-signin pt-hide"></span>
            <input id="pt-dial" class="quick-inp" type="tel" inputmode="tel" placeholder="Number to dial…" maxlength="24"
              autocomplete="off" oninput="ptDialSync()" onkeydown="if(event.key==='Enter')ptDial()">
            <button id="pt-dial-btn" class="btn btn-green" onclick="ptDial()">Dial</button>
            <button id="pt-save-btn" class="btn btn-muted" onclick="ptQuickSave()" disabled
              aria-label="Save this number to favorites" title="Save to favorites">Save</button>
            <button id="pt-t99" class="btn btn-amber pt-tone" onclick="ptSendTones('*99')" disabled
              aria-label="Send star 9 9 (talk)" title="Send *99 — talk">*99</button>
            <button id="pt-thash" class="btn btn-amber pt-tone" onclick="ptSendTones('#')" disabled
              aria-label="Send pound (unkey)" title="Send # — unkey">#</button>
          </div>
          <div class="pt-callrow"><div id="pt-call" class="pt-call" role="status"></div><div id="pt-cbtns"></div></div>
          <div class="pt-callrow pt-hide" id="pt-hl"><div id="pt-hl-txt" class="pt-call pt-live" role="status"></div></div>
          <div id="pt-grid"></div>
          <div class="act-bar">
            <button class="btn btn-red" onclick="ptHangup()">Hang Up</button>
            <button id="pt-kp-btn" class="btn btn-amber" onclick="ptKeypadOpen()" disabled>Keypad</button>
            <button id="pt-patch-btn" class="btn btn-muted" onclick="ptPatchToggle()">Patch: On</button>
            <button id="pt-rep-btn" class="btn btn-muted" onclick="ptReportOpen()" title="Gather a text report to copy and paste">Report</button>
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
                <label class="cfg-lbl" for="cfg-phone-nodes">Phone nodes</label>
                <select id="cfg-phone-nodes" class="cfg-inp" title="Each phone network's own node (information only — picking one changes nothing)"><option value="">—</option></select>
                <input id="cfg-bridge-node-2" type="hidden">
              </div>
              <div class="cfg-field">
                <label class="cfg-lbl cfg-lbl-reserved" for="cfg-bridge-node-3">Reserved</label>
                <input id="cfg-bridge-node-3" class="cfg-inp" type="text" inputmode="numeric" placeholder="—" maxlength="10" disabled title="Reserved for future use">
              </div>
              <div class="cfg-field">
                <label class="cfg-lbl" for="cfg-port">Web UI Port</label>
                <input id="cfg-port" class="cfg-inp" type="text" inputmode="numeric" placeholder="e.g. 8989" maxlength="5">
              </div>
              <div class="cfg-field">
                <label class="tab-chk-lbl"><input type="checkbox" id="cfg-cpuweight">CPUWeight</label>
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
              <label class="tab-chk-lbl"><input type="checkbox" id="chk-PHONE" value="PHONE">Phone</label>
            </div>
          </div>
          <div class="cfg-section" id="ph-section">
            <div class="ed-sec-hdr no-top" style="padding-left:0">
              <span>Phone</span>
              <span class="ph-hdr-r">
                <label class="tab-chk-lbl ph-act-lbl" title="Set up the phone system in Asterisk (asks first)"><input type="checkbox" id="ph-active" onclick="return phActClick(event)">Activate</label>
                <button onclick="toggleEdSection('eds-phone')">Hide</button>
              </span>
            </div>
            <div id="eds-phone">
              <div class="cfg-grid">
                <div class="cfg-field"><label class="tab-chk-lbl"><input type="checkbox" id="ph-patch">Phone patch on</label></div>
                <div class="cfg-field">
                  <label class="cfg-lbl" for="ph-dialtime">Dial timeout (ms)</label>
                  <input id="ph-dialtime" class="cfg-inp" type="text" inputmode="numeric" maxlength="5" placeholder="20000">
                </div>
                <div class="cfg-field"><label class="tab-chk-lbl"><input type="checkbox" id="ph-restart">Restart Asterisk if needed</label></div>
                <div class="cfg-field"><label class="tab-chk-lbl"><input type="checkbox" id="ph-totoff">Transmitter time-out off while the Phone tab is open</label></div>
                <div class="cfg-field"><label class="cfg-lbl" for="ph-totcap">Safety cap (minutes keyed)</label>
                  <input id="ph-totcap" class="cfg-inp" type="text" inputmode="numeric" maxlength="2" placeholder="15"></div>
                <div class="cfg-field"><label class="cfg-lbl" for="ph-signin">Sign in</label>
                  <select id="ph-signin" class="cfg-inp"><option value="picked">Picked network only</option><option value="all">All networks</option></select></div>
              </div>
              <div class="ph-hint">Sign in: with "Picked network only", just the network picked on the Phone tab signs in, so two accounts for the same number never compete. Picking another network moves the sign-in (not during a call). A network whose own "Sign in" box is off never signs in.</div>
              <div class="cfg-grid">
                <div class="cfg-field"><label class="tab-chk-lbl"><input type="checkbox" id="ph-sx" onchange="phSxToggle()">Simplex radio (use VOX for calls)</label></div>
              </div>
              <div class="cfg-grid" id="ph-sx-grid" style="display:none">
                <div class="cfg-field"><label class="cfg-lbl" for="ph-sx-vt">VOX timeout (ms)</label>
                  <input id="ph-sx-vt" class="cfg-inp" type="text" inputmode="numeric" maxlength="5" placeholder="10000"></div>
                <div class="cfg-field"><label class="cfg-lbl" for="ph-sx-vr">VOX recovery (ms)</label>
                  <input id="ph-sx-vr" class="cfg-inp" type="text" inputmode="numeric" maxlength="5" placeholder="2000"></div>
                <div class="cfg-field"><label class="cfg-lbl" for="ph-sx-pd">Radio delay (x20 ms)</label>
                  <input id="ph-sx-pd" class="cfg-inp" type="text" inputmode="numeric" maxlength="3" placeholder="25"></div>
                <div class="cfg-field"><label class="cfg-lbl" for="ph-sx-fd">Phone delay (x20 ms)</label>
                  <input id="ph-sx-fd" class="cfg-inp" type="text" inputmode="numeric" maxlength="3" placeholder="25"></div>
              </div>
              <div class="cfg-grid">
                <div class="cfg-field"><label class="cfg-lbl" for="ph-hang">Hang time (ms)</label>
                  <input id="ph-hang" class="cfg-inp" type="text" inputmode="numeric" maxlength="5" placeholder="default"></div>
              </div>
              <div class="ph-hint">Hang time: how long the radio stays keyed after the caller stops talking. Blank uses the node default; 100–500 cuts the dead-air tail.</div>
              <div class="ph-hint" id="ph-sx-hint" style="display:none">Callers should mute their phone and un-mute only to talk. Long unbroken audio is cut every VOX timeout for the recovery time so you can break in.</div>
              <div class="ed-sec-hdr" style="padding-left:0"><span>Networks</span></div>
              <div id="ph-nets"></div>
              <div class="ed-toolbar" style="justify-content:flex-start">
                <button class="btn btn-muted" id="ph-add-btn" onclick="phAddNet()">Add network</button>
              </div>
              <div class="ed-sec-hdr" style="padding-left:0"><span>Hams Over IP AllStar Link</span></div>
              <div class="ph-hint">HOIP calls in to your node over IAX2, and callers use *99 to talk and # to stop.
                You need an internet name that points at your home (not an IP address) and <span id="ph-hl-porthint">UDP port 4569 forwarded to this Pi</span>.
                Save Phone, copy the dial string, and put it in your "Request a Line" ticket on the HOIP helpdesk.</div>
              <div class="cfg-grid">
                <div class="cfg-field"><label class="tab-chk-lbl"><input type="checkbox" id="ph-hl-on">Turn on</label></div>
                <div class="cfg-field"><label class="cfg-lbl" for="ph-hl-user">Username</label>
                  <input id="ph-hl-user" class="cfg-inp" type="text" maxlength="32" autocomplete="off" placeholder="kd8pgk-hoip"></div>
                <div class="cfg-field"><label class="cfg-lbl" for="ph-hl-pass">Password</label>
                  <input id="ph-hl-pass" class="cfg-inp" type="password" maxlength="64" autocomplete="new-password" placeholder="8+ characters"></div>
                <div class="cfg-field"><label class="cfg-lbl" for="ph-hl-fqdn">Internet name</label>
                  <input id="ph-hl-fqdn" class="cfg-inp" type="text" maxlength="120" autocomplete="off" placeholder="kd8pgk.ddns.net"></div>
                <div class="cfg-field"><label class="cfg-lbl" for="ph-hl-port">Port</label>
                  <input id="ph-hl-port" class="cfg-inp" type="text" inputmode="numeric" maxlength="5" placeholder="4569" oninput="phHlHints()"></div>
                <div class="cfg-field"><label class="cfg-lbl" for="ph-hl-node">Callers land on</label>
                  <select id="ph-hl-node" class="cfg-inp" onchange="phHlHints()"></select></div>
                <div class="ph-hint" id="ph-hl-warn" style="display:none;color:var(--warn,#ffb020)">Warning: on the radio node, HOIP callers can use every command it knows (linking and unlinking nodes too), and they are heard on whatever it is linked to, including the DMR and M17 bridges. The Phone Bridge is the safe choice.</div>
              </div>
              <div class="ph-hint" id="ph-hl-note"></div>
              <div class="ed-toolbar" style="justify-content:flex-start">
                <button class="btn btn-muted" onclick="phHlCopy()">Copy dial string</button>
              </div>
              <input id="ph-hl-str" class="cfg-inp" type="text" readonly style="display:none" aria-label="HOIP dial string">
              <div class="ed-toolbar" style="justify-content:flex-start;margin-top:.4rem">
                <button class="btn btn-teal" onclick="phSave()">Save Phone</button>
                <button class="btn btn-muted" onclick="phLoad()">Reload</button>
                <button class="btn btn-red" onclick="phRevertOpen()" title="Take the phone system back out of Asterisk (asks first)">Revert (turn phone off)</button>
              </div>
              <div class="ph-msg" id="ph-msg"></div>
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
<div id="ph-dlg-overlay" role="dialog" aria-modal="true" aria-labelledby="ph-dlg-title"><div id="ph-dlg-box">
  <div id="ph-dlg-hdr"><span id="ph-dlg-title"></span>
    <button class="btn btn-muted" onclick="phDlgClose()" aria-label="Close" title="Close">✕</button></div>
  <div id="ph-dlg-body"></div>
  <label class="tab-chk-lbl" style="margin-top:.4rem"><input type="checkbox" id="ph-dlg-restart">Restart Asterisk if needed</label>
  <div id="ph-dlg-btns"><button class="btn btn-muted" onclick="phDlgClose()">Cancel</button><button id="ph-dlg-ok" class="btn btn-teal"></button></div>
</div></div>
<div id="pt-kp-overlay" role="dialog" aria-modal="true" aria-labelledby="pt-kp-title"><div id="pt-kp-box">
  <div id="pt-kp-hdr"><span id="pt-kp-title">Keypad</span>
    <button id="pt-kp-x" class="btn btn-muted" onclick="ptKeypadClose()" aria-label="Close keypad" title="Close">✕</button></div>
  <div id="pt-kp-sent" aria-live="polite"></div>
  <div id="pt-kp-grid">
    <button class="btn btn-muted" data-key="1">1</button><button class="btn btn-muted" data-key="2">2</button><button class="btn btn-muted" data-key="3">3</button>
    <button class="btn btn-muted" data-key="4">4</button><button class="btn btn-muted" data-key="5">5</button><button class="btn btn-muted" data-key="6">6</button>
    <button class="btn btn-muted" data-key="7">7</button><button class="btn btn-muted" data-key="8">8</button><button class="btn btn-muted" data-key="9">9</button>
    <button class="btn btn-amber" data-key="*">*</button><button class="btn btn-muted" data-key="0">0</button><button class="btn btn-amber" data-key="#">#</button>
  </div>
  <div id="pt-kp-audio" aria-live="polite"></div>
  <div id="pt-kp-radio">From the radio during a call: *980 sends *, *981 sends #, *982 sends *99,
    *983–*987 send your tone buttons 1–5</div>
  <div id="pt-kp-path">
    <label for="pt-kp-path-sel">Send tones</label>
    <select id="pt-kp-path-sel" class="cfg-inp" onchange="ptTonePathSet(this.value)"></select>
  </div>
  <div id="pt-kp-mode" class="pt-hide">
    <label for="pt-kp-mode-sel">Tone mode (this call)</label>
    <div id="pt-kp-mode-row"><select id="pt-kp-mode-sel" class="cfg-inp" onchange="ptToneModeSet(this.value)"></select>
      <button id="pt-kp-keep" class="btn btn-teal" onclick="ptToneModeKeep()" title="Save this tone mode to the network">Keep this</button></div>
    <div id="pt-kp-mode-note"></div>
  </div>
</div></div>
<div id="pt-rep-overlay" role="dialog" aria-modal="true" aria-labelledby="pt-rep-title"><div id="pt-rep-box">
  <div id="pt-rep-hdr"><span id="pt-rep-title">Phone report</span>
    <button class="btn btn-muted" onclick="ptReportClose()" aria-label="Close report" title="Close">✕</button></div>
  <textarea id="pt-rep-text" readonly spellcheck="false" aria-label="Phone report text"></textarea>
  <div id="pt-rep-btns"><button id="pt-rep-copy" class="btn btn-teal" onclick="ptReportCopy()">Copy</button>
    <button class="btn btn-muted" onclick="ptReportOpen()">Refresh</button></div>
</div></div>
<div id="modal-overlay"><div id="modal-box"><div id="modal-msg"></div><div id="modal-btns"></div></div></div>
<div id="err-modal-overlay"><div id="err-modal-box">
  <div id="err-modal-hdr">⚠ Tune Failed</div>
  <div id="err-modal-msg"></div>
  <div id="err-modal-btns"><button class="btn btn-red" onclick="byId('err-modal-overlay').classList.remove('open')">Dismiss</button></div>
</div></div>
<div id="working-overlay"><div id="working-box"><div class="spinner"></div><div id="working-msg">Working…</div></div></div>
<div id="ready-bar"><div class="rdy-dot"></div><span id="ready-msg">READY</span></div>
<div id="wfm-shutdown-overlay"><div id="wfm-shutdown-box">
  <div id="wfm-shutdown-hdr">⚠ wifimon — Node Shutting Down</div>
  <div id="wfm-shutdown-msg"></div>
  <div id="wfm-shutdown-sub">This node is powering off. It will need to be manually power-cycled or reconnected to WiFi.</div>
</div></div>
<script>
const byId=id=>document.getElementById(id);
// Initial value only — this literal predates MODE_CAPS in file order (TDZ
// prevents referencing STATIC_PAGES here), and gets fully overwritten by
// applyTabVisibility() on first load anyway. Keep this list in sync with
// MODE_CAPS' keys below if a mode is ever added/removed at the Object.keys
// level; applyTabVisibility() itself no longer needs this list at all.
const PAGES=['ASL','ECHO','DMR','STFU','YSF','FCS','P25','NXDN','DSTAR','XLX','M17'];
let TAB_LABELS={ASL:'ASL',ECHO:'ECHO',DMR:'DMR',STFU:'STFU',YSF:'YSF',FCS:'FCS',P25:'P25',NXDN:'NXDN',DSTAR:'DSTAR',XLX:'XLX'};
const TG_BLANK_NAME='blank';
const TG_BLANK_ADDR='000000';
const TG_DISCONNECT='disconnect';
let curPage='ASL',curTg=null,busy=false,inEdit=false;
// v8.3.9 — general tab-restore record. Written on every real tab change
// (clickTab success, showPage, and the server-follow branch of
// applyServerState) so a page reload — browser tab discard/backgrounding,
// not just the dedicated SysMon round trip — can restore the tab the user
// was actually on instead of falling through to the hardcoded ASL default
// in applyTabState()'s _firstPoll branch. Session-scoped by design: a
// genuine fresh visit (new tab/session) still lands on the default.
function _saveTabState(){try{sessionStorage.setItem('dashLastTab',curPage);}catch(_){}}
// Per-mode last-tuned memory.  Digital tabs clear their entry on disconnect
// (v8.0.12h: the leaving-tab TG_DISCONNECT is issued server-side by
// _leave_page()/_enter_page(), not by clickTab) so _curTgPerMode[mode] is
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
// FCS browse card state (v8.4.2) — see the fcsCard* block near openLast().
let _fcs={loaded:false,loading:false,saving:false,at:0,tried:0,byId:{},sig:'',tuned:'',applied:null};
// M17 browse card state (v8.6.2) — see the m17Card* block after openFcsLast().
let _m17c={loaded:false,loading:false,saving:false,at:0,tried:0,byId:{},sig:'',tuned:'',applied:null};
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
  const cd=byId(mode.toLowerCase()+'-card');   // v8.4.2: FCS browse card only
  if(cd)cd.classList.add('grid-busy');
}
function undimGrid(mode){
  const el=byId(mode.toLowerCase()+'-grid');
  if(el)el.classList.remove('grid-busy');
  const cd=byId(mode.toLowerCase()+'-card');
  if(cd)cd.classList.remove('grid-busy');
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
// wifimon flagged an imminent shutdown (low voltage or lost network) — show
// a persistent, non-dismissible popup. Intentionally has no close/cancel
// button: there's nothing to cancel, the node is on its way down. Once
// shown it stays up; if the poll later reports active:false (e.g. a
// leftover flag from before a reboot) it's cleared.
let _wfmShutdownShown=false;
function showWfmShutdown(state){
  if(_wfmShutdownShown)return;
  _wfmShutdownShown=true;
  const trig=state.trigger==='low_voltage'?'Low voltage':
              state.trigger==='no_conn'?'Lost network connection':'wifimon';
  byId('wfm-shutdown-msg').textContent=trig+' — '+(state.reason||'shutting down now.');
  byId('wfm-shutdown-overlay').classList.add('open');
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
// v8.3.8 — client request ceilings for actions that trigger a DVS mode/tune
// server-side. The server caps a mode at 40s and a tune at 40s (v8.3.8); the
// browser must not abort first or the user sees "Request timed out" instead of
// the real result. These are ceilings, not waits — a fast tune returns at once.
//   DVS_TUNE_MS       one mode-or-tune per request (DMR network switch, quick-tune)
//   DVS_MODE_TUNE_MS  a mode switch AND a tune in one request (cross-mode tune,
//                     D-STAR/XLX/M17 connect) — up to 40+40s server-side
const DVS_TUNE_MS      = 55000;
const DVS_MODE_TUNE_MS = 95000;
const LINK_SWITCH_MS   = 130000;
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
  PHONE: {requires:['hasAsl'],            isDigital:false, reflectorGrid:false, tgRefresh:false},
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
  if(curPage==='FCS')fcsCardEnter();   // v8.4.2: lazy-load the FCS room list
  if(LC_CFG[curPage])lcCardEnter(curPage);   // v9.0.2 browse-card engine: P25 / NXDN / STFU / XLX / D-STAR / YSF
  if(curPage==='ASL')ndcCardEnter('ASL');   // v8.9.7: check the AllStar node list
  if(curPage==='ECHO')ndcCardEnter('ECHO');   // v9.3.60: check the EchoLink station list
  if(curPage==='M17')m17CardEnter();   // v8.6.2: lazy-load the M17 reflector list
  if(curPage==='PHONE')ptEnter();   // v9.1.0: show the phone network list
}
async function reTuneTab(page){
  busy=true;showWorking('Re-tuning '+page+'…');
  const srv=byId('dmr-srv-select');
  const server=srv?srv.value:'';
  try{
    const d=await api({action:'retune-tab',page,server},LINK_SWITCH_MS);
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
/* ── Tab lock (v8.9.0) ───────────────────────────────────────────────────────
   While a menu (<select>) or a search box on a tab page has focus, the tab
   buttons go grey and ignore taps, so a stray tap near the top of a phone
   screen can't switch tabs.  Picking from a menu, leaving the box, or 20 s
   with no activity (a safety net for phones that never report the menu
   closing) all bring the tabs back.  The Edit page is not covered. */
const TAB_LOCK_MS=20000;
const _tabLock={on:false,timer:0};
function tabLockTarget(el){
  if(!el||!el.closest)return false;
  const pg=el.closest('[id^="pg-"]');
  if(!pg||pg.id==='pg-EDIT')return false;
  return el.tagName==='SELECT'||(el.tagName==='INPUT'&&el.type==='search');
}
function tabLockSet(on){
  clearTimeout(_tabLock.timer);
  _tabLock.on=on;
  const t=document.querySelector('#tabs-strip .tabs');
  if(t){t.classList.toggle('tabs-locked',on);t.setAttribute('aria-disabled',on?'true':'false');}
  if(on)_tabLock.timer=setTimeout(()=>tabLockSet(false),TAB_LOCK_MS);
}
document.addEventListener('focusin',e=>{if(tabLockTarget(e.target))tabLockSet(true);});
document.addEventListener('focusout',e=>{
  if(!tabLockTarget(e.target))return;
  // Focus may be moving straight to another menu or box; check after it lands.
  setTimeout(()=>{if(!tabLockTarget(document.activeElement))tabLockSet(false);},0);
});
document.addEventListener('change',e=>{
  // A pick closes the menu.  Drop focus too, so a phone that leaves the menu
  // focused doesn't keep the tabs grey.
  if(e.target&&e.target.tagName==='SELECT'&&tabLockTarget(e.target)){e.target.blur();tabLockSet(false);}
});
document.addEventListener('input',e=>{if(tabLockTarget(e.target)&&e.target.tagName==='INPUT')tabLockSet(true);});

async function clickTab(page){
  if(busy||_tabLock.on)return;
  if(!inEdit&&page===curPage){
    if(page==='PHONE'){_pt.netSelect=true;ptRender();return;}   // v9.1.0: re-click = back to the network list, no server work
    reTuneTab(page);return;
  }
  inEdit=false;busy=true;
  showWorking(`Switching to ${page}…`);
  const prevPage=curPage;
  if(prevPage&&PAGES.includes(prevPage)&&prevPage!=='ASL'&&prevPage!=='ECHO'){
    // v8.0.12h: the leaving-tab teardown (DSTAR_UNLINK for DSTAR/XLX, the M17
    // placeholder-ini + service restart, the TG disconnect) is now done
    // server-side by _leave_page(), invoked from _enter_page() inside the same
    // _connecting guard as the enter. The client no longer fires a separate
    // pre-teardown request: that cost a second round trip, sent TG_DISCONNECT
    // twice per switch, and left an unguarded window between the two requests
    // in which the bridge watchdog could act on the outgoing page. Only the
    // local UI state resets remain here.
    curTg=null;_pendingTune=null;
    _curTgPerMode[prevPage]=null;  // no memory — returning to this tab starts clean
    setIndicator(null,prevPage,false);
  }
  try{
    const d=await api({action:'switch-tab',page},LINK_SWITCH_MS);
    if(d.ok){
      curPage=page;
      _saveTabState();
      // Arriving at DMR via tab-switch: always show network selector, never the
      // TG list.  Set the flag AND render immediately from cached server data so
      // the user sees the selector the instant the tab becomes visible rather
      // than seeing the old TG list for up to 1s until the next refresh fires.
      if(page==='DMR'){
        _dmrNetSelectMode=true;   // D3 writer 2/4 — see declaration comment
        renderDmrNetSelect(_lastDmrServers,_lastActiveDmrServer);
      }
      if(page==='PHONE'){_pt.netSelect=true;_pt.loadedAt=0;}   // v9.1.0
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
function clickEdit(){if(inEdit||_tabLock.on)return;inEdit=true;syncPageDisplay();edReload()}

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
// Called by the EDIT tab's Back button: grep this file for
//   onclick="showPage(curPage)"
// (v8.3.6: this line used to cite "line ~3394"; the button is nowhere near
// there, and a line number in a 3,300-line template is stale the moment
// anything above it moves. Grep for the markup instead.)
//
// Contrast with the tab buttons, which go through clickTab() — and clickTab()
// calls reTuneTab() when you click the page you are already on. showPage()
// deliberately does neither.
// This separation prevents unintended retune-on-back behavior when DMR tab was active
// before entering EDIT.  Example: User is on DMR → clicks EDIT → makes changes → clicks Back.
// Expected: returns to DMR without showing network selector (user didn't click DMR tab again).
// If showPage() incorrectly called clickTab() or reTuneTab(), it would trigger retune and
// show network selector unexpectedly.  Maintain this distinction to prevent regression.
function showPage(page){if(!PAGES.includes(page))return;inEdit=false;curPage=page;syncPageDisplay();_saveTabState()}
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
// ── Delegated grid click handling (v8.0.10) ─────────────────────────────────
// Replaces onclick="fn('${esc(x)}')" on every row across every tab's grid.
// HTML-escaping a value doesn't stop it from breaking out of the JS string
// once the browser decodes HTML entities in the attribute value, which
// happens before an inline event-handler attribute is parsed as script —
// so no amount of escaping esc() does makes that pattern safe. Rows now
// carry their data purely as data-* attributes (still esc()'d, but never
// executed as code — just read back as inert strings), and one delegated
// click listener per grid container (wired once; only innerHTML changes on
// re-render, so the container itself only needs wiring the first time)
// dispatches based on data-role.
function _gridClick(e){
  const lh=e.target.closest('[data-role="lh-btn"]');
  if(lh){
    e.stopPropagation();
    if(!lh.classList.contains('lh-off'))openLast(lh.dataset.url||'');
    return;
  }
  const row=e.target.closest('[data-role]');
  if(!row)return;
  switch(row.dataset.role){
    case 'tg-row':
      tuneTG(row.dataset.mode,row.dataset.tg,row.dataset.name);
      break;
    case 'asl-row':
      aslConnect(row.dataset.node,row.dataset.name);
      break;
    case 'echo-row':
      echoConnect(row.dataset.node,row.dataset.name);
      break;
    case 'dmr-net-row':
      switchDmrServer(row.dataset.name);
      break;
    case 'ref-row': {
      const idx=Number(row.dataset.idx);
      const base=row.dataset.base,name=row.dataset.name,ip=row.dataset.ip||'';
      if(row.dataset.conn==='dstar')dstarConnect(base,getDstarMod(idx),name);
      else if(row.dataset.conn==='xlx')xlxConnect(name,base,getXlxMod(idx));
      else if(row.dataset.conn==='m17')m17Connect(name,base,ip,getM17Mod(idx));
      break;
    }
  }
}
function _wireGridClicks(el){
  if(el&&!el.dataset.clickWired){
    el.addEventListener('click',_gridClick);
    el.dataset.clickWired='1';
  }
}
function renderDmrNetSelect(servers,activeServer){
  const el=byId('dmr-grid');if(!el)return;
  _wireGridClicks(el);
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
      const sLh=`<button class="btn-last${sUrl?'':' lh-off'}" data-role="lh-btn" data-url="${esc(sUrl)}" title="Last Heard">LH</button>`;
      const sCls=cls+' has-lh';
      return `<div class="${sCls}" data-role="dmr-net-row" data-name="${esc(s.name)}" title="${esc(s.name)}">
        <span class="row-num">${n}</span>
        <div class="dot ${dotCls}"></div>
        <span class="row-name">${esc(s.name)}</span>${sLh}</div>`;
    }).join('');
  if(!n)el.innerHTML='<div style="padding:1rem;color:var(--muted);font-family:var(--mono);font-size:.858rem">No DMR networks configured</div>';
}
function renderTGGrid(elId,tgs,mode){
  const el=byId(elId);if(!el)return;_wireGridClicks(el);const m=mode.toLowerCase();
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
    const lhBtn=showLh?`<button class="btn-last${url?'':' lh-off'}" data-role="lh-btn" data-url="${esc(url)}" title="Last Heard">LH</button>`:'';
    const pvtChip=hasPvt?'<span class="pvt-chip" title="Private call">PVT</span>':'';
    const rowAttrs=disc?'':`data-role="tg-row" data-mode="${esc(mode)}" data-tg="${esc(tg.tg)}" data-name="${esc(tg.name)}"`;
    return `<div class="${cls}" ${rowAttrs} ${disc?'':`title="${esc(tg.name)}"` }>
      <span class="row-num">${n}</span>
      <div class="dot ${dotCls}"></div>
      <span class="row-name">${esc(tg.name)}</span>${pvtChip}${lhBtn}</div>`;
  }).join('');
  if(!n)el.innerHTML=`<div style="padding:1rem;color:var(--muted);font-family:var(--mono);font-size:.858rem">No ${mode} entries</div>`;
}
function renderASLGrid(nodes,fav){
  const el=byId('asl-grid');if(!el)return;_wireGridClicks(el);let n=0;
  el.innerHTML=nodes.map(nd=>{
    if(nd.name===TG_BLANK_NAME||nd.node===TG_BLANK_ADDR)return '';
    n++;
    const active=fav===nd.node;
    return `<div class="${active?'row-grid active-asl':'row-grid'}" data-role="asl-row" data-node="${esc(nd.node)}" data-name="${esc(nd.name)}" title="${esc(nd.name)}">
      <span class="row-num">${n}</span>
      <div class="dot ${active?'dot-on':'dot-off'}"></div>
      <span class="row-name">${esc(nd.name)}</span></div>`;
  }).join('');
  if(!n)el.innerHTML='<div style="padding:1rem;color:var(--muted);font-family:var(--mono);font-size:.858rem">No ASL nodes saved</div>';
}
function renderEchoGrid(nodes,fav){
  const el=byId('echo-grid');if(!el)return;_wireGridClicks(el);let n=0;
  el.innerHTML=nodes.map(nd=>{
    if(nd.name===TG_BLANK_NAME||nd.node===TG_BLANK_ADDR)return '';
    n++;
    const active=fav===nd.node;
    return `<div class="${active?'row-grid active-echo':'row-grid'}" data-role="echo-row" data-node="${esc(nd.node)}" data-name="${esc(nd.name)}" title="${esc(nd.name)}">
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
  _wireGridClicks(el);
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
  // string (XLX/DSTAR's shape — r.tg, e.g. "XLX334AL" — the trailing L
  // is part of the stored value, see makeTuneKey below). M17's rows carry
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
    const lhBtn=`<button class="btn-last${url?'':' lh-off'}" data-role="lh-btn" data-url="${esc(url)}" title="Last Heard">LH</button>`;
    const refCls=cls+' has-lh ref-tap';
    return `<div class="${refCls}" data-role="ref-row" data-conn="${cfg.connKind}" data-idx="${i}" data-base="${esc(base)}" data-name="${esc(r.name)}" data-ip="${esc(r.ip||'')}" title="${esc(r.name)}">
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
    connKind:'dstar'
  });
}
function renderXlxGrid(refs,activeTune){
  renderReflectorGrid('xlx-grid',refs,activeTune,{
    emptyMsg:'No XLX reflectors saved',activeClass:'active-xlx',mode:'XLX',
    modSel:xlxModSel,modSelName:'xlxModSel',btnConn:'btn btn-conn',
    connKind:'xlx'
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
    connKind:'m17'
  });
}
// ── Last Heard helpers ────────────────────────────────────────────────────────
let _lhWin=null;
function openLast(url){
  if(!url)return;
  let u=String(url).trim();
  // Bare host/IP (no scheme) would resolve relative to the dashboard origin
  // (e.g. http://192.168.x.x:8989/78.129.135.58) — prepend http:// so it opens
  // as an absolute URL. Existing http(s):// values pass through untouched.
  // v8.0.10: this used to accept ANY "scheme://" unchanged, which let a
  // stored javascript:// Last-Heard URL run script when opened — now only
  // http/https pass through; anything else gets http:// prepended in front
  // of it instead, which neutralizes it rather than executing it.
  if(!/^https?:\/\//i.test(u)) u='http://'+u;
  // v8.7.7: an IP-address host has no certificate — use http even when the
  // stored link says https (same rule as _lh_url_ip_http() on save).
  u=u.replace(/^https:\/\/((?:[^\/?#@]*@)?(?:\d{1,3}(?:\.\d{1,3}){3}|\[[0-9a-f:.]+\]))(?=[:\/?#]|$)/i,'http://$1');
  // Track the actual window handle (not just the 'asl_dvs_lh' name target).
  // Relying on the name alone let some browsers get into a stuck state after
  // the user manually closed the popup — later window.open() calls with the
  // same name silently no-op instead of opening a fresh window. Checking
  // .closed lets us tell the two cases apart: reuse+navigate the existing
  // window when it's still alive, or open a brand-new one when it's gone.
  if(_lhWin && !_lhWin.closed){
    _lhWin.location.href=u;
    _lhWin.focus();
  }else{
    _lhWin=window.open(u,'asl_dvs_lh');
  }
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
  _updateLhBtn('lh-btn-FCSNET', modeNetUrls.FCS||'');   // v8.8.1: FCS network LH
  dmrSaveSync();   // v8.9.6: DMR Save follows the network dropdown
  // P25/NXDN moved to per-row LH buttons (like YSF/FCS) — no quick-bar button to update.
}

/* ── FCS browse card (v8.4.2 — Stage 2 of the FCS tab rework) ───────────────
   Servers / Rooms menus + Connect + LH, fed by /api/fcs-hosts (parsed from
   /var/lib/mmdvm/FCSRooms.txt).  It sits above the existing FCS grid, which
   is untouched and stays as the favorites list.
   Connect goes through tuneTG() like any grid row, but passes the tune value
   in its 9xxxxx form ("FCS001" + "02" -> "900102").  That is what the server
   reports back as current_fav for FCS, so the duplicate-tune guard, the grid
   highlight and pollAbInfo()'s last_tune confirmation all compare like with
   like (a raw "FCS00102" would only be confirmed by the 10 s timeout).
   Hooks into existing code: syncPageDisplay() -> fcsCardEnter(),
   applyGridState() -> fcsCardSync(d), dimGrid()/undimGrid() dim the card.
   Room lists are compact [nn,name] pairs; server ids are "FCS" + 3 digits. */
const FCS_TTL_MS=300000;
function fcsTuneValue(sid,nn){return '9'+sid.slice(3)+nn;}
function fcsFromTune(v){
  const m=/^9(\d{3})(\d{2})$/.exec(String(v||''));
  return m?{sid:'FCS'+m[1],nn:m[2]}:null;
}
function fcsMsg(text,kind){
  const el=byId('fcs-card-msg');
  if(!el)return;
  el.textContent=text||'';
  el.hidden=!text;
  el.className='fcs-card-msg'+(kind==='warn'?' warn':'');
}
function fcsCardEnter(){
  if(!byId('fcs-card')||_fcs.loading)return;
  if(_fcs.loaded&&Date.now()-_fcs.at<FCS_TTL_MS)return;
  if(Date.now()-_fcs.tried<5000)return;   // don't hammer after a failure
  loadFcsHosts();
}
async function loadFcsHosts(){
  _fcs.loading=true;_fcs.tried=Date.now();
  if(!_fcs.loaded)fcsMsg('Loading FCS rooms…');
  try{
    const r=await fetch('/api/fcs-hosts');
    if(!r.ok)throw new Error('HTTP '+r.status);
    const d=await r.json();
    if(!d||d.ok!==true||!Array.isArray(d.servers))throw new Error('bad payload');
    fcsBuildServers(d);
  }catch(e){
    if(!_fcs.loaded)fcsMsg('Could not load the FCS room list. Reopen this tab to try again.','warn');
  }finally{_fcs.loading=false}
}
function fcsBuildServers(d){
  const ssel=byId('fcs-srv-select'),rsel=byId('fcs-room-select');
  if(!ssel||!rsel)return;
  if(!d.found||!d.servers.length){
    _fcs.loaded=false;_fcs.byId={};_fcs.sig='';
    ssel.innerHTML='<option value="">No servers</option>';
    rsel.innerHTML='<option value="">No rooms</option>';
    ssel.disabled=true;rsel.disabled=true;
    fcsMsg(d.found?'FCSRooms.txt has no usable rooms.'
                  :'FCS room list not found'+(d.path?' at '+d.path:'')+
                   '. Check that DVSwitch has downloaded FCSRooms.txt.','warn');
    fcsCardButtons();
    return;
  }
  _fcs.loaded=true;_fcs.at=Date.now();
  const sig=(d.mtime||0)+':'+d.servers.length+':'+((d.stats&&d.stats.rooms)||0);
  if(sig!==_fcs.sig){                       // rebuild only when the list changed
    _fcs.sig=sig;
    _fcs.byId={};
    d.servers.forEach(s=>{_fcs.byId[s.id]=s;});
    const keepS=ssel.value,keepR=rsel.value;
    ssel.innerHTML='<option value="">Select server…</option>'+
      d.servers.map(s=>`<option value="${esc(s.id)}">${esc(s.id)}</option>`).join('');
    ssel.disabled=false;
    if(keepS&&_fcs.byId[keepS])ssel.value=keepS;
    fcsFillRooms(true,keepR);
  }
  let dated=d.updated||'';
  if(!dated&&d.mtime)dated=new Date(d.mtime*1000).toLocaleDateString();
  const rooms=(d.stats&&d.stats.rooms)||0;
  fcsMsg(d.servers.length+' servers, '+rooms+' rooms.'+(dated?' List dated '+dated+'.':''));
  fcsCardSync();
}
function fcsFillRooms(keepRoom,prevRoom){
  const ssel=byId('fcs-srv-select'),rsel=byId('fcs-room-select');
  if(!ssel||!rsel)return;
  const s=_fcs.byId[ssel.value];
  const prev=keepRoom?(prevRoom!==undefined?prevRoom:rsel.value):'';
  if(!s){
    rsel.innerHTML='<option value="">Select room…</option>';
    rsel.disabled=true;
    fcsCardButtons();
    return;
  }
  rsel.innerHTML='<option value="">Select room…</option>'+
    s.rooms.map(r=>`<option value="${esc(r[0])}">${esc(r[0])} · ${esc(r[1])}</option>`).join('');
  rsel.disabled=false;
  if(prev&&s.rooms.some(r=>r[0]===prev))rsel.value=prev;
  else if(s.rooms.length===1)rsel.value=s.rooms[0][0];
  fcsCardButtons();
}
function fcsCardButtons(){
  const ssel=byId('fcs-srv-select'),rsel=byId('fcs-room-select');
  const btn=byId('fcs-connect-btn'),lh=byId('lh-btn-FCS');
  if(!ssel||!rsel||!btn)return;
  const s=_fcs.byId[ssel.value];
  btn.disabled=!(s&&rsel.value);
  const sv=byId('fcs-save-btn');
  if(sv)sv.disabled=!(s&&rsel.value)||_fcs.saving;
  const url=s?(s.lh_url||''):'';
  _updateLhBtn('lh-btn-FCS',url);
  if(lh)lh.setAttribute('aria-disabled',url?'false':'true');
}
function fcsCardSync(d){
  // Follow the tuned room, but only when the tuned value itself changes, so
  // a poll never overwrites a pick the user is in the middle of making.
  if(d)_fcs.tuned=(d.page==='FCS'&&d.current_fav)?String(d.current_fav):'';
  if(!_fcs.loaded||_fcs.tuned===_fcs.applied)return;
  _fcs.applied=_fcs.tuned;
  const t=fcsFromTune(_fcs.tuned);
  if(!t||!_fcs.byId[t.sid])return;
  const ssel=byId('fcs-srv-select'),rsel=byId('fcs-room-select');
  if(!ssel||!rsel)return;
  if(ssel.value!==t.sid){ssel.value=t.sid;fcsFillRooms(false);}
  if([...rsel.options].some(o=>o.value===t.nn))rsel.value=t.nn;
  fcsCardButtons();
}
// NOTE (v8.5.2): pollAbInfo() confirms a tune when ABInfo's last_tune equals the
// tg we sent AND ABInfo's mode matches dvsModeFor(mode) ("YSF" for FCS).  On the
// author's node ABInfo reports tlv.ambe_mode "YSFN" (with digital.tg and
// last_tune both 900102 after a card Connect), and the old exact compare never
// matched, so FCS/YSF only confirmed via the 10 s fallback.  Fixed in v8.5.2 with
// a prefix match in pollAbInfo() (covers "YSFN" and "YSFW").
function fcsConnect(){
  const ssel=byId('fcs-srv-select'),rsel=byId('fcs-room-select');
  const s=ssel?_fcs.byId[ssel.value]:null;
  const nn=rsel?rsel.value:'';
  const room=s?s.rooms.find(r=>r[0]===nn):null;
  if(!s||!room)return;
  const tg=fcsTuneValue(s.id,nn);
  const label=s.id+'-'+nn+' '+room[1];
  if(curTg&&curTg.mode==='FCS'&&curTg.tg===tg){toast('Already tuned to '+label,'ok');return;}
  tuneTG('FCS',tg,label);
}
async function fcsSave(){
  // Save the picked room into the next free FCS favorite slot (server side:
  // action_save_fcs_favorite).  Only the room is sent — the server rebuilds
  // the name, tune value and Last Heard URL from FCSRooms.txt — then the
  // grids are re-drawn from /api/talkgroups so the new row shows up below.
  if(_fcs.saving)return;
  const ssel=byId('fcs-srv-select'),rsel=byId('fcs-room-select');
  const s=ssel?_fcs.byId[ssel.value]:null;
  const nn=rsel?rsel.value:'';
  if(!s||!s.rooms.some(r=>r[0]===nn))return;
  _fcs.saving=true;fcsCardButtons();
  try{
    const d=await api({action:'save-fcs-favorite',room:fcsTuneValue(s.id,nn)},10000);
    if(d.ok){
      // "already in favorites" comes back ok too (nothing to fix) — show it as info.
      toast(d.message,/already in favorites/.test(d.message)?'info':'ok');
      await loadTgData();
    }else{
      toast(d.message||'Could not save the favorite','err');
    }
  }finally{_fcs.saving=false;fcsCardButtons();}
}
function openFcsLast(){
  const ssel=byId('fcs-srv-select');
  const s=ssel?_fcs.byId[ssel.value]:null;
  openLast(s?s.lh_url||'':'');
}


/* ── Browse-card engine (v9.0.2) ─────────────────────────────────────────────
   One set of functions behind the list cards: load the list once (5-minute
   refresh, 5-second back-off after a failed load), a search box, one
   dropdown, Connect, Save and LH.  Each card is one LC_CFG entry keyed by
   its page.  v9.0.2 moves P25, NXDN and STFU onto it (they were the tgc*
   functions), v9.0.3 D-STAR and XLX (the rfc* functions), v9.0.4 YSF (the
   ysf* functions); M17 and FCS follow in later steps.
   Element ids: <page lower>-card / -filter / -ref-select / -connect-btn /
   -save-btn / -card-msg and lh-btn-<PAGE>REF.  dimGrid()/undimGrid() already
   toggle #<page>-card.  Hooks: syncPageDisplay() -> lcCardEnter(page),
   applyGridState() -> lcCardSync(page,d).  The card markup calls
   lcFilterSoon / lcButtons / lcConnect / lcSave / lcOpenLast.
   A card's settings (k = the page key):
     api          list URL
     loading      "Loading …" text        fail   text when the fetch fails
     none         dropdown text when the list is empty
     pick / nouns "Select talkgroup…" / "talkgroups" in the count line
     msgCls       CSS class of the message line
     empty(d)     warning when the list is missing or has no rows
     sig(d)       changes whenever the list does (rebuild only then)
     id(r)        a row's key: the dropdown value, and what tuned() returns
     search(r)    text the search box matches (lower-cased once, kept on r._s)
     option(r)    dropdown text, HTML already escaped
     base(d)      trailing "List dated …" text for the count line
     tuned(v)     the server's current_fav -> row key ('' when none)
     lh(r)        Last Heard URL ('' when none)
     connect(k,r) and save(k,r) -> the /api/action payload (null = don't)
   Optional:
     enter(k)     run each time the tab opens (e.g. fill a module menu)
     ready(k,r)   Connect / Save allowed (default: a row is picked)
     rowOf(t)     tuned() value -> row key when they differ (default: same)
     follow(k,t)  extra follow-the-tune step (e.g. set the module menu)
     ctl          more element suffixes to disable with the list (e.g. cc-select)
     keep(k,r)    extra filter besides the search words (e.g. country)
     clear(k)     reset that extra filter when it hides the tuned entry
     rebuilt(k,d) run when a changed list has been indexed (extra menus)
     emptied(k)   run when the list comes back missing or empty */
const LC_TTL_MS=300000;
const LC_CFG={};
const _lc={};
function lcDef(k,cfg){
  LC_CFG[k]=cfg;
  _lc[k]={loaded:false,loading:false,saving:false,at:0,tried:0,rows:[],by:{},
          total:0,base:'',sig:'',tuned:'',applied:null,timer:0};
}
function lcEl(k,s){return byId(k.toLowerCase()+'-'+s);}
function lcMsg(k,text,kind){
  const el=lcEl(k,'card-msg');
  if(!el)return;
  el.textContent=text||'';
  el.hidden=!text;
  el.className=LC_CFG[k].msgCls+(kind==='warn'?' warn':'');
}
function lcCardEnter(k){
  const s=_lc[k];
  if(!s||!lcEl(k,'card')||s.loading)return;
  if(LC_CFG[k].enter)LC_CFG[k].enter(k);
  if(s.loaded&&Date.now()-s.at<LC_TTL_MS)return;
  if(Date.now()-s.tried<5000)return;   // don't hammer after a failure
  lcLoad(k);
}
async function lcLoad(k){
  const s=_lc[k],c=LC_CFG[k];
  s.loading=true;s.tried=Date.now();
  if(!s.loaded)lcMsg(k,c.loading);
  try{
    const r=await fetch(c.api);
    if(!r.ok)throw new Error('HTTP '+r.status);
    const d=await r.json();
    if(!d||d.ok!==true||!Array.isArray(d.reflectors))throw new Error('bad payload');
    lcBuild(k,d);
  }catch(e){
    if(!s.loaded)lcMsg(k,c.fail,'warn');
  }finally{s.loading=false}
}
function lcSetDisabled(k,off){
  ['filter','ref-select'].concat(LC_CFG[k].ctl||[]).forEach(n=>{const el=lcEl(k,n);if(el)el.disabled=off;});
}
function lcBuild(k,d){
  const s=_lc[k],c=LC_CFG[k],rsel=lcEl(k,'ref-select');
  if(!rsel)return;
  if(!d.found||!d.reflectors.length){
    s.loaded=false;s.rows=[];s.by={};s.sig='';s.total=0;
    if(c.emptied)c.emptied(k);
    rsel.innerHTML='<option value="">'+c.none+'</option>';
    lcSetDisabled(k,true);
    lcMsg(k,c.empty(d),'warn');
    lcButtons(k);
    return;
  }
  s.loaded=true;s.at=Date.now();
  const sig=c.sig(d);
  if(sig!==s.sig){                          // rebuild only when the list changed
    s.sig=sig;s.rows=d.reflectors;s.by={};
    d.reflectors.forEach(r=>{s.by[c.id(r)]=r;r._s=c.search(r).toLowerCase();});
    s.total=d.reflectors.length;
    if(c.rebuilt)c.rebuilt(k,d);
    lcSetDisabled(k,false);
    s.applied=null;                         // let lcCardSync re-follow the tune
  }
  s.base=c.base(d);
  lcFill(k,true);
  lcCardSync(k);
}
function lcDated(d){
  let dated=d.updated||'';
  if(!dated&&d.mtime)dated=new Date(d.mtime*1000).toLocaleDateString();
  return dated?' List dated '+dated+'.':'';
}
function lcFilterSoon(k){
  const s=_lc[k];
  clearTimeout(s.timer);
  s.timer=setTimeout(()=>lcFill(k,true),150);
}
function lcMatches(k){
  const words=String((lcEl(k,'filter')||{}).value||'').toLowerCase().split(/\s+/).filter(Boolean);
  const keep=LC_CFG[k].keep;
  return _lc[k].rows.filter(r=>(!keep||keep(k,r))&&words.every(w=>r._s.includes(w)));
}
function lcFill(k,keep,want){
  const s=_lc[k],c=LC_CFG[k],rsel=lcEl(k,'ref-select');
  if(!rsel||!s.loaded)return;
  const prev=want!==undefined?want:(keep?rsel.value:'');
  const list=lcMatches(k);
  // Several hundred options: build the string once and assign it once.
  rsel.innerHTML=(list.length?'<option value="">'+c.pick+'</option>':'<option value="">No matches</option>')+
    list.map(r=>`<option value="${esc(c.id(r))}">${c.option(r)}</option>`).join('');
  if(prev&&list.some(r=>c.id(r)===prev))rsel.value=prev;
  else if(list.length===1)rsel.value=c.id(list[0]);
  const n=list.length,t=s.total;
  lcMsg(k,(n===t?t.toLocaleString()+' '+c.nouns+'.':'Showing '+n.toLocaleString()+' of '+t.toLocaleString()+' '+c.nouns+'.')+s.base);
  lcButtons(k);
}
function lcSelected(k){
  const rsel=lcEl(k,'ref-select');
  return rsel&&rsel.value&&_lc[k]?_lc[k].by[rsel.value]||null:null;
}
function lcButtons(k){
  const r=lcSelected(k),c=LC_CFG[k];
  const ok=c.ready?c.ready(k,r):!!r;
  const btn=lcEl(k,'connect-btn');
  if(btn)btn.disabled=!ok;
  const sv=lcEl(k,'save-btn');
  if(sv)sv.disabled=!ok||_lc[k].saving;
  const url=r?c.lh(r):'';
  _updateLhBtn('lh-btn-'+k+'REF',url);
  const lh=byId('lh-btn-'+k+'REF');
  if(lh)lh.setAttribute('aria-disabled',url?'false':'true');
}
function lcCardSync(k,d){
  // Follow the tuned entry, but only when the tuned value itself changes,
  // so a poll never overwrites a pick the user is in the middle of making.
  const s=_lc[k];
  if(!s)return;
  if(d)s.tuned=(d.page===k&&d.current_fav)?LC_CFG[k].tuned(d.current_fav):'';
  if(!s.loaded||s.tuned===s.applied)return;
  s.applied=s.tuned;
  const c=LC_CFG[k];
  const r=s.by[c.rowOf?c.rowOf(s.tuned):s.tuned];
  if(!r)return;
  if(!lcMatches(k).includes(r)){            // search hides it: clear the search
    const f=lcEl(k,'filter');
    if(f)f.value='';
    if(c.clear)c.clear(k);
  }
  if(c.follow)c.follow(k,s.tuned);
  lcFill(k,false,c.id(r));
}
function lcConnect(k){
  const r=lcSelected(k);
  if(r)LC_CFG[k].connect(k,r);
}
async function lcSave(k){
  // Save the picked entry into the next free favorite slot for this tab,
  // then re-draw the grids from the server so the new row shows up below.
  const s=_lc[k];
  if(!s||s.saving)return;
  const r=lcSelected(k);
  if(!r)return;
  const payload=LC_CFG[k].save(k,r);
  if(!payload)return;
  s.saving=true;lcButtons(k);
  try{
    const d=await api(payload,10000);
    if(d.ok){
      toast(d.message,/already in favorites/.test(d.message)?'info':'ok');
      await loadTgData();
    }else{
      toast(d.message||'Could not save the favorite','err');
    }
  }finally{s.saving=false;lcButtons(k);}
}
function lcOpenLast(k){
  const r=lcSelected(k);
  openLast(r?LC_CFG[k].lh(r):'');
}
function lcHostUrl(a){
  // An address -> http://address/ with no port (IPv6 in brackets).
  a=String(a||'');
  if(!a)return '';
  return 'http://'+(a.includes(':')&&!a.startsWith('[')?'['+a+']':a)+'/';
}

/* ── P25 / NXDN / STFU talkgroup cards (v8.8.8, v8.9.5; engine v9.0.2) ────────
   Search box + Talkgroup menu + Connect + Save, fed by /api/p25-hosts and
   /api/nxdn-hosts (P25Hosts.txt / NXDNHosts.txt, found via each gateway's
   ini) and /api/stfu-hosts (TGList_BM.txt).  Each sits above its tab's
   grid, which stays as the favorites list.
   P25 / NXDN rows are [talkgroup, address, port, private]; the lists carry no
   names, so entries read "38 · host", and LH opens the address.
   STFU rows are [talkgroup, name, description]; search covers all three and
   there is no LH (STFU keeps its one network LH).
   Connect sends the talkgroup number through tuneTG() — the gateway maps it
   to the address — which is what the server reports back as current_fav.
   Numbers are compared with leading zeros removed ("0038" == "38").
   Save sends only the number (server side: action_save_tg_favorite), which
   looks the rest up in the same list. */
function lcTgNorm(v){v=String(v||'').trim();return /^\d{1,8}$/.test(v)?String(parseInt(v,10)):'';}
function lcTgCard(k,named){
  lcDef(k,{
    api:'/api/'+k.toLowerCase()+'-hosts',
    loading:'Loading '+k+' talkgroups…',
    fail:'Could not load the '+k+' talkgroup list. Reopen this tab to try again.',
    none:'No talkgroups',pick:'Select talkgroup…',nouns:'talkgroups',msgCls:'tgc-card-msg',
    empty:d=>d.found?k+' host list has no usable talkgroups.'
      :k+' talkgroup list not found'+(d.path?' at '+d.path:'')+'. Check that DVSwitch has downloaded it.',
    sig:d=>(d.mtime||0)+':'+d.reflectors.length+':'+(d.paths||[]).join('|'),
    id:r=>r[0],
    search:r=>r[0]+' '+r[1]+(named?' '+(r[2]||''):''),
    option:r=>`${esc(r[0])} · ${esc(r[1])}${r[3]?' (private)':''}`,
    base:d=>{
      const priv=(d.paths||[]).length>1?' Includes your private list.':'';
      const other=(d.stats&&d.stats.other)||0;
      return lcDated(d)+(d.path?' From '+d.path+'.':'')+priv+
        (other?' '+other.toLocaleString()+' reflector and private-call entries left out.':'');
    },
    tuned:lcTgNorm,
    lh:r=>named?'':lcHostUrl(r[1]),
    connect:(k,r)=>{
      const label=r[0]+' '+r[1];
      if(curTg&&curTg.mode===k&&lcTgNorm(curTg.tg)===r[0]){toast('Already tuned to '+label,'ok');return;}
      tuneTG(k,r[0],label);
    },
    save:(k,r)=>({action:'save-tg-favorite',mode:k,tg:r[0]}),
  });
}
lcTgCard('P25',false);
lcTgCard('NXDN',false);
lcTgCard('STFU',true);

/* ── M17 browse card (v8.6.2 — Stage 2 of the M17 tab rework) ───────────────
   Reflector / Module menus + Connect + LH, fed by /api/m17-hosts (parsed from
   /var/lib/mmdvm/M17Hosts.json).  It sits above the existing #m17-grid, which
   is untouched and stays as the favorites list.
   Connect goes through the existing m17Connect(name,base,ip,module), the same
   call a grid row makes, so there is no new connect action: the ini rewrite
   and usrp2m17 restart are unchanged.  The active key is base|module — what
   action_m17_connect() reports back as current_fav — so the duplicate-connect
   guard, the grid highlight and this card all compare like with like.
   Hooks into existing code: syncPageDisplay() -> m17CardEnter(),
   applyGridState() -> m17CardSync(d).  dimGrid()/undimGrid() already toggle
   #<mode>-card, so the card dims during a connect with no change to them.
   Two things differ from the FCS card, both from the real host file:
     - The module menu is per-reflector.  Entries carry their own module list;
       a reflector with no list falls back to A-Z.  A single-module reflector
       is preselected, the way fcsFillRooms() preselects a server's only room.
       v8.7.2: the A-Z fallback now only ever fires for an entry whose
       "modules" key is MISSING or null — a present-but-unusable list drops
       the reflector server-side, so this menu never guesses against module
       data the parser rejected.  Run m17_modules_probe.sh for current counts;
       the figures that used to be quoted here went stale.
     - Designators are opaque: "M17-003" and "URF018" both occur, so nothing
       here assumes a prefix or splits on "-". */
const M17_TTL_MS=300000;
const M17_AZ=Array.from({length:26},(_,i)=>String.fromCharCode(65+i));
function m17FavKey(base,mod){return base+'|'+mod;}
function m17FromFav(v){
  const s=String(v||'');
  const i=s.lastIndexOf('|');
  return i>0?{base:s.slice(0,i),mod:s.slice(i+1)}:null;
}
function m17Msg(text,kind){
  const el=byId('m17-card-msg');
  if(!el)return;
  el.textContent=text||'';
  el.hidden=!text;
  el.className='m17-card-msg'+(kind==='warn'?' warn':'');
}
function m17CardEnter(){
  if(!byId('m17-card')||_m17c.loading)return;
  if(_m17c.loaded&&Date.now()-_m17c.at<M17_TTL_MS)return;
  if(Date.now()-_m17c.tried<5000)return;   // don't hammer after a failure
  loadM17Hosts();
}
async function loadM17Hosts(){
  _m17c.loading=true;_m17c.tried=Date.now();
  if(!_m17c.loaded)m17Msg('Loading M17 reflectors…');
  try{
    const r=await fetch('/api/m17-hosts');
    if(!r.ok)throw new Error('HTTP '+r.status);
    const d=await r.json();
    if(!d||d.ok!==true||!Array.isArray(d.reflectors))throw new Error('bad payload');
    m17BuildRefs(d);
  }catch(e){
    if(!_m17c.loaded)m17Msg('Could not load the M17 reflector list. Reopen this tab to try again.','warn');
  }finally{_m17c.loading=false}
}
function m17BuildRefs(d){
  const rsel=byId('m17-ref-select'),msel=byId('m17-mod-select');
  if(!rsel||!msel)return;
  if(!d.found||!d.reflectors.length){
    _m17c.loaded=false;_m17c.byId={};_m17c.sig='';
    rsel.innerHTML='<option value="">No reflectors</option>';
    msel.innerHTML='<option value="">Select module…</option>';
    rsel.disabled=true;msel.disabled=true;
    m17Msg(d.found?'M17Hosts.json has no usable reflectors.'
                  :'M17 reflector list not found. Install m17hosts_update.sh to fetch it.','warn');
    m17CardButtons();
    return;
  }
  _m17c.loaded=true;_m17c.at=Date.now();
  const st=d.stats||{};
  const sig=(d.mtime||0)+':'+d.reflectors.length+':'+(st.reflectors||0);
  if(sig!==_m17c.sig){                      // rebuild only when the list changed
    _m17c.sig=sig;
    _m17c.byId={};
    d.reflectors.forEach(r=>{_m17c.byId[r.id]=r;});
    const keepR=rsel.value,keepM=msel.value;
    rsel.innerHTML='<option value="">Select reflector…</option>'+
      d.reflectors.map(r=>`<option value="${esc(r.id)}">${esc(r.id)}${r.label&&r.label!==r.id?' · '+esc(r.label):''}</option>`).join('');
    rsel.disabled=false;
    if(keepR&&_m17c.byId[keepR])rsel.value=keepR;
    m17FillModules(true,keepM);
  }
  let dated=d.updated||'';
  if(!dated&&d.mtime)dated=new Date(d.mtime*1000).toLocaleDateString();
  // v8.7.4: reflector-level rejections only. bad_modules and other_mode
  // count rejected MODULES, not reflectors, so summing them here would
  // badly overstate the number (other_mode alone is 33 on the live file
  // against 5 genuinely hidden reflectors).
  const hidden=(st.other_ports||0)+(st.ipv6_only||0)+(st.no_m17||0)
               +(st.malformed||0)+(st.duplicates||0);
  let msg=d.reflectors.length+' reflector'+(d.reflectors.length===1?'':'s')+'.';
  if(hidden)msg+=' '+hidden+' hidden (not reachable over M17).';
  if(dated)msg+=' List dated '+dated+'.';
  m17Msg(msg);
  m17CardSync();
}
function m17FillModules(keepMod,prevMod){
  // Module menu is per-reflector: the host file says which modules a reflector
  // actually publishes.  No list at all -> offer A-Z rather than nothing.
  const rsel=byId('m17-ref-select'),msel=byId('m17-mod-select');
  if(!rsel||!msel)return;
  const r=_m17c.byId[rsel.value];
  const prev=keepMod?(prevMod!==undefined?prevMod:msel.value):'';
  if(!r){
    msel.innerHTML='<option value="">Select module…</option>';
    msel.disabled=true;
    m17CardButtons();
    return;
  }
  const mods=(Array.isArray(r.modules)&&r.modules.length)?r.modules:M17_AZ;
  msel.innerHTML='<option value="">Select module…</option>'+
    '<option value="@ALL">All Modules</option>'+
    mods.map(l=>`<option value="${esc(l)}">Mod-${esc(l)}</option>`).join('');
  msel.disabled=false;
  if(prev&&[...msel.options].some(o=>o.value===prev))msel.value=prev;
  else if(Array.isArray(r.modules)&&r.modules.length===1)msel.value=r.modules[0];
  m17CardButtons();
}
function m17CardButtons(){
  const rsel=byId('m17-ref-select'),msel=byId('m17-mod-select');
  const btn=byId('m17-connect-btn'),lh=byId('lh-btn-M17');
  if(!rsel||!msel||!btn)return;
  const r=_m17c.byId[rsel.value];
  btn.disabled=!(r&&msel.value);
  const sv=byId('m17-save-btn');
  if(sv)sv.disabled=!(r&&msel.value)||_m17c.saving;
  const url=r?(r.lh_url||''):'';
  _updateLhBtn('lh-btn-M17',url);
  if(lh)lh.setAttribute('aria-disabled',url?'false':'true');
}
function m17CardSync(d){
  // Follow the connected reflector, but only when the value itself changes, so
  // a poll never overwrites a pick the user is in the middle of making.
  if(d)_m17c.tuned=(d.page==='M17'&&d.current_fav)?String(d.current_fav):'';
  if(!_m17c.loaded||_m17c.tuned===_m17c.applied)return;
  _m17c.applied=_m17c.tuned;
  const t=m17FromFav(_m17c.tuned);
  if(!t||!_m17c.byId[t.base])return;   // quick-bar connects use the raw IP as base
  const rsel=byId('m17-ref-select'),msel=byId('m17-mod-select');
  if(!rsel||!msel)return;
  if(rsel.value!==t.base){rsel.value=t.base;m17FillModules(false);}
  if([...msel.options].some(o=>o.value===t.mod))msel.value=t.mod;
  m17CardButtons();
}
function m17CardConnect(){
  const rsel=byId('m17-ref-select'),msel=byId('m17-mod-select');
  const r=rsel?_m17c.byId[rsel.value]:null;
  const mod=msel?msel.value:'';
  if(!r||!mod)return;
  const key=m17FavKey(r.id,mod);
  if(curTg&&curTg.mode==='M17'&&curTg.tg===key){
    toast('Already connected to '+r.id+' Mod-'+mod,'ok');return;
  }
  // Same call a favorites row makes: name, base, ip, module.
  m17Connect(r.label||r.id,r.id,r.addr,mod);
}
async function m17CardSave(){
  // Save the picked reflector into the next free M17 favorite slot (server
  // side: action_save_m17_favorite).  Only the designator and module are sent
  // — the server rebuilds the label, address and Last Heard URL from
  // M17Hosts.json — then the grids are redrawn from /api/m17-reflectors so the
  // new row shows up below.  Mirrors fcsSave().
  if(_m17c.saving)return;
  const rsel=byId('m17-ref-select'),msel=byId('m17-mod-select');
  const r=rsel?_m17c.byId[rsel.value]:null;
  const mod=msel?msel.value:'';
  if(!r||!mod)return;
  _m17c.saving=true;m17CardButtons();
  try{
    const d=await api({action:'save-m17-favorite',base:r.id,module:mod},10000);
    if(d.ok){
      // "already in favorites" comes back ok too (nothing to fix) — show it as info.
      toast(d.message,/already in favorites/.test(d.message)?'info':'ok');
      await loadTgData();
    }else{
      toast(d.message||'Could not save the favorite','err');
    }
  }finally{_m17c.saving=false;m17CardButtons();}
}
function openM17Last(){
  const rsel=byId('m17-ref-select');
  const r=rsel?_m17c.byId[rsel.value]:null;
  openLast(r?r.lh_url||'':'');
}

/* ── XLX / D-STAR reflector cards (v8.9.1, v8.9.3; engine v9.0.3) ───────────
   Search box + Reflector menu + small Module menu + Connect + LH + Save.
   XLX is fed by /api/xlx-hosts (XLXHosts.txt), D-STAR by /api/dstar-hosts
   (DPlus / DExtra / DCS lists, with the XLX entries left out because the
   XLX tab covers them).  Rows are {id, addr}; entries read
   "XLX307 · address".  The grid below stays as the favorites list.
   Connect goes through xlxConnect() / dstarConnect(), the same call a
   favorites row makes.  The tune string is id+module+'L' — also what the
   server reports back as current_fav — so the duplicate-connect check and
   card follow compare like with like.  No All-Modules option: a
   D-STAR-style link takes one letter.  LH opens http://address/ with no
   port.  Save sends the reflector and module; the server re-checks the list
   and stores http://address as the favorite's Last Heard link.
   Extra element: <page>-mod-select. */
function lcRefMod(k){const m=lcEl(k,'mod-select');return m?m.value:'';}
function lcRefFromFav(v){
  // current_fav is the tune string itself, e.g. "XLX307AL" or "REF001CL".
  const s=String(v||'').trim().toUpperCase();
  if(s.length<4||s.slice(-1)!=='L')return null;
  const mod=s.slice(-2,-1),base=s.slice(0,-2).trim();
  return /^[A-Z]$/.test(mod)&&base?{base:base,mod:mod}:null;
}
function lcRefCard(k,what,file,save,connect){
  lcDef(k,{
    api:'/api/'+k.toLowerCase()+'-hosts',
    loading:'Loading '+what+'s…',
    fail:'Could not load the '+what+' list. Reopen this tab to try again.',
    none:'No reflectors',pick:'Select reflector…',nouns:what+'s',msgCls:'rfc-card-msg',
    empty:d=>d.found?'The '+what+' list has no usable entries.'
      :what+' list not found at '+(d.path||file)+'. Check that DVSwitch has downloaded it.',
    sig:d=>(d.mtime||0)+':'+d.reflectors.length+':'+((d.stats||{}).reflectors||0),
    id:r=>r.id,
    search:r=>r.id+' '+(r.addr||''),
    option:r=>`${esc(r.id)} · ${r.addr?esc(r.addr):'no address'}`,
    base:d=>{
      const st=d.stats||{};
      const skipped=(st.malformed||0)+(st.duplicates||0);
      return (skipped?' '+skipped.toLocaleString()+' skipped as unusable.':'')+
        (st.xlx?' XLX reflectors are on the XLX tab.':'')+
        (Array.isArray(d.missing)&&d.missing.length?' Not found: '+d.missing.join(', ')+'.':'')+
        lcDated(d);
    },
    tuned:v=>String(v).trim().toUpperCase(),
    rowOf:t=>{const f=lcRefFromFav(t);return f?f.base:'';},
    follow:(k,t)=>{
      const f=lcRefFromFav(t),msel=lcEl(k,'mod-select');
      if(f&&msel&&[...msel.options].some(o=>o.value===f.mod))msel.value=f.mod;
    },
    enter:k=>{
      // A-Z, letter only so the menu stays narrow.  Filled once.
      const msel=lcEl(k,'mod-select');
      if(!msel||msel.options.length)return;
      let h='';
      for(let i=0;i<26;i++){const l=String.fromCharCode(65+i);h+=`<option value="${l}">${l}</option>`;}
      msel.innerHTML=h;
      msel.value='A';
    },
    ready:(k,r)=>!!(r&&lcRefMod(k)),
    lh:r=>lcHostUrl(r.addr),
    connect:(k,r)=>{
      const mod=lcRefMod(k);
      if(!mod)return;
      if(curTg&&curTg.mode===k&&curTg.tg===r.id+mod+'L'){
        toast('Already connected to '+r.id+' Mod-'+mod,'ok');return;
      }
      connect(r.id,mod);
    },
    save:(k,r)=>{const mod=lcRefMod(k);return mod?{action:save,base:r.id,module:mod}:null;},
  });
}
lcRefCard('XLX','XLX reflector','/var/lib/mmdvm/XLXHosts.txt','save-xlx-favorite',
          (id,mod)=>xlxConnect(id,id,mod));
lcRefCard('DSTAR','D-STAR reflector','/var/lib/mmdvm/','save-dstar-favorite',
          (id,mod)=>dstarConnect(id,mod,id+' Mod-'+mod));

/* ── YSF reflector card (v8.8.3; engine v9.0.4) ─────────────────────────────
   Country menu + text filter + Reflector menu + Connect + LH + Save, fed by
   /api/ysf-hosts (YSFHosts.txt, found via YSFGateway.ini).  It sits above
   the YSF grid, which stays as the favorites list.
   Rows are compact [number, name, description, address, port, country, link].
   Connect sends "address:port" through tuneTG(), the same call a grid row
   makes; that string is what the server reports back as current_fav, so the
   duplicate-tune guard, grid highlight and this card compare like with like.
   The card also recognises an older number-style tune (e.g. "87332").
   Both filters apply together; the text filter matches every typed word
   against number, name and description.  Country is a best guess from the
   start of the reflector name (see _ysf_country() on the server); "" = Other.
   The country picked when the list first loads is YSF_DEFAULT_CC.
   Save sends only address:port (server side: action_save_ysf_favorite),
   which rebuilds the name and Last Heard link from YSFHosts.txt.
   Extra element: ysf-cc-select. */
const YSF_DEFAULT_CC='US';
function ysfKey(r){return (r[3]+':'+r[4]).toLowerCase();}
function ysfTuneValue(r){return r[3]+':'+r[4];}
function ysfFindTuned(v){
  const s=_lc.YSF;
  v=String(v||'').trim();
  if(!v)return null;
  return s.by[v.toLowerCase()]||(/^\d{1,5}$/.test(v)?s.byId[v.padStart(5,'0')]||s.byId[v]:null)||null;
}
lcDef('YSF',{
  api:'/api/ysf-hosts',
  loading:'Loading YSF reflectors…',
  fail:'Could not load the YSF reflector list. Reopen this tab to try again.',
  none:'No reflectors',pick:'Select reflector…',nouns:'reflectors',msgCls:'ysf-card-msg',
  empty:d=>{
    const where=d.path?' at '+d.path:'';
    return d.found?'YSFHosts.txt has no reflectors with an address.'
      :d.note==='json'?'The YSF host list'+where+' is a .json file, which this dashboard does not read yet.'
      :'YSF reflector list not found'+where+'. Check that DVSwitch has downloaded YSFHosts.txt.';
  },
  sig:d=>(d.mtime||0)+':'+d.reflectors.length+':'+(d.path||''),
  id:ysfKey,
  search:r=>r[0]+' '+r[1]+' '+r[2],
  option:r=>`${esc(r[0])} · ${esc(r[1])}`,
  base:d=>lcDated(d)+(d.path?' From '+d.path+'.':''),
  tuned:v=>String(v),
  rowOf:t=>{const r=ysfFindTuned(t);return r?ysfKey(r):'';},
  ctl:['cc-select'],
  keep:(k,r)=>{const cc=(lcEl(k,'cc-select')||{}).value;return cc==='*'||cc===undefined||r[5]===cc;},
  clear:k=>{const c=lcEl(k,'cc-select');if(c)c.value='*';},
  emptied:k=>{
    const s=_lc[k];s.byId={};
    const c=lcEl(k,'cc-select');
    if(c)c.innerHTML='<option value="*">All countries</option>';
  },
  rebuilt:(k,d)=>{
    const s=_lc[k],csel=lcEl(k,'cc-select');
    s.byId={};
    d.reflectors.forEach(r=>{if(!s.byId[r[0]])s.byId[r[0]]=r;});
    if(!csel)return;
    const keepC=s.sig0?csel.value:YSF_DEFAULT_CC;
    s.sig0=true;
    const cs=Array.isArray(d.countries)?d.countries:[];
    csel.innerHTML=`<option value="*">All countries (${s.total.toLocaleString()})</option>`+
      cs.map(c=>`<option value="${esc(c[0])}">${esc(c[0]||'Other')} (${Number(c[1]).toLocaleString()})</option>`).join('');
    if(keepC&&[...csel.options].some(o=>o.value===keepC))csel.value=keepC;
  },
  lh:r=>lcHostUrl(r[3]),
  connect:(k,r)=>{
    const tg=ysfTuneValue(r),label=r[0]+' '+r[1];
    if(curTg&&curTg.mode==='YSF'&&String(curTg.tg).toLowerCase()===tg.toLowerCase()){
      toast('Already tuned to '+label,'ok');return;
    }
    tuneTG('YSF',tg,label);
  },
  save:(k,r)=>({action:'save-ysf-favorite',ref:ysfTuneValue(r)}),
});

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
    DVS_MODE_TUNE_MS
  );}finally{undimGrid('DSTAR');}
}
async function xlxConnect(name,base,module){
  if(busy)return;
  dimGrid('XLX');
  try{await apiAction(
    {action:'xlx-connect',name,base,module},
    `Connecting ${base}${module}L…`,
    d=>{curTg={mode:'XLX',tg:base+module+'L'};_curTgPerMode['XLX']=curTg;toast(d.message,'ok','xlx');renderXlxGrid(_lastXlxRefs,curTg.tg);setIndicator(curTg.tg,'XLX',false,base+' Mod-'+module);},
    DVS_MODE_TUNE_MS
  );}finally{undimGrid('XLX');}
}
async function m17Connect(name,base,ip,module){
  if(busy)return;
  dimGrid('M17');
  try{await apiAction(
    {action:'m17-connect',name,base,ip,module},
    `Connecting ${base} Mod-${module}…`,
    d=>{curTg={mode:'M17',tg:base+'|'+module};_curTgPerMode['M17']=curTg;toast(d.message,'ok','m17');renderM17Grid(_lastM17Refs,curTg.tg);setIndicator(curTg.tg,'M17',false,base+' Mod-'+module);},
    DVS_MODE_TUNE_MS
  );}finally{undimGrid('M17');}
}
async function doAslDiscCurrent(){
  await apiAction(
    {action:'asl-disc-current'},
    'Disconnecting all…',
    ()=>{curTg=null;setIndicator(null,'ASL',false);renderASLGrid(_lastAslNodes,null);showReady('ASL DISCONNECTED');},  // A5 writer 6/7 — see applyGridState comment
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
    45000
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
    DVS_MODE_TUNE_MS
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
    DVS_MODE_TUNE_MS
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
    30000
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
    if(mode!==curPage&&!inEdit){
      curTg=null; // null immediately so stale duplicate-tune guard can't fire
      dimGrid(curPage);
      showWorking(`Switching to ${mode}…`);
      try{
        setIndicator(null,curPage,false);
        const sw=await api({action:'switch-tab',page:mode},LINK_SWITCH_MS);
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
      const d=await api({action:'tune',mode,tg,name},DVS_MODE_TUNE_MS);
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
/* v8.9.6: DMR quick-bar Save.  Saves the number in the box, or, when the box
   is empty (Tune clears it), the last talkgroup tuned from the box on the
   network now picked in the dropdown.  The server (action_save_dmr_favorite)
   files it in that network's own 10 slots. */
let _dmrQtLast=null;   // {net,tg}: last talkgroup tuned from the DMR box
let _dmrSaving=false;
function dmrSaveNet(){const sel=byId('dmr-srv-select');return sel?sel.value:'';}
function dmrSavePick(){
  const inp=byId('qt-DMR');
  const v=inp?inp.value.trim():'';
  if(v)return v;
  const net=dmrSaveNet();
  return(_dmrQtLast&&net&&_dmrQtLast.net===net)?_dmrQtLast.tg:'';
}
function dmrSaveSync(){
  const b=byId('dmr-save-btn');
  if(b)b.disabled=_dmrSaving||!dmrSaveNet()||!dmrSavePick();
}
async function dmrQuickSave(){
  if(_dmrSaving)return;
  const net=dmrSaveNet();
  const tg=dmrSavePick();
  if(!net||!tg){dmrSaveSync();return;}
  if(!/^\d{1,8}$/.test(tg)){toast('DMR talkgroup must be a number (up to 8 digits)','err');return;}
  _dmrSaving=true;dmrSaveSync();
  try{
    const d=await api({action:'save-dmr-favorite',network:net,tg},10000);
    if(d.ok){
      toast(d.message,/already in favorites/.test(d.message)?'info':'ok');
      await loadTgData();
    }else{
      toast(d.message||'Could not save the favorite','err');
    }
  }finally{_dmrSaving=false;dmrSaveSync();}
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
      if(mode==='DMR'&&/^\d{1,8}$/.test(tg))_dmrQtLast={net:dmrSaveNet(),tg};   // v8.9.6
      if(inp)inp.value='';
      if(mode==='DMR')dmrSaveSync();
      setIndicator(tg,mode,false,tg);
      _pendingTune={tg,mode,name:tg,at:Date.now()};
      pollAbInfo();
    },
    DVS_MODE_TUNE_MS
  );}finally{undimGrid(mode);}
}
async function aslConnect(node,name){
  if(busy)return;
  dimGrid('ASL');
  try{await apiAction(
    {action:'asl-connect',node,name},
    `Connecting ${name}…`,
    d=>{curTg={mode:'ASL',tg:node};setIndicator(node,'ASL',false);renderASLGrid(_lastAslNodes,node);showReady(`ASL READY — ${name}`);},  // A5 writer 4/7 (optimistic render) — see applyGridState comment
    30000
  );}finally{undimGrid('ASL');}
}
/* v9.3.61: shared node directory card (ASL v9.3.61, Echo v9.3.62).
   Searches a node list on the server (/api/<kind>-directory?q=) because the
   lists are too big to send to a phone.  The menu fills after 2 or more
   characters, up to 200 matches.  Connect goes through the same call a
   favorite row makes.  Save (card or quick bar) goes to the tab's
   save-*-favorite action.  One "saving" flag per tab is shared by the card
   and quick-bar Save buttons so the two can't run at once.
   ASL: /var/lib/asterisk/astdb.txt, LH opens the node's AllStar stats page.
   ECHO: chan_echolink's "echolink dbdump" (stations logged in right now),
   LH opens EchoLink's logins page (it has no page per node). */
const NDC_TTL_MS=300000;
const NDC={
  ASL:{card:'asl-card',msg:'asl-card-msg',filter:'asl-filter',sel:'asl-ref-select',
    connectBtn:'asl-connect-btn',saveBtn:'asl-save-btn',lhBtn:'lh-btn-ASLNODE',
    qtInput:'cbn-input',qtBtn:'asl-qt-save-btn',
    api:'/api/asl-directory',saveAction:'save-asl-favorite',favApi:'/api/asl-nodes',
    favsLoaded:n=>{_lastAslNodes=n;renderASLGrid(_lastAslNodes,_lastLinkedNode);},
    connect:(node,name)=>aslConnect(node,name),
    lhUrl:r=>'https://stats.allstarlink.org/stats/'+encodeURIComponent(r[0]),
    optText:m=>[m[0],m[1],m[3]||m[2]||''].filter(Boolean).join(' · '),
    noListOpt:'No node list',selectOpt:'Select node…',
    listErr:'Could not check the AllStar node list. Reopen this tab to try again.',
    emptyMsg:'The AllStar node list is empty. Run: sudo asl3-update-astdb',
    missingMsg:'AllStar node list not found. Turn on asl3-update-astdb.',
    missingRetryMs:0,
    foundMsg:(d,total)=>total.toLocaleString()+' nodes listed'+
      (d.mtime?', dated '+new Date(d.mtime*1000).toLocaleDateString():''),
    noMatch:q=>'No nodes match "'+q+'".',
    searchErr:'Could not search the node list. Try again.',
    qtBad:'ASL node must be a number (up to 7 digits)'},
  ECHO:{card:'echo-card',msg:'echo-card-msg',filter:'echo-filter',sel:'echo-ref-select',
    connectBtn:'echo-connect-btn',saveBtn:'echo-save-btn',lhBtn:'lh-btn-ECHONODE',
    qtInput:'echo-input',qtBtn:'echo-qt-save-btn',
    api:'/api/echo-directory',saveAction:'save-echo-favorite',favApi:'/api/echo-nodes',
    favsLoaded:n=>{_lastEchoNodes=n;renderEchoGrid(_lastEchoNodes,_lastEchoFav);},
    connect:(node,name)=>echoConnect(node,name),
    lhUrl:r=>'https://www.echolink.org/logins.jsp',
    optText:m=>[m[0],m[1]].filter(Boolean).join(' · '),
    noListOpt:'No station list',selectOpt:'Select station…',
    listErr:'Could not check the EchoLink station list. Reopen this tab to try again.',
    emptyMsg:'The EchoLink station list is empty. EchoLink may still be logging in; reopen this tab in a few minutes.',
    missingMsg:'EchoLink station list not available. Is EchoLink turned on in Asterisk?',
    missingRetryMs:60000,
    foundMsg:(d,total)=>total.toLocaleString()+' stations logged in'+
      (d.mtime?' as of '+new Date(d.mtime*1000).toLocaleTimeString():''),
    noMatch:q=>'No logged-in stations match "'+q+'".',
    searchErr:'Could not search the station list. Try again.',
    qtBad:'EchoLink node numbers are 1–7 digits'},
};
const _ndc={};
Object.keys(NDC).forEach(k=>{_ndc[k]={timer:0,seq:0,rows:{},saving:false,found:false,checked:0,total:0,qtLast:''};});
function ndcMsg(k,text,kind){
  const el=byId(NDC[k].msg);
  if(!el)return;
  el.textContent=text||'';
  el.hidden=!text;
  el.className='tgc-card-msg'+(kind==='warn'?' warn':'');
}
function ndcSelected(k){
  const sel=byId(NDC[k].sel);
  const v=sel?sel.value:'';
  return v&&_ndc[k].rows[v]?_ndc[k].rows[v]:null;
}
function ndcButtons(k){
  const c=NDC[k],r=ndcSelected(k);
  const cb=byId(c.connectBtn),sv=byId(c.saveBtn),lh=byId(c.lhBtn);
  if(cb)cb.disabled=!r;
  if(sv)sv.disabled=!r||_ndc[k].saving;
  if(lh){lh.classList.toggle('lh-off',!r);lh.setAttribute('aria-disabled',r?'false':'true');}
}
async function ndcCardEnter(k){
  const c=NDC[k],st=_ndc[k];
  if(!byId(c.card))return;
  if(st.checked&&Date.now()-st.checked<NDC_TTL_MS)return;
  st.checked=Date.now();
  try{
    const r=await fetch(c.api+'?q=');
    if(!r.ok)throw new Error('HTTP '+r.status);
    const d=await r.json();
    if(!d||d.ok!==true)throw new Error('bad payload');
    ndcFound(k,d);
  }catch(e){
    st.checked=Date.now()-NDC_TTL_MS+5000;   // try again in 5 s
    ndcMsg(k,c.listErr,'warn');
  }
}
function ndcFound(k,d){
  const c=NDC[k],st=_ndc[k];
  const inp=byId(c.filter),sel=byId(c.sel);
  st.found=!!(d.found&&d.total);
  st.total=d.total||0;
  if(inp)inp.disabled=!st.found;
  if(!st.found){
    st.rows={};
    if(sel){sel.innerHTML='<option value="">'+c.noListOpt+'</option>';sel.disabled=true;}
    ndcMsg(k,d.found?c.emptyMsg:c.missingMsg,'warn');
    if(c.missingRetryMs)st.checked=Date.now()-NDC_TTL_MS+c.missingRetryMs;
    ndcButtons(k);
    return false;
  }
  if(!(inp&&inp.value.trim()))
    ndcMsg(k,c.foundMsg(d,st.total)+'. Type 2 or more characters to search.');
  return true;
}
function ndcSearchSoon(k){
  clearTimeout(_ndc[k].timer);
  _ndc[k].timer=setTimeout(()=>ndcSearch(k),300);
}
async function ndcSearch(k){
  const c=NDC[k],st=_ndc[k];
  const inp=byId(c.filter),sel=byId(c.sel);
  if(!inp||!sel)return;
  const q=inp.value.trim();
  const seq=++st.seq;
  if(q.length<2){
    st.rows={};
    sel.innerHTML='<option value="">Type to search…</option>';
    sel.disabled=true;
    ndcMsg(k,st.total?'Type 2 or more characters to search.':'');
    ndcButtons(k);
    return;
  }
  try{
    const r=await fetch(c.api+'?q='+encodeURIComponent(q));
    if(!r.ok)throw new Error('HTTP '+r.status);
    const d=await r.json();
    if(seq!==st.seq)return;   // a newer search is on its way
    if(!d||d.ok!==true||!Array.isArray(d.matches))throw new Error('bad payload');
    if(!ndcFound(k,d))return;
    const prev=sel.value;
    st.rows={};
    d.matches.forEach(m=>{st.rows[m[0]]=m;});
    if(!d.matches.length){
      sel.innerHTML='<option value="">No matches</option>';
      sel.disabled=true;
      ndcMsg(k,c.noMatch(q));
    }else{
      sel.innerHTML='<option value="">'+c.selectOpt+' ('+d.count.toLocaleString()+')</option>'+
        d.matches.map(m=>`<option value="${esc(m[0])}">${esc(c.optText(m))}</option>`).join('');
      sel.disabled=false;
      if(prev&&st.rows[prev])sel.value=prev;
      else if(d.matches.length===1)sel.value=d.matches[0][0];
      ndcMsg(k,d.count>d.matches.length
        ?'Showing '+d.matches.length+' of '+d.count.toLocaleString()+' matches. Type more to narrow it down.':'');
    }
  }catch(e){
    if(seq===st.seq)ndcMsg(k,c.searchErr,'warn');
  }
  ndcButtons(k);
}
function ndcConnect(k){
  const r=ndcSelected(k);
  if(!r)return;
  NDC[k].connect(r[0],[r[0],r[1]].filter(Boolean).join(' '));
}
function ndcLast(k){
  const r=ndcSelected(k);
  if(r)openLast(NDC[k].lhUrl(r));
}
async function ndcSaveNode(k,node){
  const c=NDC[k];
  const d=await api({action:c.saveAction,node},10000);
  if(d.ok){
    toast(d.message,/already in favorites/.test(d.message)?'info':'ok');
    try{
      const r=await fetch(c.favApi);
      if(r.ok){const n=await r.json();if(Array.isArray(n))c.favsLoaded(n);}
    }catch(_){}
  }else{
    toast(d.message||'Could not save the favorite','err');
  }
}
async function ndcSave(k){
  const r=ndcSelected(k),st=_ndc[k];
  if(!r||st.saving)return;
  st.saving=true;ndcButtons(k);ndcQtSync(k);
  try{await ndcSaveNode(k,r[0]);}finally{st.saving=false;ndcButtons(k);ndcQtSync(k);}
}
function ndcQtPick(k){
  const inp=byId(NDC[k].qtInput);
  const v=inp?inp.value.trim():'';
  return v||_ndc[k].qtLast;
}
function ndcQtSync(k){
  const b=byId(NDC[k].qtBtn);
  if(b)b.disabled=_ndc[k].saving||!ndcQtPick(k);
}
async function ndcQtSave(k){
  const st=_ndc[k];
  if(st.saving)return;
  const node=ndcQtPick(k);
  if(!node){ndcQtSync(k);return;}
  if(!/^\d{1,7}$/.test(node)){toast(NDC[k].qtBad,'err');return;}
  st.saving=true;ndcQtSync(k);ndcButtons(k);
  try{await ndcSaveNode(k,node);}finally{st.saving=false;ndcQtSync(k);ndcButtons(k);}
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
    d=>{if(/^\d{1,7}$/.test(node))_ndc.ASL.qtLast=node;if(inp)inp.value='';ndcQtSync('ASL');curTg={mode:'ASL',tg:node};setIndicator(node,'ASL',false);renderASLGrid(_lastAslNodes,node);showReady(`ASL READY — ${node}`);},  // v8.9.7 Save memory; A5 writer 5/7 (optimistic render) — see applyGridState comment
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
  if(!/^\d{1,7}$/.test(node)){toast('EchoLink node numbers are 1–7 digits','err');return}   // v9.3.56
  if(busy)return;
  dimGrid('ECHO');
  try{await apiAction(
    {action:'echo-connect-by-number',node},
    `Echo connecting ${node}…`,
    d=>{_ndc.ECHO.qtLast=node;if(inp)inp.value='';ndcQtSync('ECHO');_lastEchoFav=node;setIndicator(node,'ECHO',false);renderEchoGrid(_lastEchoNodes,node);showReady(`Echo READY — ${node}`);},  // v9.3.59 Save memory
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
    const d=await api({action:'switch-dmr-server',name},DVS_TUNE_MS);
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
    // Tab restore on reload. Two sources, checked in order:
    //  1. SysMon breadcrumb — one-shot, set right before following the SysMon
    //     link; restores the tab they left from when they hit Back.
    //  2. v8.3.9: general last-active-tab record (_saveTabState(), written on
    //     every real tab change). Covers every OTHER way this page reloads
    //     with connections still live server-side — most commonly a mobile
    //     browser discarding/reloading a backgrounded tab. Before this, only
    //     the SysMon round trip was remembered, so any other reload fell
    //     through to the hardcoded ASL default below even though the actual
    //     active tab (DMR/YSF/M17/etc.) was still connected.
    // Either way, skip all forced-page overrides (ASL default, DMR net-select).
    let _tabRestored=false;
    try{
      const _srRaw=sessionStorage.getItem('sysmonReturn');
      if(_srRaw){
        sessionStorage.removeItem('sysmonReturn');
        const _sr=JSON.parse(_srRaw);
        if(_sr.page&&PAGES.includes(_sr.page)){
          curPage=_sr.page;_tabRestored=true;
          fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'cpuweight-resume'})}).catch(()=>{});
        }
      }
    }catch(_){}
    if(!_tabRestored){
      try{
        const _lastTab=sessionStorage.getItem('dashLastTab');
        if(_lastTab&&PAGES.includes(_lastTab)){curPage=_lastTab;_tabRestored=true;}
      }catch(_){}
    }
    if(!_tabRestored){
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
  if(!inEdit&&!busy&&d.page!==curPage&&PAGES.includes(d.page)){curPage=d.page;syncPageDisplay();_saveTabState()}
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
  applyPhoneState(d.phone);   // v9.1.0
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
    // A5 (audit) — asl-grid is the one grid driven by link state rather than
    // curTg, so it has more repaint triggers than any other. RECOUNTED in
    // v8.3.6: there are SEVEN call sites, not the three this comment used to
    // claim, and four of them were untagged. All seven now carry an
    // "A5 writer n/7" marker, matching the discipline the _dmrNetSelectMode
    // D3 comment already keeps:
    //   1/7  here, applyGridState()   — status poll
    //   2/7  pollKeyed(), mode==='ASL' branch
    //   3/7  pollKeyed(), linked-node sync branch
    //   4/7  aslConnect()             — optimistic, pre-confirmation
    //   5/7  doConnectByNumber()      — optimistic, pre-confirmation
    //   6/7  doAslDiscCurrent()       — clears to null on disconnect
    //   7/7  loadTgData()             — boot draw
    // Not a bug — this is how foreign/perm-linked nodes get reflected on the
    // grid. But it does mean a change to renderASLGrid()'s signature or to
    // what _lastAslNodes holds has seven places to check, not three.
    renderASLGrid(_lastAslNodes,_lastLinkedNode);  // A5 writer 1/7
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
    fcsCardSync(d);   // v8.4.2: follow the tuned FCS room in the browse card
    Object.keys(LC_CFG).forEach(k=>lcCardSync(k,d));   // v9.0.2 browse-card engine: P25 / NXDN / STFU / XLX / D-STAR / YSF
    m17CardSync(d);   // v8.6.2: follow the connected M17 reflector in the browse card
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
    if(d.wifimon_shutdown&&d.wifimon_shutdown.active)showWfmShutdown(d.wifimon_shutdown);
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
    byId('cfg-cpuweight').checked=!!d.cpuweight_enabled;
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
  const cpuweight_enabled=byId('cfg-cpuweight').checked;
  const d=await api({action:'save-config',asl_node,bridge_node,bridge_nodes,port,callsign,enabled_tabs,cpuweight_enabled,mode_net_urls:modeNetUrls});
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
    renderASLGrid(_lastAslNodes,_lastLinkedNode);  // A5 writer 7/7 — boot draw; see applyGridState comment
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
// ── Phone tab (v9.1.0) ──────────────────────────────────────────────────────
// Laid out like the DMR tab: tapping the tab shows the network list first; the
// network menu, Dial box and 10 favorites follow.  Call state comes from the
// 'phone' block of /api/status (only filled while this tab is open).
let _pt={data:null,status:{configured:false},netSelect:true,loadedAt:0,loading:false,lastDialed:'',
  wasLive:false,flash:null};
let _ptToneChain=Promise.resolve();
function ptLive(){const c=(_pt.status||{}).call||{};return c.state==='in_call'}
// v9.2.4: tones go through one queue so quick presses arrive in order.
function ptSendTones(tones,label){
  _ptToneChain=_ptToneChain.then(async()=>{
    const d=await api({action:'phone-tones',tones},20000);
    if(d.ok){_pt.flash={t:'Sent '+(label||tones),until:Date.now()+2500};ptRenderStatus();setTimeout(ptRenderStatus,2600)}
    else toast(d.message,'err');
  }).catch(()=>{});
  return _ptToneChain;
}
function ptActiveNet(){const d=_pt.data;return d?((d.networks||[]).find(n=>n.id===d.active)||null):null}
async function ptLoad(force){
  if(_pt.loading)return;
  if(!force&&_pt.data&&Date.now()-_pt.loadedAt<2000)return;
  _pt.loading=true;
  try{_pt.data=await(await fetch('/api/phone')).json();_pt.loadedAt=Date.now()}catch(_){}
  finally{_pt.loading=false}
  ptRender();
}
function ptEnter(){ptRender();ptLoad(false)}
function ptDigits(){return byId('pt-dial').value.replace(/[^0-9]/g,'')}
// v9.3.33: Save needs a picked network (favorites belong to it)
function ptDialSync(){const b=byId('pt-save-btn');if(b)b.disabled=ptDigits().length<3||!ptActiveNet()}
function ptRender(){
  const d=_pt.data,sel=byId('pt-net-select'),grid=byId('pt-grid');
  if(!sel||!grid)return;
  const nets=(d&&d.networks)||[];
  const sig=nets.map(n=>n.id+'='+n.name).join('|')+'#'+(d?d.active:'');
  if(sel.dataset.sig!==sig){
    sel.dataset.sig=sig;
    sel.innerHTML=nets.length?nets.map(n=>`<option value="${esc(n.id)}">${esc(n.name)}</option>`).join(''):'<option value="">No networks</option>';
    if(d&&d.active)sel.value=d.active;
  }
  sel.disabled=busy||!nets.length;
  ptDialSync();
  ptRenderStatus();
  if(!d){grid.innerHTML='<div style="padding:1rem;color:var(--muted);font-family:var(--mono);font-size:.858rem">Loading…</div>';return}
  if(!nets.length){
    grid.innerHTML='<div style="padding:1rem;color:var(--muted);font-family:var(--mono);font-size:.858rem">No phone networks yet — add one on the Edit page</div>';
    return;
  }
  const off=d.activated===false;   // v9.3.48
  ['pt-dial','pt-dial-btn'].forEach(id=>{const b=byId(id);if(b)b.disabled=off});
  if(off){
    grid.innerHTML='<div style="padding:1rem;color:var(--muted);font-family:var(--mono);font-size:.858rem">The phone is off. Turn it on with the Activate switch on the Edit page (Phone).</div>';
    return;
  }
  if(_pt.netSelect){
    let n=0;
    grid.innerHTML='<div class="net-sel-hdr">Select Network</div>'+nets.map(x=>{
      n++;const act=x.id===d.active;
      return `<div class="row-grid${act?' active-phone':''}" data-role="pt-net-row" data-id="${esc(x.id)}" title="${esc(x.name)}">`+
        `<span class="row-num">${n}</span><div class="dot ${act?'dot-on':'dot-off'}"></div>`+
        `<span class="row-name">${esc(x.name)} · ${esc(x.type_label||'')}${x.node?' · node '+esc(x.node):''}</span></div>`;
    }).join('');
    return;
  }
  let n=0;
  const an=ptActiveNet();
  const vm=(an&&PH_EXT_TYPES.includes(an.type)&&an.voicemail_access)?`<div class="row-grid" data-role="pt-vm-row" title="Voicemail ${esc(an.voicemail_access)}">`+
    `<span class="row-num">VM</span><div class="dot dot-off"></div><span class="row-name">Voicemail · ${esc(an.voicemail_access)}`+
    // v9.3.52: send the saved voicemail PIN (then #) once voicemail asks for it
    ` <button type="button" class="btn btn-teal pt-vm-pin" data-role="pt-vm-pin" title="${an.has_voicemail_pin?'Send your saved voicemail PIN, then #':'No voicemail PIN saved — add it on the Edit page'}">Pin</button></span></div>`:'';
  const tc=(an&&an.test_number)?`<div class="row-grid" data-role="pt-test-row" title="Test call ${esc(an.test_number)}">`+
    `<span class="row-num">T</span><div class="dot dot-off"></div><span class="row-name">Test call · ${esc(an.test_number)}</span></div>`:'';
  // v9.3.32: the picked network's own favorites
  const rows=((an&&an.favorites)||[]).map(f=>{
    if(!f.number)return '';
    n++;
    return `<div class="row-grid" data-role="pt-fav-row" data-num="${esc(f.number)}" title="${esc(f.number)}">`+
      `<span class="row-num">${n}</span><div class="dot dot-off"></div>`+
      `<span class="row-name">${esc(f.name||f.number)}${f.name&&f.name!==f.number?' · '+esc(f.number):''}</span></div>`;
  }).join('');
  const empty=an?`No favorites on ${esc(an.name)} yet — dial a number and press Save`:'Pick a network first';
  grid.innerHTML=(rows||vm||tc)?('<div class="net-sel-hdr">Favorites'+(an?' · '+esc(an.name):'')+'</div>'+tc+vm+rows):'<div style="padding:1rem;color:var(--muted);font-family:var(--mono);font-size:.858rem">'+empty+'</div>';
}
function ptRenderStatus(){
  const st=_pt.status||{},d=_pt.data,net=ptActiveNet();
  // v9.3.21: HOIP AllStar Link callers (incoming over IAX2)
  const hl=st.hoip_link||{},hlr=byId('pt-hl');
  if(hlr){
    const on=!!(hl.on&&hl.callers>0);
    hlr.classList.toggle('pt-hide',!on);
    if(on)byId('pt-hl-txt').textContent='HOIP AllStar caller on node '+hl.node+(hl.who?' — '+hl.who:'')+(hl.callers>1?' (+'+(hl.callers-1)+' more)':'')+' · *99 talk, # stop';
  }
  const dot=byId('pt-reg-dot'),call=byId('pt-call'),pb=byId('pt-patch-btn');
  if(!dot||!call||!pb)return;
  const reg=(st.reg&&net)?st.reg[net.id]:undefined;
  dot.classList.toggle('pt-hide',reg===undefined||reg===null);
  dot.className='dot '+(reg?'dot-on':'dot-off')+((reg===undefined||reg===null)?' pt-hide':'');
  dot.title=reg?'Signed in':'Not signed in';
  // v9.3.26: sign-in progress for the picked network
  const si=st.signin||{},sl=byId('pt-signin');
  if(sl){
    const show=net&&si.id===net.id&&(si.state==='signing'||si.state==='failed');
    sl.classList.toggle('pt-hide',!show);
    sl.textContent=si.state==='signing'?'Signing in…':(si.state==='failed'?'Sign-in failed':'');
    sl.title=si.error||'';
    sl.className='pt-signin'+(show?'':' pt-hide')+(si.state==='failed'?' pt-signin-bad':'');
    if(si.state==='signing')dot.title='Signing in…';
  }
  // v9.3.28: transmitter time-out state while on the Phone tab
  const tt=st.tot||{},tl=byId('pt-tot');
  if(tl){
    const show=!!(tt.off||tt.error||tt.capped);
    tl.className='pt-signin'+(show?'':' pt-hide')+((tt.error||tt.capped)?' pt-signin-bad':'');
    tl.textContent=tt.capped?'Time-out back on (safety cap)':(tt.error?'Time-out: not switched':(tt.off?'Time-out: off for calls':''));
    tl.title=tt.error||(tt.capped?'The radio stayed keyed past the safety cap, so the time-out was turned back on':'The transmitter time-out is off while this tab is open and back on when you leave');
  }
  const patchOn=st.configured?st.patch!==false:(d?d.patch_enabled!==false:true);
  pb.textContent='Patch: '+(patchOn?'On':'Off');
  pb.className='btn '+(patchOn?'btn-muted':'btn-red');
  const c=st.call||{state:'idle'};
  let txt='',cls='pt-call';
  if(st.configured&&st.activated===false){txt='The phone is off — turn it on with Activate on the Edit page';cls+=' pt-warn'}   // v9.3.48
  else if(!patchOn){txt='Phone patch is off — dialing is blocked';cls+=' pt-warn'}
  else if(c.state==='dialing'){txt='Dialing '+(_pt.lastDialed||'')+'…';cls+=' pt-live'}
  else if(c.state==='incoming'){txt='Incoming call'+(c.who?' from '+c.who:'')+((net&&net.incoming==='open')?' — connecting':' — waiting for PIN');cls+=' pt-live'}
  else if(c.state==='in_call'){
    // v9.3.8: your radio audio only goes to the call while you're keyed
    txt='In call'+(c.who?' — '+c.who:((c.number||_pt.lastDialed)?' — '+(c.number||_pt.lastDialed):''))+(_lastKeyed?' · Talking':' · Listening');
    cls+=' pt-live'+(_lastKeyed?' pt-talk':'');
  }
  // v9.3.46: each network has its own node; say so while it links
  else if(net&&st.node&&st.node_linked===false){txt='Linking node '+st.node+' for '+net.name+'…';cls+=' pt-warn'}
  else if(net&&reg===false){txt='Not signed in to '+net.name;cls+=' pt-warn'}
  else txt=net?('Ready · '+net.name+(st.node?' · node '+st.node:'')):'';
  if(_pt.flash&&Date.now()<_pt.flash.until){txt=_pt.flash.t;cls='pt-call pt-live'}
  else if(st.notice){txt=st.notice;cls='pt-call '+(st.notice.indexOf('Sent')===0?'pt-live':'pt-warn')}
  call.className=cls;call.textContent=txt;
  const live=c.state==='in_call';
  ['pt-t99','pt-thash','pt-kp-btn'].forEach(id=>{const b=byId(id);if(b)b.disabled=!live});
  // v9.2.7: the network's own tone buttons, rebuilt only when they change.
  const cb=byId('pt-cbtns');
  if(cb){
    const bs=(net&&net.buttons)||[],bsig=(net?net.id:'')+'|'+JSON.stringify(bs);
    if(cb.dataset.sig!==bsig){
      cb.dataset.sig=bsig;
      cb.innerHTML=bs.map(b=>`<button class="btn btn-teal" data-tones="${esc(b.tones)}" data-label="${esc(b.label)}" title="Send ${esc(b.tones)}">${esc(b.label)}</button>`).join('');
    }
    cb.querySelectorAll('button').forEach(b=>{b.disabled=!live});
  }
  if(!live)ptKeypadClose();
  ptToneModeRender(live?(st.tone||{}):{});
  ptTonePathRender(st.tone_path||'provider');
  const db=byId('pt-dial-btn');if(db)db.textContent=live?'Send':'Dial';
  const inp=byId('pt-dial');
  if(inp){
    inp.placeholder=live?'Tones to send…':'Number to dial…';
    if(live&&!_pt.wasLive&&inp.value.replace(/\D/g,'')===_pt.lastDialed){inp.value='';ptDialSync()}
  }
  _pt.wasLive=live;
}
function applyPhoneState(p){
  _pt.status=p||{configured:false};
  ptRenderStatus();
  if(curPage!=='PHONE'||inEdit)return;
  const c=_pt.status.call||{state:'idle'};
  if(c.state==='idle'){
    if(curTg&&curTg.mode==='PHONE'){curTg=null;setIndicator(null,'PHONE',false)}
  }else{
    // v9.3.4: the badge shows the number (caller ID on an incoming call),
    // with the favorite's name as its tooltip.
    const label=c.who||c.number||_pt.lastDialed||'call';
    // v9.3.32: the picked network's favorites first, then the others
    const an=ptActiveNet(),nets=(_pt.data&&_pt.data.networks)||[];
    const pool=((an&&an.favorites)||[]).concat(...nets.filter(n=>n!==an).map(n=>n.favorites||[]));
    const fav=pool.find(f=>f.number&&f.number===label);
    curTg={mode:'PHONE',tg:label};setIndicator(label,'PHONE',_lastKeyed,fav&&fav.name?fav.name:'');
  }
}
async function ptChooseNet(id){
  const d=await api({action:'phone-select',network:id});
  if(!d.ok){toast(d.message,'err');return}
  _pt.netSelect=false;
  if(_pt.data)_pt.data.active=id;
  _pt.loadedAt=0;ptRender();ptLoad(true);
}
async function ptSwitchNet(id){
  if(!id)return;
  const d=await api({action:'phone-select',network:id});
  if(!d.ok){toast(d.message,'err');ptLoad(true);return}
  if(_pt.data)_pt.data.active=id;
  ptRender();
}
async function ptDialNumber(num){
  _pt.lastDialed=num;
  const d=await api({action:'phone-dial',number:num},15000);
  toast(d.message,d.ok?'ok':'err');
  if(d.ok){byId('pt-dial').value=num;ptDialSync();setTimeout(refresh,700)}
}
async function ptVoicemail(){
  _pt.lastDialed='voicemail';
  const d=await api({action:'phone-voicemail'},15000);
  toast(d.message,d.ok?'ok':'err');
  if(d.ok)setTimeout(refresh,700);
}
async function ptVmPin(){
  const d=await api({action:'phone-vm-pin'},20000);
  toast(d.message,d.ok?'ok':'err');
}
async function ptTestCall(){
  _pt.lastDialed='TEST';
  const d=await api({action:'phone-test'},15000);
  toast(d.message,d.ok?'ok':'err');
  if(d.ok)setTimeout(refresh,700);
}
async function ptDial(){
  const raw=byId('pt-dial').value.replace(/[\s\-]/g,'');
  if(ptLive()){
    const t=raw.replace(/[^0-9*#,]/g,'');
    if(!t){toast('Type the tones to send','err');return}
    await ptSendTones(t);byId('pt-dial').value='';ptDialSync();return;
  }
  if(/[*#]/.test(raw)){
    const an=ptActiveNet();
    if(an&&an.voicemail_access&&raw===an.voicemail_access){await ptVoicemail();return}
    toast('Codes with * or # are sent during a call — dial the number first','err');return;
  }
  const num=ptDigits();
  if(!num){toast('Type a number to dial','err');return}
  await ptDialNumber(num);
}
(function(){
  const cb=byId('pt-cbtns');
  if(cb)cb.addEventListener('click',e=>{const b=e.target.closest('[data-tones]');if(b&&!b.disabled)ptSendTones(b.dataset.tones,b.dataset.label)});
})();
// v9.2.5: pop-up keypad — each key goes out as soon as it's pressed.
function ptKeypadOpen(){
  if(!ptLive())return;
  byId('pt-kp-sent').textContent='';
  byId('pt-kp-audio').textContent='';
  byId('pt-kp-overlay').classList.add('open');
  ptAudioStop();ptAudioPoll();_ptAudioTimer=setInterval(ptAudioPoll,3000);
  byId('pt-kp-x').focus();
}
function ptKeypadClose(){const o=byId('pt-kp-overlay');if(o)o.classList.remove('open');ptAudioStop()}
// v9.3.9: call check under the keypad, every 3 seconds while it's open.
let _ptAudioTimer=null;
function ptAudioStop(){if(_ptAudioTimer){clearInterval(_ptAudioTimer);_ptAudioTimer=null}}
async function ptAudioPoll(){
  const el=byId('pt-kp-audio');if(!el)return;
  let d;try{d=await(await fetch('/api/phone-callcheck')).json()}catch(_){return}
  if(!d.live){el.textContent='';return}
  if(!d.sip){el.textContent='Call check: not available for IAX2';return}
  const s=d.stats;
  if(!s){el.textContent='Call check: no audio numbers yet';return}
  let h=`Audio in <span class="ok">${s.in}</span> · out <span class="ok">${s.out}</span> · lost ${s.in_lost}/${s.out_lost}`;
  // v9.3.10: the far end reports back on what it got from us
  h+=s.confirmed?` · far end confirming <span class="ok">yes</span>`:' · far end confirming: not yet';
  if(s.secs>=5&&s.out===0)h+=`<span class="warn">Nothing is leaving the Pi — Asterisk isn't sending audio to this call</span>`;
  else if(s.secs>=5&&s.in===0)h+=`<span class="warn">Nothing is arriving — check the router note on the Edit page</span>`;
  el.innerHTML=h;
  el.title=s.confirmed?'The far end is confirming it gets packets from the Pi, so the router is not blocking you.':s.out>0?'Audio is leaving the Pi. If they still can\'t hear you, check the router note on the Edit page.':'';
}
// v9.3.3: tone mode for the live call (SIP only), shown under the keypad.
let _ptModeBusy=false;
function ptToneModeLbl(m){const x=PH_TONE_MODES.find(p=>p[0]===m);return x?x[1].replace(' (recommended)',''):''}
function ptToneModeRender(t){
  const box=byId('pt-kp-mode'),sel=byId('pt-kp-mode-sel'),keep=byId('pt-kp-keep'),note=byId('pt-kp-mode-note');
  if(!box||!sel)return;
  box.classList.toggle('pt-hide',!t.sip);
  if(!t.sip)return;
  if(!sel.options.length)sel.innerHTML=(t.mode?'':'<option value="">Unknown</option>')+phOpts(PH_TONE_MODES,t.mode||'');
  if(t.mode&&sel.querySelector('option[value=""]'))sel.innerHTML=phOpts(PH_TONE_MODES,t.mode);
  if(!_ptModeBusy&&document.activeElement!==sel&&t.mode)sel.value=t.mode;
  sel.disabled=_ptModeBusy;
  keep.disabled=_ptModeBusy||!t.mode||t.mode===t.saved;
  note.textContent=t.net?('Saved for '+t.net+': '+(ptToneModeLbl(t.saved)||'Automatic')):'';
}
// v9.3.15: which way keypad tones go into the call (saved as you pick).
let _ptPathBusy=false;
function ptTonePathRender(p){
  const sel=byId('pt-kp-path-sel');if(!sel)return;
  if(!sel.options.length)sel.innerHTML=phOpts(PH_TONE_PATHS,p);
  if(!_ptPathBusy&&document.activeElement!==sel)sel.value=p;
  sel.disabled=_ptPathBusy;
}
async function ptTonePathSet(p){
  if(!p||_ptPathBusy)return;
  _ptPathBusy=true;ptTonePathRender(p);
  try{
    const d=await api({action:'phone-tone-path',path:p},10000);
    toast(d.message,d.ok?'ok':'err');
    if(d.ok&&_pt.status)_pt.status.tone_path=p;
  }finally{_ptPathBusy=false;ptRenderStatus()}
}
async function ptToneModeSet(m){
  if(!m||_ptModeBusy)return;
  _ptModeBusy=true;ptRenderStatus();
  try{
    const d=await api({action:'phone-tone-mode',mode:m},10000);
    toast(d.message,d.ok?'ok':'err');
    if(d.ok&&_pt.status&&_pt.status.tone)_pt.status.tone.mode=m;
  }finally{_ptModeBusy=false;ptRenderStatus()}
}
async function ptToneModeKeep(){
  if(_ptModeBusy)return;
  _ptModeBusy=true;ptRenderStatus();
  try{
    const d=await api({action:'phone-tone-keep'},60000);
    toast(d.message,d.ok?'ok':'err');
    if(d.ok&&_pt.status&&_pt.status.tone)_pt.status.tone.saved=_pt.status.tone.mode;
    if(d.ok){_pt.loadedAt=0;ptLoad(true)}
  }finally{_ptModeBusy=false;ptRenderStatus()}
}
function ptKeypadKey(k){
  const sh=byId('pt-kp-sent');
  sh.textContent=(sh.textContent+k).slice(-16);
  ptSendTones(k);
}
(function(){
  const g=byId('pt-kp-grid');
  if(g)g.addEventListener('click',e=>{const b=e.target.closest('[data-key]');if(b)ptKeypadKey(b.dataset.key)});
  const o=byId('pt-kp-overlay');
  if(o)o.addEventListener('click',e=>{if(e.target===o)ptKeypadClose()});
  document.addEventListener('keydown',e=>{
    if(!o||!o.classList.contains('open'))return;
    if(e.key==='Escape'){ptKeypadClose();return}
    if(/^[0-9*#]$/.test(e.key)){e.preventDefault();ptKeypadKey(e.key)}
  });
})();
// v9.3.7: report pop-up.  Plain http:// pages can't use the clipboard API,
// so Copy falls back to selecting the text and the browser's copy command.
async function ptReportOpen(){
  const o=byId('pt-rep-overlay'),t=byId('pt-rep-text');
  t.value='Gathering…';o.classList.add('open');
  try{const d=await(await fetch('/api/phone-report')).json();t.value=d.text||'No report'}
  catch(_){t.value='Could not reach the dashboard'}
}
function ptReportClose(){byId('pt-rep-overlay').classList.remove('open')}
async function ptReportCopy(){
  const t=byId('pt-rep-text');
  try{
    if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(t.value);toast('Report copied','ok');return}
  }catch(_){}
  t.focus();t.select();
  let ok=false;try{ok=document.execCommand('copy')}catch(_){}
  toast(ok?'Report copied':'Text is selected — press Ctrl+C (or long-press → Copy)',ok?'ok':'err');
}
(function(){
  const o=byId('pt-rep-overlay');
  if(o)o.addEventListener('click',e=>{if(e.target===o)ptReportClose()});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&o&&o.classList.contains('open'))ptReportClose()});
})();
async function ptHangup(){
  const d=await api({action:'phone-hangup'});
  toast(d.message,d.ok?'ok':'err');setTimeout(refresh,500);
}
async function ptPatchToggle(){
  const st=_pt.status||{};
  const now=st.configured?st.patch!==false:true;
  const d=await api({action:'phone-patch',on:!now});
  toast(d.message,d.ok?'ok':'err');
  if(d.ok){_pt.status=Object.assign({},st,{configured:true,patch:!now});ptRenderStatus();_pt.loadedAt=0;setTimeout(refresh,400)}
}
async function ptQuickSave(){
  const num=ptDigits();
  if(num.length<3){toast('Type a number to save','err');return}
  if(!ptActiveNet()){toast('Pick a phone network first','err');return}
  const d=await api({action:'save-phone-favorite',number:num});
  toast(d.message,d.ok?'ok':'err');
  if(d.ok)ptLoad(true);
}
(function(){
  const g=byId('pt-grid');
  if(g)g.addEventListener('click',e=>{
    const r=e.target.closest('[data-role]');if(!r)return;
    if(r.dataset.role==='pt-vm-pin'){e.stopPropagation();ptVmPin();return}   // v9.3.52
    if(r.dataset.role==='pt-net-row')ptChooseNet(r.dataset.id);
    else if(r.dataset.role==='pt-fav-row')ptDialNumber(r.dataset.num);
    else if(r.dataset.role==='pt-vm-row')ptVoicemail();
    else if(r.dataset.role==='pt-test-row')ptTestCall();
  });
})();
// ── Phone editor (Edit tab, v9.0.9) ─────────────────────────────────────────
// State lives in _ph while the Edit page is open.  Passwords and PINs are never
// sent to the browser; a blank box on save means "keep the one on file".
let _ph={loaded:false,dirty:false,nets:[],active:'',max:6,router:{}};
const PH_TYPES=[['iax2','IAX2 (login)'],['sip','SIP with login'],['sip_ip','SIP by IP address'],['hoip','Hams Over IP'],['awire','AmateurWire']];
// v9.3.53: ham PBX services with an extension and voicemail share one card
const PH_EXT_TYPES=['hoip','awire'];
const PH_EXT_DEF={hoip:{name:'Hams Over IP',host:'premium.hamsoverip.com',port:'5160'},
                  awire:{name:'AmateurWire',host:'pbx1-wv.amateurwire.org',port:'5060'}};
// v9.3.54: HOIP wants RFC 2833 tone packets with ulaw; 3191 reads your tones back
const PH_HOIP_TONE='rfc4733',PH_HOIP_TONE_TEST='3191';
// v9.3.2: how keypad tones travel on a SIP network (IAX2 has no setting).
const PH_TONE_PATHS=[['provider','Straight to the provider (v9.3.13 way)'],['node','Through the call (test)'],['sound','As sound (tone recordings)']];
const PH_TONE_MODES=[['auto','Automatic (recommended)'],['rfc4733','Tone packets only (RFC 2833)'],['inband','Real tones in the audio'],['info','SIP messages'],['auto_info','Packets, then SIP messages']];
const PH_BLANK_NET={id:'',name:'',type:'iax2',host:'',port:'',username:'',password:'',caller_id:'',
  dialing:'phone',dial_format:'10',e911:false,allow_intl:false,register:true,incoming:'off',pin:'',
  trusted:'',did:'',lan_net:'',wan_ip:'',has_password:false,has_pin:false,
  callsign:'',email:'',extension:'',transport:'udp',auth_id:'',voicemail:'',voicemail_pin:'',display_name:'',dmr_id:'',
  voicemail_access:'',login_url:'',has_voicemail_pin:false,tone_mode:'auto',test_number:'',node:''};
// v9.2.6: the five tone buttons are edited as flat btn_label_N / btn_tones_N
// fields and sent back as a 'buttons' list.
const PH_TONE_BTNS=5;
function phBtnFlat(bs){const o={};for(let k=0;k<PH_TONE_BTNS;k++){const b=(bs||[])[k]||{};o['btn_label_'+k]=b.label||'';o['btn_tones_'+k]=b.tones||''}return o}
function phBtnList(n){const a=[];for(let k=0;k<PH_TONE_BTNS;k++)a.push({label:n['btn_label_'+k]||'',tones:n['btn_tones_'+k]||''});return a}
Object.assign(PH_BLANK_NET,phBtnFlat([]));
function phOpts(list,cur){return list.map(([v,l])=>`<option value="${esc(v)}"${v===cur?' selected':''}>${esc(l)}</option>`).join('')}
function phField(i,k,label,val,extra){
  extra=extra||{};
  return `<div class="cfg-field${extra.auto?' ph-auto-on':''}"><label class="cfg-lbl">${esc(label)}<span class="ph-auto-tag" title="Filled in for you — type over it to change it">auto</span></label>`+
    `<input class="cfg-inp" data-k="${k}" type="${extra.type||'text'}" value="${esc(val==null?'':val)}"`+
    ` placeholder="${esc(extra.ph||'')}" maxlength="${extra.max||64}" autocomplete="off"${extra.num?' inputmode="numeric"':''}></div>`;
}
function phChk(k,label,on){
  return `<div class="cfg-field"><label class="tab-chk-lbl"><input type="checkbox" data-k="${k}"${on?' checked':''}>${esc(label)}</label></div>`;
}
// v9.3.34: each network's own 10 favorites, edited in its card (n.favs).
// The section starts hidden; n._favOpen remembers Show while the page is open.
function phFavsIn(list){
  const a=(list||[]).map(f=>({name:f.name||'',number:f.number||'',tones:'',has_tones:!!f.has_tones,tones_clear:false}));
  while(a.length<10)a.push({name:'',number:'',tones:'',has_tones:false,tones_clear:false});
  return a.slice(0,10);
}
function phFavsOut(favs){return (favs||[]).map(f=>({name:f.name||'',number:f.number||'',tones:f.tones||'',tones_clear:!!f.tones_clear}))}
function phFavBlock(n,i){
  const favs=n.favs||phFavsIn([]),open=!!n._favOpen,used=favs.filter(f=>String(f.number||'').trim()).length;
  let h=`<div class="ed-sec-hdr ph-fav-hdr" style="padding-left:0"><span>Favorites (${used} of 10)</span>`+
    `<button type="button" data-ftog="${i}">${open?'Hide':'Show'}</button></div>`;
  h+=`<div class="ph-fav-list"${open?'':' style="display:none"'}>`;
  h+=favs.map((f,j)=>
    `<div class="ph-fav-row" data-fi="${j}"><input class="cfg-inp" data-fk="name" type="text" maxlength="24" placeholder="${j+1}. Name" value="${esc(f.name)}">`+
    `<input class="cfg-inp" data-fk="number" type="text" inputmode="numeric" maxlength="20" placeholder="Number" value="${esc(f.number)}">`+
    `<input class="cfg-inp" data-fk="tones" type="password" inputmode="tel" maxlength="32" autocomplete="off" placeholder="${f.has_tones?'Then send: saved':'Then send'}" value="${esc(f.tones||'')}">`+
    (f.has_tones?`<button type="button" class="btn btn-muted ph-fav-clr" data-fclr="${j}" aria-label="Clear the saved tones for favorite ${j+1}" title="Clear the saved tones">✕</button>`:'<span></span>')+
    `</div>`).join('');
  h+=`<div class="ph-hint">These favorites show on the Phone tab while this network is picked. Then send: tones sent 1 second after the call answers, such as a PIN like 1234#. A comma waits 1 second. Saved tones are hidden; leave the box blank to keep them, or press ✕ to clear them.</div>`;
  return h+`</div>`;
}
function phRenderNet(n,i){
  const login=n.type!=='sip_ip', sip=n.type!=='iax2', phone=n.dialing==='phone', pin=n.incoming==='pin', opn=n.incoming==='open', hoip=PH_EXT_TYPES.includes(n.type), aw=n.type==='awire';
  let h=`<div class="ph-net" data-i="${i}"><div class="ph-net-hdr"><span>${i+1}. ${esc(n.name||'New network')}${n.node?' · node '+esc(n.node):''}</span>`+
    `<button class="btn btn-muted" onclick="phRemoveNet(${i})">Remove</button></div><div class="cfg-grid">`;
  const au=k=>!!(n._auto&&k in n._auto);   // v9.3.51
  h+=phField(i,'name','Name',n.name,{max:24,auto:au('name')});
  h+=`<div class="cfg-field"><label class="cfg-lbl">Type</label><select class="cfg-inp" data-k="type" onchange="phRerender()">${phOpts(PH_TYPES,n.type)}</select></div>`;
  // v9.3.46: the network's own private node (blank = the next free number)
  h+=phField(i,'node','Node number',n.node,{max:4,num:true,ph:'blank = next free'});
  if(hoip){
    const df=PH_EXT_DEF[n.type];
    if(aw){   // v9.3.53: AmateurWire
      h+=phField(i,'extension','Extension',n.extension,{max:10,num:true});
      h+=phField(i,'display_name','Display Name',n.display_name,{max:40,ph:'e.g. KD8PGK James',auto:au('display_name')});
      h+=phField(i,'dmr_id','DMR ID',n.dmr_id,{max:7,num:true,auto:au('dmr_id')});
    }else{
    h+=phField(i,'callsign','Callsign',n.callsign,{max:12,ph:'e.g. KD8PGK',auto:au('callsign')});
    h+=phField(i,'email','Email',n.email,{max:120,auto:au('email')});
    h+=phField(i,'extension','Extension',n.extension,{max:10,num:true});
    }
    h+=phField(i,'host',aw?'Server / Domain':'SIP Server / Proxy / Registrar',n.host,{max:120,ph:df.host,auto:au('host')});
    h+=phField(i,'port','SIP Port',n.port,{max:5,num:true,ph:df.port,auto:au('port')});
    h+=`<div class="cfg-field"><label class="cfg-lbl">Transport</label><select class="cfg-inp" data-k="transport">${phOpts([['udp','UDP']],'udp')}</select></div>`;
    h+=phField(i,'username','SIP Username',n.username,{max:64,ph:'blank = the extension',auto:au('username')});
    h+=phField(i,'auth_id','Authentication ID',n.auth_id,{max:64,ph:'blank = the SIP username',auto:au('auth_id')});
    h+=phField(i,'password','SIP Password',n.password,{type:'password',max:128,ph:n.has_password?'unchanged':'required'});
    h+=phChk('register','Sign in (register) with this network',n.register);
    h+=`<div class="ph-sub">Voicemail</div>`;
    if(!aw)h+=phField(i,'voicemail','Voicemail',n.voicemail,{max:64,ph:'e.g. 400353@default',auto:au('voicemail')});
    h+=phField(i,'voicemail_pin','Voicemail PIN',n.voicemail_pin,{type:'password',max:10,num:true,ph:n.has_voicemail_pin?'unchanged':'optional'});
    h+=phField(i,'voicemail_access','Voicemail Access',n.voicemail_access,{max:8,ph:'e.g. *97',auto:au('voicemail_access')});
    if(!aw)h+=phField(i,'login_url','Website login link',n.login_url,{max:300,ph:'https://...'});
  }else{
  h+=phField(i,'host','Server',n.host,{max:120,ph:'e.g. dallas1.voip.ms'});
  h+=phField(i,'port','Port (blank = default)',n.port,{max:5,num:true});
  if(login){
    h+=phField(i,'username','Username',n.username,{max:64});
    h+=phField(i,'password','Password',n.password,{type:'password',max:128,ph:n.has_password?'unchanged':'required'});
    h+=phChk('register','Sign in (register) with this network',n.register);
  }
  }
  h+=`<div class="cfg-field"><label class="cfg-lbl">Dialing</label><select class="cfg-inp" data-k="dialing" onchange="phRerender()">${phOpts([['phone','Phone numbers'],['ext','Extensions']],n.dialing)}</select></div>`;
  h+=phField(i,'caller_id','Caller ID number',n.caller_id,{max:15,num:true,auto:au('caller_id')});
  if(phone){
    h+=`<div class="cfg-field"><label class="cfg-lbl">Send number as</label><select class="cfg-inp" data-k="dial_format">${phOpts([['10','10 digits'],['1','1 + 10 digits'],['+1','+1 + 10 digits']],n.dial_format)}</select></div>`;
    h+=phChk('e911','E911 is set up (allows 911)',n.e911);
    h+=phChk('allow_intl','Allow international (011)',n.allow_intl);
  }
  h+=`<div class="ph-sub">Incoming calls</div>`;
  h+=`<div class="cfg-field"><label class="cfg-lbl">When someone calls</label><select class="cfg-inp" data-k="incoming" onchange="phRerender()">${phOpts([['off','Hang up'],['pin','Ask for a PIN'],['open','Answer (no PIN)']],n.incoming)}</select></div>`;
  if(pin){
    h+=phField(i,'pin','PIN (4-8 digits)',n.pin,{type:'password',max:8,num:true,ph:n.has_pin?'unchanged':'required'});
    h+=phField(i,'trusted','Trusted numbers (skip PIN)',n.trusted,{max:160,ph:'10 digits, comma separated'});
  }
  if(opn)h+=phField(i,'trusted','Trusted numbers (only these get through)',n.trusted,{max:160,ph:'blank = anyone'});
  h+=phField(i,'did','Your phone number (DID)',n.did,{max:15,num:true});
  h+=phField(i,'test_number','Test number',n.test_number,{max:20,ph:'e.g. an echo test'});
  h+=`<div class="ph-sub">Tone buttons (Phone tab)</div>`;
  for(let k=0;k<PH_TONE_BTNS;k++){
    h+=`<div class="cfg-field"><label class="cfg-lbl">Button ${k+1}</label><div class="ph-btn-pair">`+
      `<input class="cfg-inp" data-k="btn_label_${k}" type="text" maxlength="10" placeholder="Label" value="${esc(n['btn_label_'+k]||'')}" autocomplete="off">`+
      `<input class="cfg-inp" data-k="btn_tones_${k}" type="text" inputmode="tel" maxlength="32" placeholder="Tones, e.g. *99" value="${esc(n['btn_tones_'+k]||'')}" autocomplete="off"></div></div>`;
  }
  if(sip){
    h+=`<div class="ph-sub">Keypad tones (SIP)</div>`;
    h+=`<div class="cfg-field"><label class="cfg-lbl">Tone mode</label><select class="cfg-inp" data-k="tone_mode"${n.type==='hoip'?' onchange="phRerender()"':''}>${phOpts(PH_TONE_MODES,n.tone_mode||'auto')}</select></div>`;
    h+=`<div class="ph-sub">Behind a router (SIP)</div>`;
    h+=phField(i,'lan_net','Home network',n.lan_net,{max:43,ph:'192.168.1.0/24'});
    h+=phField(i,'wan_ip','Public IP address',n.wan_ip,{max:45,ph:'e.g. 203.0.113.5'});
  }
  h+=`</div>`;
  if(pin)h+=`<div class="ph-hint">Callers hear a beep, key the PIN then #. Incoming calls are answered only while the Phone tab is open; otherwise the caller gets a busy signal.</div>`;
  if(opn)h+=`<div class="ph-hint">Callers go straight on the air with no PIN. If trusted numbers are listed, only those numbers get through and everyone else hears busy. Calls are answered only while the Phone tab is open; otherwise the caller gets a busy signal.</div>`;
  h+=`<div class="ph-hint">Node number: this network's own private node (1000-1999). Leave it blank and Save Phone gives it the next free number counting up from the Phone Bridge. Only the picked network's node is linked to your radio, and only while the Phone tab is open.</div>`;
  h+=`<div class="ph-hint">Tone buttons show on the Phone tab and work during a call. Tones use 0-9, * and #; a comma waits 1 second. A blank label shows the tones.</div>`;
  h+=`<div class="ph-hint">Test number adds a Test call row to the Phone tab. An echo test (it plays your voice back) is the quickest way to check the far end can hear you. Ask your network for its number.</div>`;
  if(sip)h+=`<div class="ph-hint">Tone mode is how keypad tones reach this network. Automatic works for most. If the far end doesn't react to tones, try Real tones in the audio, then SIP messages. Takes effect after Save Phone. During a call you can also try each one from the Phone tab's Keypad and press Keep this.</div>`;
  if(n.type==='iax2')h+=`<div class="ph-hint">IAX2 uses port ${esc(_ph.iaxPort||'4569')}, the same one AllStarLink already uses on this Pi.</div>`;
  else if(hoip)h+=`<div class="ph-hint">Hams Over IP: SIP on UDP 5160, audio (RTP) on UDP 10000-15000. Voicemail Access adds a Voicemail row to the Phone tab.</div>`;
  if(n.type==='hoip'){   // v9.3.54; v9.3.55: the tone warning updates when Tone mode is changed
    if((n.tone_mode||'auto')!==PH_HOIP_TONE)h+=`<div class="ph-hint" style="color:var(--warn,#ffb020)">Hams Over IP asks for Tone mode: Tone packets only (RFC 2833). Pick it above and Save Phone, or *99 may not reach the far end.</div>`;
    h+=`<div class="ph-hint">To test keypad tones on Hams Over IP, call ${PH_HOIP_TONE_TEST}: wait for the beep, key some digits then #, and they are read back to you.${n.test_number===PH_HOIP_TONE_TEST?' The Test call row on the Phone tab dials it.':''}</div>`;
  }
  else h+=`<div class="ph-hint">SIP needs UDP 5060 and UDP 10000-20000 forwarded on your router.</div>`;
  // v9.3.6: router note, shown once on the first SIP network
  const rn=_ph.router||{};
  if(sip&&rn.text&&_ph.nets.findIndex(x=>x.type!=='iax2')===i)
    h+=`<div class="ph-hint ph-warn">${esc(rn.text)}</div>`+((rn.lines&&rn.lines.length)?`<pre class="ph-lines">${esc(rn.lines.join('\n'))}</pre>`:'');
  h+=phFavBlock(n,i);
  return h+`</div>`;
}
function phRender(){
  byId('ph-nets').innerHTML=_ph.nets.length?_ph.nets.map(phRenderNet).join(''):'<div class="ph-hint">No phone networks yet.</div>';
  byId('ph-add-btn').disabled=_ph.nets.length>=_ph.max;
}
function phSyncFromDOM(){
  document.querySelectorAll('#ph-nets .ph-net').forEach(card=>{
    const n=_ph.nets[+card.dataset.i];if(!n)return;
    card.querySelectorAll('[data-k]').forEach(el=>{n[el.dataset.k]=el.type==='checkbox'?el.checked:el.value});
    card.querySelectorAll('.ph-fav-row').forEach(row=>{
      const f=(n.favs||[])[+row.dataset.fi];if(!f)return;
      row.querySelectorAll('[data-fk]').forEach(el=>{f[el.dataset.fk]=el.value});
    });
  });
}
function phSxToggle(){
  const on=byId('ph-sx').checked;
  byId('ph-sx-grid').style.display=on?'':'none';
  byId('ph-sx-hint').style.display=on?'':'none';
  _ph.dirty=true;
}
// v9.3.51: Hams Over IP cards fill in the boxes that repeat something else.
// n._auto remembers each value filled in for you; a box is only ever filled
// while it is blank or still holds that value, so anything you type stays.
// Passwords and PINs are never filled.  Browser only -- Save Phone saves.
const PH_FROM_EXT={username:e=>e,auth_id:e=>e,caller_id:e=>e,voicemail:e=>e+'@default'};
function phAutoSet(n,k,v){
  if(!v)return false;
  n._auto=n._auto||{};
  const cur=String(n[k]==null?'':n[k]);
  if(cur&&!(k in n._auto&&n._auto[k]===cur))return false;   // yours: leave it
  n[k]=v;n._auto[k]=v;return true;
}
function phAutoFill(n,i){
  if(!PH_EXT_TYPES.includes(n.type))return;
  const df=PH_EXT_DEF[n.type],aw=n.type==='awire';
  const others=_ph.nets.filter((x,j)=>j!==i&&PH_EXT_TYPES.includes(x.type));
  const cs=((byId('cfg-callsign')||{}).value||'').trim().toUpperCase();
  if(aw){   // v9.3.53: AmateurWire -- display name starts as your callsign; DMR ID from another card
    phAutoSet(n,'display_name',cs||(others.find(x=>x.display_name)||{}).display_name||'');
    phAutoSet(n,'dmr_id',(others.find(x=>x.dmr_id)||{}).dmr_id||'');
  }else{
    phAutoSet(n,'callsign',cs||(others.find(x=>x.callsign)||{}).callsign||'');
    phAutoSet(n,'email',(others.find(x=>x.email)||{}).email||'');
  }
  if(!n.name||(n._auto&&n._auto.name===n.name)){
    const used=new Set(_ph.nets.filter((x,j)=>j!==i).map(x=>x.name));
    let nm=df.name,k=2;while(used.has(nm))nm=df.name+' '+(k++);
    phAutoSet(n,'name',nm);
  }
  phAutoSet(n,'host',df.host);phAutoSet(n,'port',df.port);
  phAutoSet(n,'voicemail_access','*97');
  const ext=String(n.extension||'').trim();
  if(ext)Object.entries(PH_FROM_EXT).forEach(([k,f])=>{if(!(aw&&k==='voicemail'))phAutoSet(n,k,f(ext))});
}
// typing: the extension carries on into the boxes still filled for you;
// typing over a filled box makes it yours
document.addEventListener('input',e=>{
  const el=e.target;if(!el||!el.dataset||!el.dataset.k)return;
  const card=el.closest&&el.closest('.ph-net');if(!card)return;
  const n=_ph.nets[+card.dataset.i];if(!n)return;
  const k=el.dataset.k;n[k]=el.value;
  if(n._auto&&k in n._auto&&n._auto[k]!==el.value){
    delete n._auto[k];const f=el.closest('.cfg-field');if(f)f.classList.remove('ph-auto-on');
  }
  if(k==='extension'&&PH_EXT_TYPES.includes(n.type)){
    const ext=el.value.trim();
    Object.entries(PH_FROM_EXT).forEach(([dk,f])=>{
      const box=card.querySelector(`[data-k="${dk}"]`);if(!box)return;   // (AmateurWire has no Voicemail box)
      n[dk]=box.value;
      if(!ext){
        if(n._auto&&dk in n._auto&&n._auto[dk]===box.value){box.value='';n[dk]='';delete n._auto[dk];
          const fl=box.closest('.cfg-field');if(fl)fl.classList.remove('ph-auto-on')}
        return;
      }
      if(phAutoSet(n,dk,f(ext))){box.value=n[dk];const fl=box.closest('.cfg-field');if(fl)fl.classList.add('ph-auto-on')}
    });
  }
});
function phRerender(){
  const prev=_ph.nets.map(n=>n.type);
  phSyncFromDOM();
  _ph.nets.forEach((n,i)=>{   // v9.3.51
    if(PH_EXT_TYPES.includes(prev[i])&&n.type!==prev[i]&&n._auto){   // v9.3.53: any change of service
      Object.entries(n._auto).forEach(([k,v])=>{if(k!=='name'&&String(n[k]||'')===v)n[k]=''});
      n._auto={};
    }
    phAutoFill(n,i);
  });
  _ph.nets.forEach((n,i)=>{
    if(!PH_EXT_TYPES.includes(n.type))return;
    if(!n.host)n.host=PH_EXT_DEF[n.type].host;
    if(!n.port)n.port=PH_EXT_DEF[n.type].port;
    n.transport='udp';
    if(!PH_EXT_TYPES.includes(prev[i]))n.dialing='ext';
    if(n.type==='hoip'&&prev[i]!=='hoip'){   // v9.3.54: HOIP's tone setting and tone test
      if(!n.tone_mode||n.tone_mode==='auto')n.tone_mode='';
      phAutoSet(n,'tone_mode',PH_HOIP_TONE);
      phAutoSet(n,'test_number',PH_HOIP_TONE_TEST);
    }
  });
  phRender();_ph.dirty=true;
}
function phAddNet(){
  phSyncFromDOM();
  if(_ph.nets.length>=_ph.max)return;
  _ph.nets.push(Object.assign({},PH_BLANK_NET,{favs:phFavsIn([])}));
  phAutoFill(_ph.nets[_ph.nets.length-1],_ph.nets.length-1);   // v9.3.51
  _ph.dirty=true;phRender();
}
function phRemoveNet(i){phSyncFromDOM();_ph.nets.splice(i,1);_ph.dirty=true;phRender()}
// v9.3.49: on/off switch with a warning popup.  The box only changes once
// the popup is answered (phLoad sets it from the saved setting).
let _phDlgOk=null;
function phDlgOpen(title,html,okLabel,okCls,onOk){
  byId('ph-dlg-title').textContent=title;byId('ph-dlg-body').innerHTML=html;
  const b=byId('ph-dlg-ok');b.textContent=okLabel;b.className='btn '+okCls;b.disabled=false;
  byId('ph-dlg-restart').checked=byId('ph-restart')?byId('ph-restart').checked:false;
  _phDlgOk=onOk;byId('ph-dlg-overlay').classList.add('open');
}
function phDlgClose(){byId('ph-dlg-overlay').classList.remove('open');_phDlgOk=null}
(function(){
  const b=byId('ph-dlg-ok');
  if(b)b.addEventListener('click',async()=>{
    if(!_phDlgOk)return;const fn=_phDlgOk;b.disabled=true;b.textContent='Working…';
    try{await fn(byId('ph-dlg-restart').checked)}finally{phDlgClose()}
  });
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&byId('ph-dlg-overlay').classList.contains('open'))phDlgClose()});
})();
function phNodesFor(){
  const base=String(_ph.node||'1001'),rows=_ph.nets.filter(n=>n.node).map(n=>n.node+' ('+(n.name||'?')+')');
  if(!_ph.nets.some(n=>String(n.node)===base))rows.push(base+' (Phone Bridge)');
  return rows.length?rows.join(', '):base+' (Phone Bridge)';
}
function phActClick(e){
  e.preventDefault();
  if(_ph.active_on){phRevertOpen();return false}
  if(_ph.dirty){toast('Save Phone first, then Activate','err');return false}
  const sip=_ph.nets.some(n=>n.type!=='iax2'),iax=_ph.nets.some(n=>n.type==='iax2')||byId('ph-hl-on').checked;
  const html='<p>Turning the phone on changes Asterisk on this Pi:</p><ul>'+
    `<li><b>rpt.conf</b>: adds private node${_ph.nets.length>1?'s':''} ${esc(phNodesFor())}, one per phone network, each with its own code list (*61 dial, *65 hang up).</li>`+
    '<li><b>extensions.conf</b>: one line that includes the dashboard\'s dialing file.</li>'+
    (sip?'<li><b>pjsip.conf</b>: one line that includes the dashboard\'s SIP file.</li>':'')+
    (iax?'<li><b>iax.conf</b>: two lines that include the dashboard\'s IAX2 files.</li>':'')+
    `<li><b>modules.conf</b>: phone module lines.${sip?' SIP needs Asterisk restarted once.':''}</li>`+
    '<li><b>/var/lib/asterisk</b>: two small scripts (hang up, radio tone codes).</li>'+
    '<li>A one-time <b>.dvsphone.bak</b> copy of each Asterisk file before its first change.</li></ul>'+
    '<p>While the Phone tab is open, the picked network\'s node links to your radio, and the transmitter time-out is off if that box is ticked.</p>'+
    '<p>Not done for you: router and firewall ports.</p>'+
    '<p>Revert (at the bottom of the Phone section) takes it all back out.</p>';
  phDlgOpen('Turn the phone on?',html,'Activate','btn-teal',async restart=>{
    const d=await api({action:'phone-activate',restart},60000);
    toast(d.message,d.ok?'ok':'err');byId('ph-msg').textContent=d.message;
    await phLoad();_pt.loadedAt=0;
  });
  return false;
}
// v9.3.50: Revert -- also opened by unticking Activate.
function phRevertOpen(){
  const html='<p>Turning the phone off takes it back out of Asterisk on this Pi:</p><ul>'+
    '<li>Hangs up any call and unlinks the phone nodes from your radio.</li>'+
    `<li><b>rpt.conf</b>: removes the phone nodes ${esc(phNodesFor())} and their code lists.</li>`+
    '<li><b>extensions.conf, pjsip.conf, iax.conf</b>: removes the dashboard\'s include lines and its dialing, SIP and IAX2 files (HOIP AllStar Link too).</li>'+
    '<li><b>modules.conf</b>: removes the phone module lines.</li>'+
    '<li>Removes the two phone scripts and the phone notes stored in Asterisk.</li></ul>'+
    '<p>Asterisk reloads. If the SIP modules were loaded or a phone node keeps running, Asterisk needs one restart (tick the box below).</p>'+
    '<p>Kept: your networks, favorites and passwords, and anything you added to these files by hand. Activate puts the phone back.</p>';
  phDlgOpen('Turn the phone off?',html,'Revert','btn-red',async restart=>{
    const d=await api({action:'phone-revert',restart},90000);
    toast(d.message,d.ok?'ok':'err');byId('ph-msg').textContent=d.message;
    await phLoad();_pt.loadedAt=0;
  });
}
// v9.3.47: Phone nodes list next to the bridges (information only).  The
// starting number (Phone Bridge, 1001) is kept as it is in a hidden box.
function phNodesSel(d){
  const sel=byId('cfg-phone-nodes');if(!sel)return;
  const nets=(d&&d.networks)||[],base=String((d&&d.node)||'');
  const rows=nets.filter(n=>n.node).map(n=>[String(n.node),n.name+(n.id===d.active?' (picked)':'')]);
  if(base&&!rows.some(r=>r[0]===base))rows.push([base,'Phone Bridge, no network']);
  rows.sort((a,b)=>(+a[0])-(+b[0]));
  if(!nets.length){sel.innerHTML='<option value="">No phone networks yet</option>';sel.disabled=true;return}
  sel.disabled=false;
  sel.innerHTML=rows.map(r=>`<option value="${esc(r[0])}">${esc(r[0])} · ${esc(r[1])}</option>`).join('');
  const pick=nets.find(n=>n.id===d.active);
  if(pick&&pick.node)sel.value=String(pick.node);
}
async function phLoad(){
  try{
    const d=await(await fetch('/api/phone')).json();
    phNodesSel(d);
    _ph.active_on=!!d.activated;_ph.node=d.node||'';   // v9.3.49
    byId('ph-active').checked=_ph.active_on;
    const wasOpen=new Set(_ph.nets.filter(n=>n._favOpen&&n.id).map(n=>n.id));
    _ph.nets=(d.networks||[]).map(n=>Object.assign({},PH_BLANK_NET,n,{password:'',pin:'',voicemail_pin:'',trusted:(n.trusted||[]).join(', '),
      favs:phFavsIn(n.favorites),_favOpen:wasOpen.has(n.id)},phBtnFlat(n.buttons)));
    _ph.nets.forEach((n,i)=>phAutoFill(n,i));   // v9.3.51: fill blank boxes on saved HOIP cards too
    _ph.active=d.active||'';_ph.max=d.max_networks||6;_ph.iaxPort=d.iax_port||'4569';_ph.router=d.router_note||{};
    byId('ph-patch').checked=d.patch_enabled!==false;
    byId('ph-dialtime').value=d.dialtime||20000;
    const sx=d.simplex||{};
    byId('ph-sx').checked=!!sx.enabled;
    byId('ph-sx-vt').value=sx.voxtimeout!=null?sx.voxtimeout:10000;
    byId('ph-sx-vr').value=sx.voxrecover!=null?sx.voxrecover:2000;
    byId('ph-sx-pd').value=sx.patchdelay!=null?sx.patchdelay:25;
    byId('ph-sx-fd').value=sx.phonedelay!=null?sx.phonedelay:25;
    byId('ph-hang').value=d.hangtime||'';
    byId('ph-signin').value=d.signin_mode==='all'?'all':'picked';
    byId('ph-totoff').checked=d.tot_phone_off!==false;
    byId('ph-totcap').value=d.tot_cap_min||15;
    phSxToggle();_ph.dirty=false;
    phHlLoad(d.hoip_link||{});
    phRender();_ph.loaded=true;_ph.dirty=false;byId('ph-msg').textContent='';
  }catch(e){console.error('phLoad() error:',e);byId('ph-msg').textContent='Could not load phone settings'}
}
// v9.3.19: Hams Over IP AllStar Link fields (the password never comes back).
function phHlLoad(h){
  byId('ph-hl-on').checked=!!h.enabled;
  byId('ph-hl-user').value=h.username||'';
  byId('ph-hl-pass').value='';
  byId('ph-hl-pass').placeholder=h.has_password?'saved — leave blank to keep':'8+ characters';
  byId('ph-hl-fqdn').value=h.fqdn||'';
  byId('ph-hl-port').value=h.port||_ph.iaxPort||'4569';
  byId('ph-hl-node').innerHTML=phOpts(h.choices||[],h.node||'');
  phHlHints();
  byId('ph-hl-note').textContent=h.dial_hint?('Dial string: '+h.dial_hint):'';
  const hs=byId('ph-hl-str');if(hs){hs.value='';hs.style.display='none'}
}
// v9.3.21: copy the full dial string (with the password) for the HOIP ticket.
async function phHlCopy(){
  if(_ph.dirty){toast('Save Phone first, then copy','err');return}
  const d=await api({action:'phone-hl-dialstring'},10000);
  if(!d.ok){toast(d.message,'err');return}
  const t=byId('ph-hl-str');t.value=d.message;t.style.display='';
  try{if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(d.message);toast('Dial string copied','ok');return}}catch(_){}
  t.focus();t.select();
  let ok=false;try{ok=document.execCommand('copy')}catch(_){}
  toast(ok?'Dial string copied':'Text is selected — press Ctrl+C (or long-press → Copy)',ok?'ok':'err');
}
function phHlHints(){
  const ip=_ph.iaxPort||'4569';
  const p=(byId('ph-hl-port').value||'').trim()||ip;
  const ph=byId('ph-hl-porthint');
  if(ph)ph.textContent=p===ip?'UDP port '+ip+' forwarded to this Pi':
    'UDP port '+p+' forwarded on your router to port '+ip+' on this Pi (Asterisk only listens on '+ip+')';
  const sel=byId('ph-hl-node'),w=byId('ph-hl-warn');
  if(sel&&w){const radio=sel.selectedIndex>0;w.style.display=radio?'':'none';}
}
async function phSave(quiet){
  phSyncFromDOM();
  const phone={active:_ph.active,patch_enabled:byId('ph-patch').checked,
    dialtime:byId('ph-dialtime').value.trim(),
    simplex:{enabled:byId('ph-sx').checked,voxtimeout:byId('ph-sx-vt').value.trim(),
      voxrecover:byId('ph-sx-vr').value.trim(),patchdelay:byId('ph-sx-pd').value.trim(),
      phonedelay:byId('ph-sx-fd').value.trim()},
    hangtime:byId('ph-hang').value.trim(),
    signin_mode:byId('ph-signin').value,
    tot_phone_off:byId('ph-totoff').checked,
    tot_cap_min:byId('ph-totcap').value.trim(),
    networks:_ph.nets.map(n=>{const o=Object.assign({},n,{trusted:String(n.trusted||''),buttons:phBtnList(n),favorites:phFavsOut(n.favs)});
      delete o.favs;delete o._favOpen;delete o._auto;return o}),
    hoip_link:{enabled:byId('ph-hl-on').checked,username:byId('ph-hl-user').value.trim(),
      password:byId('ph-hl-pass').value,fqdn:byId('ph-hl-fqdn').value.trim(),
      port:byId('ph-hl-port').value.trim(),node:byId('ph-hl-node').value}};
  const d=await api({action:'save-phone',phone});
  if(!d.ok){toast('Phone: '+d.message,'err');byId('ph-msg').textContent=d.message;return false}
  const a=await api({action:'phone-apply',restart:byId('ph-restart').checked},60000);
  toast(a.ok?('Phone: '+d.message+' — '+a.message):('Phone: saved, but Asterisk: '+a.message),a.ok?'ok':'err');
  byId('ph-msg').textContent=a.message;
  await phLoad();
  _pt.loadedAt=0;
  return a.ok;
}
document.addEventListener('input',e=>{if(e.target.closest&&e.target.closest('#ph-section'))_ph.dirty=true});
(function(){
  // v9.3.34: Show/Hide and ✕ (clear saved tones) inside each network card
  const pn=byId('ph-nets');
  if(pn)pn.addEventListener('click',e=>{
    const card=e.target.closest('.ph-net');if(!card)return;
    const n=_ph.nets[+card.dataset.i];if(!n)return;
    const t=e.target.closest('[data-ftog]');
    if(t){phSyncFromDOM();n._favOpen=!n._favOpen;phRender();return}
    const b=e.target.closest('[data-fclr]');if(!b)return;
    phSyncFromDOM();
    const f=(n.favs||[])[+b.dataset.fclr];if(!f)return;
    f.tones='';f.has_tones=false;f.tones_clear=true;_ph.dirty=true;phRender();
  });
})();
document.addEventListener('change',e=>{if(e.target.closest&&e.target.closest('#ph-section'))_ph.dirty=true});
async function edReload(){
  try{
    const[tgRes,ndRes,ecRes,srvRes,srvTgRes,xlxRes,m17Res]=await Promise.all([
      fetch('/api/talkgroups'),fetch('/api/asl-nodes'),fetch('/api/echo-nodes'),
      fetch('/api/dmr-servers-full'),fetch('/api/dmr-server-tgs'),fetch('/api/xlx-reflectors'),
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
    edRender();await cfgLoad();await phLoad();toast('Loaded','ok');
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
  syncEdRowsFromDOM('.dstar-ed-row',edRows,(row,entry)=>edRefRowSync(row,entry,'dstar'));
}
/* v9.3.67: one row reader for the D-STAR and XLX reflector editors.  Name,
   then tg = base padded to 6 + module + L (v8.7.6: the pad puts the module
   in slot 7; a no-op for XLX, which is always 6), blank base = blank row,
   then the LH link. */
function edRefRowSync(row,entry,p){
  const n=row.querySelector('.'+p+'-inp-name');
  const b=row.querySelector('.'+p+'-inp-base');
  const m=row.querySelector('.'+p+'-inp-mod');
  if(n)entry.name=n.value;
  if(b&&m){
    const baseVal=b.value.trim().toUpperCase();
    entry.tg=baseVal?baseVal.padEnd(6)+m.value.trim().toUpperCase()+'L':TG_BLANK_ADDR;
    if(!baseVal)entry.name=TG_BLANK_NAME;
  }
  const u=row.querySelector('.url-inp');
  if(u)entry.url=u.value.trim();
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
  syncEdRowsFromDOM('.xlx-ed-row',xlxEdRows,(row,entry)=>edRefRowSync(row,entry,'xlx'));
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
  syncEdRowsFromDOM('.nd-row',ndRows,(row,entry)=>{   // v9.3.66
    const n=row.querySelector('.nd-inp-name');const nd=row.querySelector('.nd-inp-node');
    if(n)entry.name=n.value;if(nd)entry.node=nd.value;
  });
}
function ecSyncFromDOM(){
  syncEdRowsFromDOM('.ec-row',ecRows,(row,entry)=>{   // v9.3.66
    const n=row.querySelector('.ec-inp-name');const nd=row.querySelector('.ec-inp-node');
    if(n)entry.name=n.value;if(nd)entry.node=nd.value;
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
// v8.0.10 — delegated listeners for the DMR-network editor. The server "key"
// (and every field rendered under it) comes from user-editable text and is
// carried purely as data-*/value attributes now (see edRender()'s DMR
// Networks section) rather than interpolated into inline on*="..." handler
// strings — HTML-escaping a value doesn't stop it from breaking out of a JS
// string once the browser decodes entities in an attribute value, which is
// exactly the class of bug this replaces. Wired once (#ed-list itself is
// static markup; only its innerHTML is replaced by edRender()).
function _edInput(e){
  const t=e.target;
  if(t.classList.contains('dsm-field')){
    const block=t.closest('[data-srvkey]');
    if(block)dmrSrvMetaChanged(block.dataset.srvkey,t.dataset.field,t.value);
  }else if(t.classList.contains('dsm-tg-field')){
    const row=t.closest('.dsm-tg-row');
    if(row)dmrSrvTgChanged(row.dataset.srvkey,Number(row.dataset.idx),t.dataset.field,t.value);
  }
}
function _edClick(e){
  const rm=e.target.closest('.dsm-remove');
  if(rm){
    const block=rm.closest('[data-srvkey]');
    if(block)dmrSrvRemove(block.dataset.srvkey);
    return;
  }
  const tg=e.target.closest('.dsm-toggle');
  if(tg&&tg.dataset.target){ toggleEdSection(tg.dataset.target); return; }
}
(function _wireEdList(){
  const el=byId('ed-list');
  if(el){ el.addEventListener('input',_edInput); el.addEventListener('click',_edClick); }
})();
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
  const allSids=['eds-tabs','eds-phone','eds-ASL','eds-ECHO','eds-DSTAR','eds-XLX','eds-M17',
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
        h+=`<div id="eds-FCS">`;
        h+=edUrlRow('FCS');   // v8.8.1: FCS network Last Heard, like ASL
        h+=`<div class="ed-list-grid">`;
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
      // v8.0.10: the DMR server "key" is derived from the user-editable
      // server name and can contain quote/backtick characters, so it (and
      // every field below) is carried as a data-* attribute and handled by
      // the delegated _edInput/_edClick listeners wired near the bottom of
      // this file — never interpolated into an inline on*="..." handler
      // string, which is exactly the pattern the v8.0.10 XSS fixes removed.
      h+=`<div class="srv-meta-row dsm-block" data-srvkey="${esc(key)}">`;
      h+=`<input class="ed-inp dsm-field" data-field="srvName" value="${esc(srv.srvName)}" placeholder="Name">`;
      h+=`<input class="ed-inp dsm-field" data-field="password" value="${esc(srv.password)}" placeholder="Password">`;
      h+=`<input class="ed-inp dsm-field" data-field="address" value="${esc(srv.address)}" placeholder="host:port">`;
      h+=`<button class="btn-xs btn-red dsm-remove" title="Remove">×</button>`;
      h+='</div>';
      h+=`<div class="ed-url-row" data-srvkey="${esc(key)}"><span class="ed-url-label">Network Dashboard URL</span>`;
      h+=`<input class="ed-inp url-inp dsm-field" data-field="netUrl" value="${esc(srv.netUrl||'')}" placeholder="https://host/last_heard (optional)"></div>`;
    });
    h+='</div>';
    h+=`<div style="padding:.35rem .6rem"><button class="btn btn-muted" onclick="dmrSrvAdd()" style="font-size:.77rem;padding:.3rem .8rem">+ Add Network</button></div>`;
    h+='</div>';
    if(Object.keys(dmrSrvRows).length){
      Object.entries(dmrSrvRows).forEach(([key,srv])=>{
        const tgsid=`eds-TGS-${key}`;
        h+=`<div class="ed-sec-hdr"><span>TGs · ${esc(srv.srvName)}</span><button class="dsm-toggle" data-target="${esc(tgsid)}">Hide</button></div>`;
        h+=`<div id="${esc(tgsid)}"><div class="ed-list-grid" style="margin-bottom:.5rem">`;
        h+=srv.rows.map((r,i)=>`<div class="ed-row dsm-tg-row" data-srvkey="${esc(key)}" data-idx="${i}">
          <input class="ed-inp dsm-tg-field" data-field="name" value="${esc(r.name)}" placeholder="Name">
          <input class="ed-inp dsm-tg-field" data-field="tg" value="${esc(r.tg)}" placeholder="TG">
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
    if(_ph.loaded&&_ph.dirty)await phSave(true);
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
      if(mode==='PHONE')ptRenderStatus();   // v9.3.8: Talking / Listening
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
        renderASLGrid(_lastAslNodes,linkedNode);  // A5 writer 2/7 — see applyGridState comment
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
          renderASLGrid(_lastAslNodes,linkedNode);  // A5 writer 3/7 — see applyGridState comment
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
      // v8.5.2: prefix match — ABInfo reports YSF as "YSFN"/"YSFW" (narrow/wide), so an
      // exact compare with "YSF" never matched and YSF/FCS only confirmed via the 10 s
      // fallback.  Other modes' ABInfo strings equal dvsModeFor() exactly, so they still match.
      const modeMatch=!d.mode||String(d.mode).startsWith(dvsModeFor(_pendingTune.mode));
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
let _appStarted=false;
function _startApp(){
  if(_appStarted)return;
  _appStarted=true;
  refresh().then(()=>{loadTgData();schedulePoll();pollKeyed();initModuleSelects();pollAbInfo();});
  setInterval(pollAbInfo,10_000);
  setInterval(()=>{
    if(!_uptimeAt)return;
    const el=byId('hdr-uptime');
    if(el)el.textContent=fmtUptime(_uptimeBase+Math.floor((Date.now()-_uptimeAt)/1000));
  },60_000);
  _initQuickLinks();
  _probeSysMon();
}

/* ── Root-password auth (v8.0.9) ──────────────────────────────────────────
   No app credential store — this logs in with the box's own root
   password. The server sets an HttpOnly, SameSite=Strict session cookie
   on success — there's no token for this page to carry around or attach
   to requests, the browser does that automatically on every same-origin
   /api/* call. Because that cookie isn't port-scoped, it also
   authenticates the sysmon companion app on this same host: log in once,
   on either one, and you're in on both. Since the cookie is HttpOnly (JS
   can't read it, on purpose), the only way to know whether we're already
   logged in is to ask the server — see the /api/whoami boot probe below. */
window._authLostHandled = false;

const _rawFetch = window.fetch.bind(window);
window.fetch = async function(input, init){
  const url = typeof input === 'string' ? input : (input && input.url) || '';
  const isApi = url.startsWith('/api/');
  const skipAuth = url === '/api/login' || url === '/api/ping';
  const res = await _rawFetch(input, init);
  if (isApi && !skipAuth && res.status === 401) _onAuthLost();
  return res;
};

/* v8.8.5: login-expiry refresh (same behaviour as instmon 2.36.1).  When a
   session is lost while the app is running (expired, logged out elsewhere,
   or the script reinstalled/restarted), reload the page instead of drawing
   the login over the stale page, which mangles its text.  A sessionStorage
   stamp carries "Session expired" across the reload and limits it to one
   reload: a second loss within _RELOGIN_WINDOW_MS shows the login in place.
   A fresh logged-out visit never reloads (the app hasn't started, so this
   path isn't reached — the boot gate shows the login directly). */
const _RELOGIN_KEY='dashRelogin';
const _RELOGIN_WINDOW_MS=30000;
const _SESSION_EXPIRED_MSG='Session expired — please log in again.';
function _onAuthLost(){
  if (window._authLostHandled) return; // multiple in-flight requests can all 401 at once
  window._authLostHandled = true;
  if (_appStarted) {
    let last = 0;
    try { last = Number(sessionStorage.getItem(_RELOGIN_KEY)) || 0; } catch(_) {}
    if (!last || Date.now() - last > _RELOGIN_WINDOW_MS) {
      let stamped = false;
      try { sessionStorage.setItem(_RELOGIN_KEY, String(Date.now())); stamped = true; } catch(_) {}
      if (stamped) {
        try { _saveTabState(); } catch(_) {}
        location.reload();
        return;
      }
    }
  }
  showLoginScreen(_SESSION_EXPIRED_MSG);
}
function showLoginScreen(msg){
  const el=byId('login-screen'); if(!el)return;
  el.classList.remove('hidden');
  const errEl=byId('login-err'); if(errEl)errEl.textContent=msg||'';
  const pwEl=byId('login-pw'); if(pwEl){pwEl.value='';setTimeout(()=>pwEl.focus(),0);}
}
function hideLoginScreen(){ const el=byId('login-screen'); if(el)el.classList.add('hidden'); }

async function _doLogin(ev){
  if(ev)ev.preventDefault();
  const pwEl=byId('login-pw'),btnEl=byId('login-btn'),errEl=byId('login-err');
  const password=pwEl?pwEl.value:'';
  if(!password)return;
  if(btnEl)btnEl.disabled=true;
  if(errEl)errEl.textContent='';
  try{
    const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},
                                       body:JSON.stringify({password})});
    const d=await r.json().catch(()=>({ok:false,message:'Unexpected response'}));
    if(r.ok&&d.ok){
      window._authLostHandled=false;
      try{sessionStorage.removeItem(_RELOGIN_KEY);}catch(_){}
      hideLoginScreen();
      _startApp();
    }else{
      if(errEl)errEl.textContent=d.message||'Login failed';
    }
  }catch(e){
    if(errEl)errEl.textContent='Network error — is the dashboard reachable?';
  }finally{
    if(btnEl)btnEl.disabled=false;
  }
}
function doLogout(){
  fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},
                        body:JSON.stringify({action:'logout'})})
    .catch(()=>{})
    .finally(()=>location.reload());
}

/* ── Quick links (v8.8.0) ──────────────────────────────────── */
function _initQuickLinks() {
  const host = window.location.hostname;
  document.querySelectorAll('.ql[data-ql-path],.ql[data-ql-port]').forEach(a => {
    a.href = a.dataset.qlPath ? `http://${host}${a.dataset.qlPath}`
                              : `http://${host}:${a.dataset.qlPort}/`;
  });
}

/* ── SysMon link probe ─────────────────────────────────────── */
async function _probeSysMon() {
  const btn = document.getElementById('lnk-sysmon');
  if (!btn) return;
  try {
    const r = await fetch('/api/sysmon-status');
    if (!r.ok) return;
    const d = await r.json();
    if (d.running) {
      btn.href = `http://${window.location.hostname}:${d.port}/`;
      btn.classList.remove('ql-off');
      btn.removeAttribute('aria-disabled');
      btn.removeAttribute('title');
      // Save current tab so Back from SysMon restores it (any tab, not just DMR).
      btn.addEventListener('click', () => {
        try{sessionStorage.setItem('sysmonReturn',JSON.stringify({page:curPage}));}catch(_){}
        try{navigator.sendBeacon('/api/action', new Blob([JSON.stringify({action:'cpuweight-away'})], {type:'application/json'}));}catch(_){}
      }, {once:true});
    }
  } catch (_) {}
}
// Boot gate: the session cookie is HttpOnly, so this page can't just check
// for it — it asks the server via /api/whoami instead. That request
// carries whatever session cookie the browser already holds for this
// host, on ANY port — including one set by logging into the sysmon
// companion app — so this is also the entire mechanism that makes a login
// on one app skip the login screen on the other.
(async function _authBoot(){
  try {
    const r = await fetch('/api/whoami');
    if (r.ok) { hideLoginScreen(); _startApp(); return; }
  } catch(_) { /* fall through to showing the login screen */ }
  // v8.8.5: after an expiry reload, say why the login is showing.
  let relogin = null;
  try { relogin = sessionStorage.getItem(_RELOGIN_KEY); } catch(_) {}
  showLoginScreen(relogin ? _SESSION_EXPIRED_MSG : '');
})();
</script>
</body>
</html>
"""

_HTML_BYTES = (HTML
               .replace("__VERSION__",    VERSION)
               .replace("__BUILD_DATE__", BUILD_DATE)
               .encode())
_HTML_GZIP  = gzip.compress(_HTML_BYTES, compresslevel=6)


_AUTH_ACCOUNT        = "root"
_SESSION_TTL_SEC     = 12 * 3600
_LOGIN_MAX_ATTEMPTS  = 5
_LOGIN_WINDOW_SEC    = 5 * 60
_LOGIN_LOCKOUT_SEC   = 15 * 60

def _read_shadow_hash(account: str) -> Optional[str]:
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

_SESSION_COOKIE_NAME = "asl_dvs_session"
_SHARED_AUTH_DIR      = Path("/run/asl_dvs")
_SHARED_AUTH_FILE     = _SHARED_AUTH_DIR / "auth_session.json"
_shared_auth_proc_lock = threading.Lock()


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

def _login_is_locked(ip: str) -> Optional[float]:
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


_PUBLIC_GET_PATHS = {"/", "/index.html", "/api/ping"}

class _EarlyReturn(Exception):
    pass

class Handler(BaseHTTPRequestHandler):
    timeout = 30

    def log_message(self, fmt, *args):
        pass

    def _accepts_gzip(self) -> bool:
        return "gzip" in self.headers.get("Accept-Encoding", "")

    def send_json(self, data: dict, status: int = 200,
                  extra_headers: Optional[Dict[str, str]] = None) -> None:
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
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'unsafe-inline'; "
                         "script-src 'unsafe-inline'; connect-src 'self'; "
                         "frame-ancestors 'none'")
        self.send_header("X-Frame-Options", "DENY")
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
            on_phone = _state.page == "PHONE"

        if current_etag and client_etag == current_etag and not on_phone:
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

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/favicon.ico":
            self.send_response(204); self.send_header("Cache-Control", "max-age=86400"); self.end_headers()
            return
        handler = _GET_ROUTES.get(path)
        if not handler:
            self.send_response(404); self.end_headers()
            return
        if path == "/api/event" and self._client_ip() in ("127.0.0.1", "::1"):
            pass
        elif path not in _PUBLIC_GET_PATHS and not self._require_auth():
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

    def _do_login(self) -> None:
        ip = self._client_ip()
        locked_until = _login_is_locked(ip)
        if locked_until is not None:
            wait = max(0, int(locked_until - time.time()))
            self.send_json({"ok": False, "message": f"Too many failed attempts — try again in {wait}s"}, 429)
            return
        if not self._require_json_content_type():
            return
        try:
            data = json.loads(self._read_body())
        except _EarlyReturn:
            return
        except (json.JSONDecodeError, ValueError) as e:
            self.send_json({"ok": False, "message": f"Bad request: {e}"}, 400); return
        password = str(data.get("password", "")) if isinstance(data, dict) else ""
        if _verify_root_password(password):
            _login_record_success(ip)
            token = _issue_session()
            log.info("login: successful root-password login from %s", ip)
            self.send_json({"ok": True}, 200,
                            extra_headers={"Set-Cookie": _session_cookie_header(token, _SESSION_TTL_SEC)})
        else:
            _login_record_failure(ip)
            log.warning("login: failed attempt from %s", ip)
            self.send_json({"ok": False, "message": "Incorrect password"}, 401)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/login":
            try:
                self._do_login()
            except _EarlyReturn:
                pass
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                log.exception("Unhandled error in login")
                try:
                    self.send_json({"ok": False, "message": "Internal server error"}, 500)
                except Exception:
                    pass
            return
        if path != "/api/action":
            self.send_response(404); self.end_headers(); return
        if not self._require_auth():
            return
        if not self._require_json_content_type():
            return
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
        extra = {"Set-Cookie": _clear_session_cookie_header()} if data.get("action") == "logout" else None
        try:
            self.send_json({"ok": ok, "message": msg}, 200 if ok else 400, extra_headers=extra)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _dispatch_action(self, data: dict) -> Tuple[bool, str]:
        action = str(data.get("action", ""))
        fn = _POST_ACTIONS.get(action)
        if fn is None:
            return False, f"Unknown action '{action}'"
        return fn(self, data)

def _arg(d: dict, key: str) -> str:
    return str(d.get(key, ""))

def _arg_s(d: dict, key: str) -> str:
    return str(d.get(key, "")).strip()

def _act_page(fn):
    def act(h, d):
        page = _arg(d, "page").upper()
        if page not in ALL_PAGES:
            return False, f"Unknown page '{page}'"
        return fn(page, d)
    return act

def _act_mode(fn):
    def act(h, d):
        mode = _arg(d, "mode").upper()
        if mode not in TUNE_MODES:
            return False, f"Unknown mode '{mode}'"
        return fn(mode, d)
    return act

def _act_background(message: str, target, root_only: str = ""):
    def act(h, d):
        if root_only:
            if os.geteuid() != 0:
                return False, f"root required for {root_only}"
            log.warning("%s requested", root_only.upper())
        h.send_json({"ok": True, "message": message})
        threading.Thread(target=target, daemon=True).start()
        raise _EarlyReturn()
    return act

def _act_rows(fn):
    def act(h, d):
        rows = d.get("rows", [])
        if not isinstance(rows, list):
            return False, "rows must be a list"
        return fn(rows)
    return act

def _act_logout(h, d):
    _revoke_session(h._session_token())
    return True, "Logged out"

def _act_switch_dmr_server(h, d):
    name = _arg_s(d, "name")
    if not name:
        return False, "name is required"
    return action_switch_dmr_server(name)

def _act_save_all(h, d):
    nd = d.get("nodes", [])
    tg = d.get("talkgroups", [])
    ec = d.get("echo_nodes", [])
    if not (isinstance(nd, list) and isinstance(tg, list) and isinstance(ec, list)):
        return False, "nodes, talkgroups and echo_nodes must be lists"
    return action_save_all(nd, tg, ec)

def _act_save_dmr_server_tgs(h, d):
    srv_tgs = d.get("server_tgs", {})
    if not isinstance(srv_tgs, dict):
        return False, "server_tgs must be a dict"
    return action_save_dmr_server_tgs(srv_tgs, d.get("server_list", None))

def _act_save_config(h, d):
    allowed  = {"asl_node", "bridge_node", "port", "callsign"}
    cfg_data = {k: str(v) for k, v in d.items() if k in allowed}
    if "enabled_tabs" in d and isinstance(d["enabled_tabs"], list):
        cfg_data["enabled_tabs"] = d["enabled_tabs"]
    if "mode_net_urls" in d and isinstance(d["mode_net_urls"], dict):
        cfg_data["mode_net_urls"] = d["mode_net_urls"]
    if "bridge_nodes" in d and isinstance(d["bridge_nodes"], (list, tuple)):
        cfg_data["bridge_nodes"] = list(d["bridge_nodes"])
    if "cpuweight_enabled" in d:
        cfg_data["cpuweight_enabled"] = bool(d["cpuweight_enabled"])
    return action_save_config(cfg_data)

_POST_ACTIONS: dict = {
    "logout":            _act_logout,
    "switch-tab":        _act_page(lambda page, d: action_switch_tab(page)),
    "retune-tab":        _act_page(lambda page, d: action_retune_tab(page, _arg_s(d, "server"))),
    "tune":              _act_mode(lambda mode, d: action_tune(mode, _arg(d, "tg"),
                                                           _clip_label(_arg(d, "name")))),
    "quick-tune":        _act_mode(lambda mode, d: action_quick_tune(mode, _arg_s(d, "tg"))),
    "asl-connect":       lambda h, d: action_asl_connect(_arg(d, "node"), _clip_label(_arg(d, "name"))),
    "asl-disc-current":  lambda h, d: action_asl_disconnect_current(),
    "disc-perm-link":    lambda h, d: action_disc_perm_link(),
    "connect-by-number": lambda h, d: action_connect_by_number(_arg(d, "node")),
    "echo-connect":      lambda h, d: action_echo_connect(_arg(d, "node"), _clip_label(_arg(d, "name"))),
    "echo-connect-by-number": lambda h, d: action_echo_connect_by_number(_arg(d, "node")),
    "echo-disc":         lambda h, d: action_echo_disconnect(),
    "dstar-connect":     lambda h, d: action_dstar_connect(
        _arg_s(d, "base"), _arg_s(d, "module"),
        _clip_label(_arg_s(d, "name") or f"DSTAR {_arg_s(d, 'base')}{_arg_s(d, 'module')}")),
    "xlx-connect":       lambda h, d: action_xlx_connect(
        _clip_label(_arg_s(d, "name") or f"XLX {_arg_s(d, 'base')} Mod-{_arg_s(d, 'module')}"),
        _arg_s(d, "base"), _arg_s(d, "module")),
    "dstar-disconnect":  lambda h, d: action_dstar_disconnect(),
    "xlx-disconnect":    lambda h, d: action_xlx_disconnect(),
    "m17-connect":       lambda h, d: action_m17_connect(
        _clip_label(_arg_s(d, "name") or f"M17 {_arg_s(d, 'base')} Mod-{_arg_s(d, 'module')}"),
        _arg_s(d, "base"), _arg_s(d, "ip"), _arg_s(d, "module")),
    "m17-disconnect":    lambda h, d: action_m17_disconnect(),
    "disc-all":          _act_background("Emergency disconnect — restarting services…",
                                         lambda: action_disconnect_all()),
    "switch-dmr-server": _act_switch_dmr_server,
    "save-all":          _act_save_all,
    "save-dmr-server-tgs": _act_save_dmr_server_tgs,
    "save-fcs-favorite": lambda h, d: action_save_fcs_favorite(_arg(d, "room")),
    "save-ysf-favorite": lambda h, d: action_save_ysf_favorite(_arg(d, "ref")),
    "save-tg-favorite":  lambda h, d: action_save_tg_favorite(_arg(d, "mode"), _arg(d, "tg")),
    "save-asl-favorite": lambda h, d: action_save_asl_favorite(_arg(d, "node")),
    "save-echo-favorite": lambda h, d: action_save_echo_favorite(_arg(d, "node")),
    "save-dmr-favorite": lambda h, d: action_save_dmr_favorite(_arg(d, "network"), _arg(d, "tg")),
    "save-m17-favorite": lambda h, d: action_save_m17_favorite(_arg(d, "base"), _arg(d, "module")),
    "save-dstar-favorite": lambda h, d: action_save_dstar_favorite(_arg(d, "base"), _arg(d, "module")),
    "save-xlx-favorite": lambda h, d: action_save_xlx_favorite(_arg(d, "base"), _arg(d, "module")),
    "save-xlx":          _act_rows(lambda rows: action_save_xlx(rows)),
    "save-m17":          _act_rows(lambda rows: action_save_m17(rows)),
    "save-config":       _act_save_config,
    "save-phone":        lambda h, d: action_save_phone(d.get("phone", {})),
    "phone-select":      lambda h, d: action_phone_select(_arg_s(d, "network")),
    "phone-apply":       lambda h, d: action_phone_apply(bool(d.get("restart", False))),
    "phone-activate":    lambda h, d: action_phone_activate(bool(d.get("restart", False))),
    "phone-revert":      lambda h, d: action_phone_revert(bool(d.get("restart", False))),
    "phone-dial":        lambda h, d: action_phone_dial(_arg(d, "number")),
    "phone-voicemail":   lambda h, d: action_phone_voicemail(),
    "phone-vm-pin":      lambda h, d: action_phone_vm_pin(),
    "phone-test":        lambda h, d: action_phone_test(),
    "phone-hangup":      lambda h, d: action_phone_hangup(),
    "phone-tones":       lambda h, d: action_phone_send_tones(_arg(d, "tones")),
    "phone-tone-mode":   lambda h, d: action_phone_tone_mode(_arg_s(d, "mode")),
    "phone-tone-keep":   lambda h, d: action_phone_tone_keep(),
    "phone-tone-path":   lambda h, d: action_phone_tone_path(_arg_s(d, "path")),
    "phone-hl-dialstring": lambda h, d: action_hl_dialstring(),
    "phone-patch":       lambda h, d: action_phone_patch(bool(d.get("on", False))),
    "save-phone-favorite": lambda h, d: action_save_phone_favorite(_arg(d, "number"), _arg(d, "name")),
    "reboot":            _act_background("Rebooting…",
                                         lambda: (time.sleep(1), os.system("reboot")), "reboot"),
    "shutdown":          _act_background("Shutting down…",
                                         lambda: (time.sleep(1), os.system("shutdown -h now")),
                                         "shutdown"),
    "cpuweight-away":    lambda h, d: action_cpuweight_away(),
    "cpuweight-resume":  lambda h, d: action_cpuweight_resume(),
}

def _send_event_response(handler) -> None:
    try:
        handler.send_json({"ok": True})
    except (BrokenPipeError, ConnectionResetError):
        pass

_GET_ROUTES: dict = {
    "/":               lambda h: h.send_html(),
    "/index.html":     lambda h: h.send_html(),
    "/api/ping":       lambda h: h.send_ping(),
    "/api/whoami":     lambda h: h.send_json({"ok": True}),
    "/api/sysmon-status": lambda h: h.send_json(action_sysmon_status()),
    "/api/status":     lambda h: h.send_status(),
    "/api/keyed":      lambda h: h.send_json(action_get_keyed()),
    "/api/talkgroups":     lambda h: h.send_json(action_get_talkgroups()),
    "/api/asl-nodes":      lambda h: h.send_json(action_get_asl_nodes()),
    "/api/echo-nodes":     lambda h: h.send_json(action_get_echo_nodes()),
    "/api/xlx-reflectors": lambda h: h.send_json(action_get_xlx_reflectors()),
    "/api/m17-reflectors": lambda h: h.send_json(action_get_m17_reflectors()),
    "/api/dmr-servers-full": lambda h: h.send_json(action_get_dmr_servers_full()),
    "/api/dmr-server-tgs": lambda h: h.send_json(action_get_dmr_server_tgs()),
    "/api/dmr-ready":      lambda h: h.send_json(action_dmr_server_ready()),
    "/api/fcs-hosts":      lambda h: h.send_json(action_get_fcs_hosts()),
    "/api/ysf-hosts":      lambda h: h.send_json(action_get_ysf_hosts()),
    "/api/p25-hosts":      lambda h: h.send_json(action_get_tg_hosts("P25")),
    "/api/nxdn-hosts":     lambda h: h.send_json(action_get_tg_hosts("NXDN")),
    "/api/stfu-hosts":     lambda h: h.send_json(action_get_stfu_tgs()),
    "/api/m17-hosts":      lambda h: h.send_json(action_get_m17_hosts()),
    "/api/xlx-hosts":      lambda h: h.send_json(action_get_xlx_hosts()),
    "/api/dstar-hosts":    lambda h: h.send_json(action_get_dstar_hosts()),
    "/api/asl-directory":  lambda h: h.send_json(action_asl_directory(h.path)),
    "/api/echo-directory": lambda h: h.send_json(action_echo_directory(h.path)),
    "/api/config":     lambda h: h.send_json(action_get_config()),
    "/api/phone":      lambda h: h.send_json(action_get_phone()),
    "/api/phone-report": lambda h: h.send_json(action_phone_report()),
    "/api/phone-callcheck": lambda h: h.send_json(action_phone_callcheck()),
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

def _harden_existing_conf_perms() -> None:
    try:
        p = Path(ASL_DVS_CONF)
        if p.is_file():
            mode = p.stat().st_mode & 0o777
            if mode != 0o600:
                p.chmod(0o600)
                log.info("startup: tightened %s permissions %o -> 0600", ASL_DVS_CONF, mode)
    except Exception as exc:
        log.warning("startup: could not tighten %s permissions: %s", ASL_DVS_CONF, exc)

def startup() -> None:
    global DVS_PATH
    _harden_existing_conf_perms()
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
        threading.Thread(target=_phone_refresh_on_start, name="phone-refresh", daemon=True).start()
        if _ph_read(TONECODE_SCRIPT) is not None:
            _phone_req_dir()
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
        self._per_ip_lock  = threading.Lock()
        self._per_ip_count: Dict[str, int] = {}

    def _release_per_ip_slot(self, ip: str) -> None:
        with self._per_ip_lock:
            n = self._per_ip_count.get(ip, 1) - 1
            if n <= 0:
                self._per_ip_count.pop(ip, None)
            else:
                self._per_ip_count[ip] = n

    def verify_request(self, request, client_address) -> bool:
        ip = client_address[0]
        with self._per_ip_lock:
            if self._per_ip_count.get(ip, 0) >= _MAX_CONCURRENT_CONNECTIONS_PER_IP:
                log.warning("Per-IP connection cap (%d) reached, rejecting %s",
                            _MAX_CONCURRENT_CONNECTIONS_PER_IP, client_address)
                return False
            self._per_ip_count[ip] = self._per_ip_count.get(ip, 0) + 1
        if not self._conn_semaphore.acquire(blocking=False):
            log.warning("Connection cap (%d) reached, rejecting %s",
                        _MAX_CONCURRENT_CONNECTIONS, client_address)
            self._release_per_ip_slot(ip)
            return False
        return True

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._conn_semaphore.release()
            self._release_per_ip_slot(client_address[0])

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
    pad = " " * max(0, 32 - len(_cfg.asl_node))
    lpad = " " * max(0, 15 - len(str(_cfg.port)))
    npad = " " * max(0, 24 - len(ip) - len(str(_cfg.port)))
    _bridge_short_labels = ("Digital", "M17", "Phone", "Reserved")
    _bridge_lines = []
    for _i in range(BRIDGE_SLOT_COUNT):
        _val = _cfg.bridge_nodes[_i] or "—"
        _bpad = " " * max(0, 32 - len(_val))
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
║  Network   : http://{ip}:{_cfg.port}{npad}║
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