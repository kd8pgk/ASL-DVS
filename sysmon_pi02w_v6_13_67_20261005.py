#!/usr/bin/env python3
"""
ASL-DVS SYSMON  --  sysmon.py   (Pi Zero 2 W build)
Version : 6.13.67-pi02w  (20261005)
Authors : Claude AI (Anthropic) / KD8PGK
License : CC BY-NC 4.0
Nodes   : KD8PGK 652701 / 652702 / 652703

Changelog: the last 10 versions are below.  Older entries (v6.13.55 and
earlier) are in sysmon_changelog_v6_13_65_20261004.txt.

v6.13.67-pi02w -- Pi Zero 2 W build, branched from v6.13.67.  A lighter
sysmon for the Pi Zero 2 W (512 MB RAM, 4 slow cores): tabs are removed
in stages; everything else matches v6.13.67.
  Console tab removed: the in-browser Asterisk console (websocket,
  asterisk -rvvv, embedded xterm.js), every Troubleshooting check and the
  Page self-check.  Routes gone: /api/console/*, /static/xterm.js,
  /static/xterm.css, /static/addon-fit.js.  The D-Star card keeps its
  "Remote control listening" row (helpers moved into the card).
  Net tab removed: hostname / .local tools, mtr install, ping and trace
  to Google, allstarlink.org, DV hosts and reflectors.  Routes gone:
  /api/net, /api/net/run, /api/net/cancel.  The background job runner
  and /api/net/job stay -- Phone -> Modules "Reinstall" uses them.
  Reg tab removed: the HTTP and IAX2 registration check cards.  Routes
  gone: /api/reg/http, /api/reg/iax.  The shared check-list renderer
  stays (Phone uses it).
  Firewall tab removed: ufw / nftables / firewalld rule views and
  editing, raw ruleset, enable / disable.  Route gone: /api/firewall (GET
  and POST).  Ports -> port details loses its Firewall zone (state and
  Allow / Deny), so /api/ports no longer reads the firewall on every
  15 s refresh.  Phone's read-only "Pi firewall" checks stay; their fix
  hints now give the Cockpit / firewall-cmd / nftables / ufw step.
  Cleanup: section labels updated for the tabs that remain, tab colour
  map trimmed.  A saved enabled_tabs list that still names a removed tab
  is fine -- unknown tabs are dropped when the config is read.
  Result: 33,068 -> ~23,400 lines, page 440 -> 358 KB, 53 -> 42 GET and
  30 -> 22 POST routes.  Checks run each stage: pyflakes (clean),
  node --check, dead-code and reachability scans, --selftest, every GET
  route called directly, and every tab opened in Chromium (no errors).

v6.13.67 -- D-Star card: gatewayAddress row fixed.  gatewayAddress is the
Pi's own address that ircDDBGateway binds every socket to (DExtra, D-Plus,
DCS, G2 and remote control), not the router's.  Blank (or 0.0.0.0) now
passes -- it is the normal setting -- with a "don't forward the port" note
when remote control is on.  127.0.0.1 fails (blocks reflector and gateway
links) and an address this Pi doesn't have (e.g. the router's) fails
(ircDDBGateway can't bind it).  The row shows whatever the remote-control
setting, since the address covers every link.  v6.13.66 passed 127.0.0.1
and warned on blank.

v6.13.66 -- D-Star -- ircDDBGateway card (ASL-DVS tab).
For dashboard v9.3.71, whose D-STAR tab links to gateway callsigns as well
as reflectors.  A new card under "DVSwitch -- Config Files" reads
/etc/ircddbgateway and checks: ircddbgatewayd running, gatewayCallsign,
repeaterBand1 (shown as the 8-character callsign the dashboard uses),
ircddbEnabled (gateway lookup), dextraEnabled (gateway links), and remote
control -- remoteEnabled (WARN when off: the dashboard falls back to
dvswitch.sh tune), remotePassword set (never shown), remotePort valid and
listening (catches settings not yet applied by a restart), gatewayAddress
(WARN when blank: listens on every interface).  Buttons: Edit (the file
is now in the DVSwitch config-file list), Restart ircddbgatewayd (root),
Refresh, Copy.  Read-only -- nothing changes the file but the editor.
New route /api/dstar-gw (GET checks, POST restart), added to the Page
self-check.  Console -> Saved favorites now passes D-STAR gateway rows
("W1ABC BL") and treats the unpadded "W1ABCBL" as old form (the dashboard
fixes it on load).

v6.13.65 -- Console Dashboard checks, stage 4 of 4 (release).
Summary of v6.13.62-v6.13.64: a new "Dashboard" group in Console ->
Troubleshooting (before Sysmon) with three read-only checks for the
dashboard's v9.3.61-v9.3.69 refactor -- "Dashboard file check" (version,
compiles, functions defined twice, every page button's function present),
"Node search lists" (the astdb.txt and EchoLink lists the ASL and Echo
search cards use) and "Saved favorites" (each saved ASL, Echo, D-STAR and
XLX row in asl_dvs.conf).  None connects to port 8989.  Run all goes from
33 to 36 checks (the Console keeps 40 results).  The Page self-check is
unchanged: it reads tab data routes, and these checks already run through
/api/console/tcatalog, which it covers.  Changelog entries v6.13.52-
v6.13.55 moved to sysmon_changelog_v6_13_65_20261004.txt.  Checks run:
py_compile, pyflakes (no new warnings), duplicate-function scan, node
--check, --selftest, and tests of each new check against dashboard
v9.3.60 and v9.3.69, broken copies (a missing page function, a file that
won't compile), sample astdb.txt / echolink dbdump output, and a sample
asl_dvs.conf with good, old-form, duplicate, bridge and bad rows.

v6.13.64 -- Console Dashboard checks, stage 3 of 4: Saved favorites.
"Saved favorites" reads asl_dvs.conf and checks every saved ASL, Echo,
D-STAR and XLX row: node numbers are 1-7 digits, no bridge or phone node
is saved as a favorite, nothing is saved twice, ASL/Echo rows past slot 10
(not loaded) are flagged, D-STAR rows are the 6-character base + module +
L (REF/XRF/DCS + 3 digits), XLX rows are XLX + 3 + module + L, and old
4-field XLX rows (skipped when the dashboard loads) are flagged.  Run it
after tapping Save on the dashboard to see the row landed right.

v6.13.63 -- Console Dashboard checks, stage 2 of 4: Node search lists.
"Node search lists" shows what the dashboard's ASL and Echo search cards
(dashboard v9.3.61/62) have to search: astdb.txt found, its date and how
many nodes it holds (read the way the dashboard reads it), the EchoLink
stations logged in now (asterisk -rx "echolink dbdump"), and the bridge
and phone nodes the dashboard leaves out of both searches.

v6.13.62 -- Console Dashboard checks, stage 1 of 4: Dashboard file check.
New "Dashboard" group in Troubleshooting (before Sysmon).  "Dashboard
file check" reads the installed asl_dvs_dashboard.py (never connects to
port 8989): shows its version (WARN if older than 9.3.69), compiles it in
memory (nothing written to the SD card), flags a function defined twice,
and checks that every on...= handler on the dashboard page names a
function the page script defines -- a renamed or removed function there
breaks a button.  _ts_dash_version() now finds the file through the new
shared _ts_dash_paths().  BUILD_DATE was a release behind; now 20261004.

v6.13.61 -- rpt.conf templates, stage 3 of 3: Console reader.
_ts_rpt_sections() (used by the Console's Bridge port check, Bridge
traffic and Stuck autopatch) now keeps the last value when a setting appears twice
in one section, as Asterisk does -- it used to keep the first.  It also
skips ;-- ... --; block comments instead of reading the lines inside.

v6.13.60 -- rpt.conf templates, stage 2 of 3: Console check.  New
"Template values" button in Troubleshooting -> Links: for each node it
lists the settings that come only from a template such as [node-main],
marks the ones the sysmon tabs read (callsign, idrecording, idtalkover,
rxchannel, statpost_url and the four DTMF settings) and fails any node
whose template isn't defined above it in rpt.conf.

v6.13.59 -- rpt.conf templates, stage 1 of 3: shared scanner.
_rpt_scan() now reads rpt.conf the way Asterisk does (checked against
Asterisk's main/config.c): a node's template values go in first, then
its own lines, and the last value wins -- so the node's own line beats
the template, and with two templates the second beats the first.
Templates of templates work, as does [name](!,base); a template must be
defined above the node that uses it.  ;-- ... --; block comments are now
skipped (a line inside one used to be read as a setting).  This changes
what the ASL-DVS rpt.conf card, the Reg tab, the DVSM tab, the M17 and
Zello rpt.conf checks, the header callsign and the Security identity
show when a value is set only in the template.  Checked: output
identical to v6.13.58 on sample files with no templates or block
comments; new cases (value only in template, node overrides, two
templates, template of template, missing template, block comments)
give Asterisk's answer.  #include lines are still not followed by this
scanner (the Phone tab and Node Settings reader does follow them).

v6.13.58 -- Refactor by tab and card, stage 6 of 6 (release).
Summary of v6.13.51-v6.13.57: a dead-code scan found nothing unused that
is safe to delete (the 58 decorator-registered Phone/Console checks and
the two web-server overrides only look unused; /api/dashboard-status,
/api/appconf/files and /api/abinfo are kept on purpose).  The code is now
grouped by tab, then by card, with no change to what any tab shows or
does.  Changelog entries before v6.13.49 moved to the separate file
sysmon_changelog_v6_13_58_20261004.txt (shipped with this file); the last
10 versions stay here.  _RADIO_TUNE_DRIVERS was checked and kept as is --
it is the allowlist the Tune save checks, and one item is correct today.
Checks run on every stage: py_compile, pyflakes (no new warnings), a
before/after comparison of every top-level statement and every module
value (route tables, Phone sections, Console checks, security checks),
the page outside the script byte-identical, every script statement
present once with non-function statements in the same order, node
--check, and --selftest.

v6.13.57 -- Refactor stage 5 of 6: Console.  The Troubleshooting checks
are grouped by their button group (Links, Bridges, Phone, Asterisk, Pi
health, Network, Sysmon), each helper beside the group that uses it;
helpers used by several groups come first.  Buttons, their order in
each group, and Run all are unchanged (checked against the old
catalog).  The unused "order" list in /api/console/tcatalog now follows
group order -- the page doesn't read it.  _ts_netcheck split into
_ts_nc_state, _ts_nc_network and _ts_nc_bridges.

v6.13.56 -- Refactor stage 4 of 6: Phone.  _phone_sec_health split into
_phone_health_nodes, _phone_health_files, _phone_health_live and
_phone_health_routes; _ph_hoip_checks split into _ph_hoip_server_ports,
_ph_hoip_transport_auth, _ph_hoip_signin and _ph_hoip_network_vm.  The
splits are mechanical (same statements, values passed in and out).
Health, HOIP and Netcheck output compared old vs new over 80 mocked
system states each (sample rpt/extensions/pjsip/iax files, canned
command output): identical.
"""

import argparse
import codecs
import configparser
import fcntl
import gzip
import hmac
import io
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

VERSION      = "6.13.67-pi02w"
BUILD_DATE   = "20261005"

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
            "asl_dvs_dashboard.service | ASL+DVSwitch Dashboard | - | 8989 | tcp\n"
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

        "enabled_tabs": "overview,services,ports,journal,asldvs,phone,tune,hardware,dvsm,stfu,m17,zello,sdcard,security,edit",
    },
}

_log_buf: deque = deque(maxlen=LOG_MAXLEN)
_log_idx: int   = 0
_log_lock       = threading.Lock()

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
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        st = os.stat(path)
        mode, owner = st.st_mode & 0o7777, (st.st_uid, st.st_gid)
    except FileNotFoundError:
        mode, owner = 0o666 & ~_process_umask(), None
    try:
        tmp.unlink(missing_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            if owner is not None and os.geteuid() == 0:
                os.fchown(fh.fileno(), *owner)
            os.fchmod(fh.fileno(), mode)
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError as e:
            log.debug("_atomic_write cleanup: %s", e)
        raise

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
    "asl_dvs_dashboard.service",
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

def get_live_registrations() -> dict:

    out, err = _run_with_stderr(["asterisk", "-rx", "rpt show registrations"], timeout=8)
    if not out:
        return {
            "ok": False, "raw": "",
            "error": err or "no output — asterisk CLI may not be answering",
            "nodes": {},
        }

    nodes: "dict[str, str]" = {}
    for line in out.splitlines():
        m = _REG_LIVE_NODE_RE.search(line)
        if not m:
            continue
        node = m.group(1)
        low  = line.lower()
        if any(w in low for w in _REG_LIVE_BAD_WORDS):
            nodes[node] = "unregistered"
        elif "regist" in low:
            nodes[node] = "registered"
        else:
            nodes[node] = "unknown"
    return {"ok": True, "raw": out, "error": None, "nodes": nodes}

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
_ZELLO_SERVICE_PATHS = [
    Path("/etc/systemd/system/asl-zello-bridge.service"),
    Path("/lib/systemd/system/asl-zello-bridge.service"),
]
_ZELLO_VENV_BIN      = Path("/opt/asl-zello-bridge/venv/bin/asl-zello-bridge")

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

def _bg_poll_loop() -> None:
    _log("bg_poll: started")
    
    _sd_notify("READY=1")
    poll_count = 0
    while True:
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
                try:
                    rl = get_live_registrations()
                    _update_state(reg_live=rl)
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
        
        _sd_notify("WATCHDOG=1")
        time.sleep(10)

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>ASL-DVS SYSMON</title>
<style>

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
  
  --text:#d0dff0;--text-bright:#f0f8ff;
  --sans:Arial,Helvetica,sans-serif;
  
  --fs-xs:.75rem;    
  --fs-sm:.75rem;    
  --fs-base:.85rem;  
  --fs-md:.9rem;     
  --fs-lg:1rem;      
  --fs-xl:1.2rem;    
  
  --ov-btns-w:290px;
}

*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--sans);
     height:100vh;height:100dvh;  
     overflow:hidden;display:flex;flex-direction:column}

header{background:linear-gradient(90deg,#0f1a2e,#161e2e 50%,#0f1a2e);
  border-bottom:2px solid var(--amber);padding:.75rem 1rem;
  display:flex;align-items:center;flex-shrink:0;
  box-shadow:0 2px 0 rgba(255,208,64,.25),0 6px 30px rgba(0,0,0,.7)}
.logo{font-family:var(--sans);font-size:1.21rem;color:var(--amber);
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
#wfm-shutdown-hdr{font-family:var(--sans);font-size:.88rem;letter-spacing:.22em;
  text-transform:uppercase;color:var(--red);text-shadow:0 0 12px rgba(255,61,90,.8)}
#wfm-shutdown-msg{font-family:var(--sans);font-size:1.02rem;color:#ffb0b8;line-height:1.6}
#wfm-shutdown-sub{font-family:var(--sans);font-size:.74rem;color:#c98a92;letter-spacing:.03em}

#login-screen{display:none;position:fixed;inset:0;z-index:9999;
  align-items:center;justify-content:center;
  background:rgba(4,7,13,.86);backdrop-filter:blur(2px)}
#login-screen.open{display:flex}
#login-card{width:90%;max-width:320px;background:var(--panel,#141a24);
  border:1px solid var(--border,#2a3444);border-radius:10px;
  padding:1.4rem 1.3rem;box-shadow:0 12px 40px rgba(0,0,0,.5);
  font-family:var(--sans)}
#login-card h2{margin:0 0 .2rem;font-size:1.05rem;color:var(--amber,#ffd040);
  letter-spacing:.02em}
#login-card p.sub{margin:0 0 1rem;font-size:.8rem;color:var(--muted,#8a95a8)}
#login-card label{display:block;font-size:.78rem;color:var(--muted,#8a95a8);
  margin-bottom:.3rem}
#login-pw{width:100%;box-sizing:border-box;padding:.55rem .6rem;
  background:var(--bg,#0b0f16);border:1px solid var(--border,#2a3444);
  border-radius:6px;color:#fff;font-size:.92rem;font-family:var(--sans)}
#login-pw:focus{outline:none;border-color:var(--amber,#ffd040)}
#login-btn{width:100%;margin-top:.8rem;padding:.6rem;border:none;border-radius:6px;
  background:var(--amber,#ffd040);color:#1a1300;font-weight:600;font-size:.88rem;
  cursor:pointer}
#login-btn:disabled{opacity:.5;cursor:default}
#login-btn:hover:not(:disabled){filter:brightness(1.08)}
#login-err{min-height:1.1rem;margin-top:.6rem;font-size:.78rem;color:var(--red)}

#offline-bar{display:none;position:fixed;top:0;left:0;right:0;z-index:1000;
  background:#3a0a0a;border-bottom:1px solid #8b1a1a;color:#ff6b6b;
  font-family:var(--sans);font-size:var(--fs-base);text-align:center;
  padding:.35rem 1rem;letter-spacing:.06em}
body.offline #offline-bar{display:block}

#toast-stack{position:fixed;bottom:1.5rem;right:1.2rem;display:flex;
  flex-direction:column-reverse;gap:.45rem;z-index:1200;pointer-events:none;
  max-width:92vw}
.toast-item{background:#1a2438;border:1px solid var(--border2);border-radius:8px;
  padding:.55rem 1.2rem;font-family:var(--sans);font-size:.924rem;
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

.ov-name{font-family:var(--sans);font-size:.902rem;font-weight:bold;
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

.ov-mode{font-family:ui-monospace,Menlo,Consolas,monospace;
  font-size:var(--fs-xs);color:#fff;letter-spacing:-.02em;
  text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ov-mode.perm-warn{color:var(--amber)}
.ov-mode.perm-fail{color:var(--red);text-shadow:0 0 6px rgba(255,61,90,.4)}
.ov-owner.sec-link,.ov-mode.sec-link{cursor:pointer;text-decoration:underline;
  text-decoration-style:dotted;text-underline-offset:2px}

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
  display:flex;align-items:center;gap:.5rem}
#ov-global-lbl{font-family:var(--sans);font-size:var(--fs-xs);letter-spacing:.2em;
  text-transform:uppercase;color:#fff}

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
#dpanel-unit{font-family:var(--sans);font-size:1rem;
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
.dp-own-val{font-family:ui-monospace,Menlo,Consolas,monospace;
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

.pt-controls{display:flex;align-items:center;gap:.4rem;
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
  grid-template-columns:10px 70px 48px 1fr 58px 1fr auto;
  align-items:center;gap:.55rem;padding:.38rem .9rem;
  border-top:1px solid var(--border)}
.pt-table-hdr{background:#131c2d;border-top:none;
  font-family:var(--sans);font-size:var(--fs-xs);
  letter-spacing:.2em;text-transform:uppercase;color:#fff;cursor:default}
.pt-row{cursor:pointer;transition:background .1s}
.pt-row:hover{background:var(--surface2)}
.pt-port{font-family:var(--sans);font-size:.902rem;
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
.jl-name{font-family:var(--sans);font-size:.902rem;font-weight:bold;
  color:var(--text-bright);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.jl-state{font-family:var(--sans);font-size:var(--fs-sm)}
.jl-btn{font-family:var(--sans);font-size:var(--fs-xs);color:var(--purple);
  border:1px solid var(--purple-dim);border-radius:3px;
  padding:.15rem .45rem;background:transparent;cursor:pointer;
  white-space:nowrap;transition:all .14s}
.jl-btn:hover{filter:brightness(1.6)}

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

#jp-toolbar{display:flex;align-items:center;gap:.4rem;
  padding:.35rem 1rem;background:#131c2d;
  border-bottom:1px solid var(--border);flex-shrink:0}
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
.ed-inp{font-family:var(--sans);font-size:.946rem;padding:.3rem .48rem;
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
#allconf-textarea{flex:1;background:#0a1020;color:#c8d8e8;
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
#modal-msg{font-family:var(--sans);font-size:.946rem;
  color:var(--text-bright);line-height:1.55;margin-bottom:1.2rem}
#modal-btns{display:flex;justify-content:flex-end;gap:.55rem}

.ast-row{display:grid;grid-template-columns:1fr auto;
  align-items:center;gap:.55rem;padding:.42rem .9rem;
  border-top:1px solid var(--border);
  cursor:pointer;transition:background .1s;user-select:none}
.ast-row:hover{background:var(--surface2)}
.ast-name{font-family:var(--sans);font-size:.902rem;
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

.ph-note{padding:.6rem .9rem;font-family:var(--sans);font-size:var(--fs-sm);color:#9fb4cc}
.ph-ro{padding:.4rem .9rem;font-family:var(--sans);font-size:var(--fs-xs);color:#9fb4cc;border-bottom:1px solid var(--border)}
.ph-blk{border-top:1px solid var(--border);padding-bottom:.35rem}
.ph-blk:first-child{border-top:none}
.ph-blk-hdr{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;padding:.45rem .9rem 0;font-family:var(--sans);font-size:var(--fs-sm);font-weight:bold;color:#fff}
.ph-kv{display:grid;grid-template-columns:minmax(110px,32%) 1fr;gap:.18rem .8rem;padding:.35rem .9rem 0;font-family:var(--sans);font-size:var(--fs-sm)}
.ph-kv .k{color:#9fb4cc;font-size:var(--fs-xs)}
.ph-kv .v{color:#fff;word-break:break-word}
.ph-pre{margin:.3rem .9rem .3rem;padding:.4rem .6rem;background:#0b1622;border:1px solid var(--border);border-radius:3px;font-family:monospace;font-size:var(--fs-xs);color:#cfe3ff;white-space:pre-wrap;word-break:break-all}
.ph-tbl{width:100%;border-collapse:collapse;font-family:var(--sans);font-size:var(--fs-sm);color:#fff}
.ph-tbl th{text-align:left;font-size:var(--fs-xs);font-weight:normal;color:#9fb4cc;padding:.3rem .9rem;border-bottom:1px solid var(--border)}
.ph-tbl td{padding:.3rem .9rem;border-top:1px solid var(--border)}
.ph-tbl tr:first-child td{border-top:none}
.ph-link{display:inline-block;text-decoration:none}
.pm-ok{color:var(--green)}
.pm-bad{color:var(--red)}
.pm-warn{color:var(--orange)}
.pm-dim{color:#9fb4cc}
.pm-btns{display:flex;flex-wrap:wrap;gap:.25rem}
.pm-btns .btn:disabled{opacity:.35;cursor:default}
.ph-sub{padding:.5rem .9rem .1rem;font-family:var(--sans);font-size:var(--fs-xs);letter-spacing:.2em;text-transform:uppercase;color:#9fb4cc}
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
.hw-check-icon{font-size:1rem;text-align:center;width:20px;flex-shrink:0}
.hw-check-icon.ok{color:var(--green);text-shadow:0 0 6px rgba(0,255,176,.5)}
.hw-check-icon.fail{color:var(--red);text-shadow:0 0 6px rgba(255,61,90,.5)}
.hw-check-icon.warn{color:var(--amber);text-shadow:0 0 6px rgba(255,208,64,.5)}
.hw-check-icon.pend{color:#fff}
.hw-check-label{color:var(--text-bright);font-size:var(--fs-base)}
.hw-check-detail{font-size:var(--fs-xs);color:#fff;
  text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hw-check-detail.ok{color:#007a50}
.hw-check-detail.warn{color:#7a5800}
.hw-check-detail.fail{color:#7a2030}

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

#uf-textarea{flex:1;background:#0a1020;color:#c8d8e8;
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

.stfu-bm-bar{display:flex;align-items:center;justify-content:space-between;
  padding:.42rem .9rem;
  background:linear-gradient(90deg,rgba(0,191,255,.06),rgba(0,191,255,.03));
  border-bottom:1px solid rgba(0,191,255,.15)}
.stfu-bm-bar-left{display:flex;align-items:center;gap:.55rem}
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
  color:#c8d8e8;padding:.7rem .9rem;background:#080e18;
  margin:0;white-space:pre;overflow-x:auto;display:block}
.stfu-ini-section{color:var(--blue)}
.stfu-ini-key{color:var(--teal)}
.stfu-ini-ph{color:#fff;font-style:italic}   

.stfu-editor-wrap{overflow:hidden;transition:max-height .3s ease;max-height:0}
.stfu-editor-wrap.open{max-height:600px}
#stfu-textarea{width:100%;background:#0a1020;color:#c8d8e8;
  font-family:var(--sans);font-size:var(--fs-base);line-height:1.65;
  border:none;outline:none;padding:.8rem 1rem;
  resize:none;tab-size:4;white-space:pre;overflow:auto;
  min-height:260px;display:block}
.stfu-editor-bar{display:flex;align-items:center;gap:.4rem;
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
.hw-pwr-flag.clear{color:#2a4060;border-color:#1a2a40}

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

.sec-summary{display:flex;align-items:center;gap:.8rem;flex-wrap:wrap;
  padding:.5rem .9rem;background:#131c2d;
  border:1px solid var(--border2);border-radius:4px;margin-bottom:.6rem;
  font-family:var(--sans);font-size:var(--fs-base)}
.sec-sum-item{display:flex;align-items:center;gap:.3rem;font-size:var(--fs-xs);
  letter-spacing:.1em;text-transform:uppercase;color:#fff}
.sec-sum-n{font-size:var(--fs-md);font-weight:bold}
.sec-sum-n.pass{color:var(--green)}
.sec-sum-n.warn{color:var(--orange)}
.sec-sum-n.fail{color:var(--red)}
.sec-sum-n.other{color:var(--text-bright)}
.sec-sum-ts{margin-left:auto;color:#fff;font-size:var(--fs-xs)}

#panel-security .s3-card-meta{margin-left:.5rem}
.sec-scope-note{padding:.35rem .9rem .55rem;color:#fff;
  font-family:var(--sans);font-size:var(--fs-xs);line-height:1.5}

.sec-row-actions{display:flex;align-items:center;gap:.35rem;
  justify-content:flex-end;min-width:0}
.sec-row-detail{font-size:var(--fs-xs);color:#fff;text-align:right;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:28ch}
.sec-row-detail.ok{color:#007a50}
.sec-row-detail.warn{color:#7a5800}
.sec-row-detail.fail{color:#7a2030}
.sec-sev{font-size:var(--fs-xs);letter-spacing:.08em;text-transform:uppercase;
  border:1px solid var(--border2);border-radius:3px;padding:0 .25rem;color:#fff}
.sec-sev.high{color:var(--red);border-color:var(--red)}
.sec-sev.medium{color:var(--orange);border-color:var(--orange)}
.sec-sev.low{color:#fff}
.ast-toggle.on{color:var(--text-bright);border-color:var(--teal)}

.sec-note{white-space:normal;line-height:1.55;
  background:#0b1420;border-top:1px solid var(--border);
  padding:.45rem .9rem .55rem 2.2rem}
.sec-note-h{display:block;color:var(--teal);font-size:var(--fs-xs);
  letter-spacing:.14em;text-transform:uppercase;margin:.35rem 0 .15rem}
.sec-note-h:first-child{margin-top:0}
.sec-note-raw{white-space:pre-wrap;word-break:break-word;
  font-family:var(--sans);font-size:var(--fs-xs);
  color:var(--text);background:#070d16;border:1px solid var(--border);
  border-radius:3px;padding:.4rem .5rem;margin-top:.2rem;
  max-height:16rem;overflow:auto}
.sec-note-p{white-space:pre-wrap;display:block;margin:0 0 .1rem}
.sec-refs{display:block;margin-top:.15rem}
.sec-refs a{color:var(--teal);text-decoration:none;display:block;
  padding:.08rem 0;word-break:break-word}
.sec-refs a:hover{text-decoration:underline}
.sec-refs .sec-ref-plain{display:block;padding:.08rem 0;color:#fff}
.sec-cmd{font-family:var(--sans);color:var(--teal);
  background:#0b1420;border:1px solid var(--border);border-radius:3px;
  padding:0 .25rem}
.sec-redacted{color:var(--green);font-size:var(--fs-xs)}
.sec-busy{opacity:.55;pointer-events:none}
</style>
</head>
<body>

<div id="login-screen">
  <div id="login-card">
    <h2>ASL-DVS SysMon</h2>
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
    <div class="logo">ASL-DVS SYSMON</div>
    <div class="logo-sub">
      <span id="hdr-callsign">KD8PGK</span>
      <span style="color:#6b4800"> · </span>
      <span>Node </span><span id="hdr-node">…</span>
    </div>
  </div>
  <div id="hdr-right">
    <span id="hdr-uptime">UP 0:00:00</span>
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
     title="Return to ASL-DVS Dashboard" target="_self" onclick="pauseAllPolling()">Node Control</a>
</div>

<div id="zone-status">
  <div class="sf"><span class="sl">Host</span><span class="sv cyan" id="s-host">…</span></div>
  <div class="sf"><span class="sl">Load</span><span class="sv" id="s-load">…</span></div>
  <div class="sf"><span class="sl">Mem</span><span class="sv" id="s-mem">…</span></div>
  <div class="sf sf-temp"><span class="sl">Temp</span><span class="sv" id="s-temp">—</span></div>
  <div class="sf"><span class="sl">Pwr</span><span class="sv" id="s-volt" title="Power health — vcgencmd get_throttled">—</span></div>
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
  <button class="tab-btn"        id="tbtn-zello"
    onclick="switchTab('zello','255,140,0')">Zello</button>
  <button class="tab-btn"        id="tbtn-sdcard"
    onclick="switchTab('sdcard','180,140,255')">SD Card</button>
  <button class="tab-btn"        id="tbtn-security"
    onclick="switchTab('security','255,90,120')">Security</button>
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
          <span class="ph-note">Start a Test call on the dashboard Phone tab first, then press this. It counts packets in and out over 4 seconds.</span></div>
        <div id="rt-audio-box"></div>
        <div class="ph-sub">3 · Coming in</div>
        <div class="ph-nocopy" style="margin:.3rem 0"><button class="btn btn-muted btn-sm" onclick="rtIn(true)">Start watching (10 min)</button>
          <button class="btn btn-muted btn-sm" onclick="rtIn(false)">Check</button>
          <span class="ph-note">Have another Hams Over IP member call your extension while watching.</span></div>
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

  <div id="panel-zello" class="tab-panel">

    <div class="stfu-tab-hdr">
      <span class="stfu-tab-title">Zello — asl-zello-bridge</span>
      <button class="btn btn-blue btn-sm" onclick="loadZello()">↻ Refresh</button>
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
        <span class="dpbadge" id="zello-badge-install">—</span>
      </div>
      <div id="zello-body-install">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr" style="padding-left:.6rem">
        <div style="display:flex;align-items:center;gap:.55rem">
          <div class="dvsm-accent" style="background:var(--teal)"></div>
          <div>
            <div class="dvsm-card-title" style="color:var(--teal)">Live Status</div>
            <div class="dvsm-card-sub">From journal — not just process state</div>
          </div>
        </div>
        <button class="btn btn-muted btn-sm" onclick="openServicePanel('asl-zello-bridge','Zello Bridge')">
          Full Journal ↗</button>
      </div>
      <div id="zello-body-status">
        <div class="stub-panel" style="min-height:60px">Loading…</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr" style="padding-left:.6rem">
        <div style="display:flex;align-items:center;gap:.55rem">
          <div class="dvsm-accent" style="background:var(--blue)"></div>
          <div>
            <div class="dvsm-card-title" style="color:var(--blue)">Configuration</div>
            <div class="dvsm-card-sub" id="zello-config-path">systemd override — Free mode</div>
          </div>
        </div>
        <span class="dpbadge" id="zello-badge-config">—</span>
      </div>
      <div id="zello-body-config">
        <div class="stub-panel" style="min-height:140px">Loading…</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr" style="padding-left:.6rem">
        <div style="display:flex;align-items:center;gap:.55rem">
          <div class="dvsm-accent" style="background:var(--red)"></div>
          <div>
            <div class="dvsm-card-title" style="color:var(--red)">Compatibility Checks</div>
            <div class="dvsm-card-sub">USRP ports · rpt.conf [1918] · credentials</div>
          </div>
        </div>
      </div>
      <div id="zello-body-compat">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="stfu-sample-hdr">
        <span class="stfu-sample-title">Sample Override</span>
        <div class="stfu-sample-btns">
          <button class="btn btn-muted btn-sm"
            onclick="zelloCopySample(this)">⎘ Copy Sample</button>
          <button class="btn btn-blue btn-sm"
            onclick="zelloOpenEditor()">✎ Edit Override</button>
        </div>
      </div>
      <div class="dvsm-card-sub" style="padding:.3rem .6rem 0">
        Reference only — shows every known key with placeholders for anything unset.
        Use Edit Override to change the real, currently-active values.
      </div>
      <div id="zello-body-sample">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>

    <div class="s3-card" style="margin-bottom:1rem">
      <div class="s3-card-hdr" style="padding-left:.6rem">
        <div style="display:flex;align-items:center;gap:.55rem">
          <div class="dvsm-accent" style="background:var(--amber)"></div>
          <div>
            <div class="dvsm-card-title" style="color:var(--amber)">Edit Override</div>
            <div class="dvsm-card-sub" id="zello-editor-path">—</div>
          </div>
        </div>
        <button class="btn btn-muted btn-sm" id="zello-editor-toggle"
          onclick="zelloToggleEditor()">▼ Expand</button>
      </div>
      <div class="stfu-editor-wrap" id="zello-editor-wrap">
        <div style="padding:.5rem .6rem;font-family:var(--sans);font-size:var(--fs-xs);
          color:var(--amber);border-bottom:1px solid rgba(255,255,255,.06)">
          ⚠ This is the real, active systemd override — including the plaintext
          password. Save writes it to disk immediately; changes don't take effect
          until you Restart below.
        </div>
        <textarea id="zello-textarea" spellcheck="false"></textarea>
        <div class="stfu-editor-bar">
          <button class="btn btn-sm" style="color:var(--blue);border-color:var(--blue-dim)"
            onclick="zelloAction('start')">▶ Start</button>
          <button class="btn btn-sm" style="color:var(--red);border-color:var(--red-dim,var(--red))"
            onclick="zelloAction('stop')">⏹ Stop</button>
          <button class="btn btn-sm" style="color:var(--green);border-color:var(--green-dim)"
            onclick="zelloAction('restart')">↺ Restart</button>
          <button class="btn btn-blue btn-sm"
            onclick="zelloSave()">💾 Save</button>
          <button class="btn btn-muted btn-sm"
            onclick="zelloCopy()">⎘ Copy</button>
          <button class="btn btn-muted btn-sm"
            onclick="zelloDiscardEdit()">✕ Close</button>
          <span style="font-family:var(--sans);font-size:var(--fs-xs);
            color:#fff;margin-left:auto">
            Save then Restart to apply changes
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

  <div id="panel-security" class="tab-panel">

    <div class="sec-summary">
      <span class="sec-sum-item">Pass <span class="sec-sum-n pass" id="sec-n-pass">–</span></span>
      <span class="sec-sum-item">Warn <span class="sec-sum-n warn" id="sec-n-warn">–</span></span>
      <span class="sec-sum-item">Fail <span class="sec-sum-n fail" id="sec-n-fail">–</span></span>
      <span class="sec-sum-item">Checks <span class="sec-sum-n other" id="sec-n-total">–</span></span>
      <button class="btn btn-muted btn-sm" id="sec-rerun-all"
              onclick="secRerun()">&#8635; Re-run checks</button>
      <span class="sec-sum-ts" id="sec-last-run">not run yet</span>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">DVSwitch</span>
        <span class="reg-card-status" id="sec-status-dvswitch">&mdash;</span>
        <span class="s3-card-meta" id="sec-meta-dvswitch">&mdash;</span>
        <div style="display:flex;gap:.3rem;margin-left:auto">
          <button class="btn btn-muted btn-sm sec-card-rerun"
                  onclick="secRerun()">&#8635; Re-run</button>
        </div>
      </div>
      <div id="sec-body-dvswitch">
        <div class="stub-panel" style="min-height:60px">Loading&hellip;</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">AllStarLink</span>
        <span class="reg-card-status" id="sec-status-asl">&mdash;</span>
        <span class="s3-card-meta" id="sec-meta-asl">&mdash;</span>
        <div style="display:flex;gap:.3rem;margin-left:auto">
          <button class="btn btn-muted btn-sm sec-card-rerun"
                  onclick="secRerun()">&#8635; Re-run</button>
        </div>
      </div>
      <div id="sec-body-asl">
        <div class="stub-panel" style="min-height:60px">Loading&hellip;</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">usrp2m17</span>
        <span class="reg-card-status" id="sec-status-usrp2m17">&mdash;</span>
        <span class="s3-card-meta" id="sec-meta-usrp2m17">&mdash;</span>
        <div style="display:flex;gap:.3rem;margin-left:auto">
          <button class="btn btn-muted btn-sm sec-card-rerun"
                  onclick="secRerun()">&#8635; Re-run</button>
        </div>
      </div>
      <div id="sec-body-usrp2m17">
        <div class="stub-panel" style="min-height:60px">Loading&hellip;</div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Cross-cutting</span>
        <span class="reg-card-status" id="sec-status-cross-cutting">&mdash;</span>
        <span class="s3-card-meta" id="sec-meta-cross-cutting">&mdash;</span>
        <div style="display:flex;gap:.3rem;margin-left:auto">
          <button class="btn btn-muted btn-sm sec-card-rerun"
                  onclick="secRerun()">&#8635; Re-run</button>
        </div>
      </div>
      <div id="sec-body-cross-cutting">
        <div class="stub-panel" style="min-height:60px">Loading&hellip;</div>
      </div>
    </div>

    <div class="sec-scope-note">
      Passive checks only &mdash; every result above comes from config files,
      /sys, /proc, <span class="sec-cmd">ss -tlnpu</span> and
      systemd state. This tab never connects to AMI, M17, USRP or the
      dashboard, so running it cannot pollute security.log or trip fail2ban.
      Checks that read credentials report booleans only; no secret value is
      sent to this page.
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
        <label class="tab-vis-lbl" title="Only shown while asl-zello-bridge is actually installed, regardless of this checkbox">
          <input type="checkbox" id="tabchk-zello" value="zello" onchange="edTabVisChanged()">Zello</label>
        <label class="tab-vis-lbl">
          <input type="checkbox" id="tabchk-sdcard" value="sdcard" onchange="edTabVisChanged()">SD Card</label>
        <label class="tab-vis-lbl">
          <input type="checkbox" id="tabchk-security" value="security" onchange="edTabVisChanged()">Security</label>
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
      <span class="ed-collapsible-title">ASL-DVS Config Files</span>
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
      <div style="font-weight:600;font-size:1rem;margin-bottom:0.8rem" id="radio-dialog-hdr">Save to Radio Preset</div>
      <div style="margin-bottom:1rem;font-size:0.9rem;color:#fff">
        <div id="radio-dialog-msg" style="margin-bottom:0.8rem">Enter a name for this preset:</div>
        <input type="text" id="radio-dialog-title" placeholder="e.g., Main, Mobile, Test…"
          style="width:100%;padding:0.5rem;border:1px solid var(--border2);border-radius:0.3rem;font-family:var(--sans);font-size:0.9rem;box-sizing:border-box"
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

      <div id="radio-dialog-error" style="display:none;font-size:var(--fs-base);color:#f88;margin-bottom:0.7rem"></div>

      <div style="display:flex;justify-content:flex-end;gap:0.5rem">
        <button class="btn btn-muted btn-sm" onclick="closeRadioDialog()">Cancel</button>
        <button class="btn btn-green btn-sm" id="radio-dialog-save-btn" onclick="confirmRadioDialog()">Save</button>
      </div>
    </div>

    <div id="radio-dialog-restart-view" style="display:none;text-align:center">
      <div style="font-weight:600;font-size:1rem;margin-bottom:0.6rem">⚠ Asterisk is restarting</div>
      <div style="font-size:0.9rem;color:#fff;margin-bottom:1rem">node will be briefly offline</div>
      <div style="width:2rem;height:2rem;border:3px solid var(--border2);border-top-color:var(--teal);
        border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 1rem"></div>
      <div id="radio-dialog-restart-msg" style="font-size:var(--fs-base);color:#f88;display:none;margin-bottom:0.8rem"></div>
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

    <div class="dpzone-lbl">Status</div>
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


const TABS = ["overview","services","ports","journal","asldvs","phone","tune","hardware","dvsm","stfu","m17","zello","sdcard","security","edit"];

let _enabledTabSet = new Set(TABS);

let _savedEnabledTabs = TABS.slice();
let _zelloInstalled   = false;

let _ptRefreshTimer  = null;
let _phRefreshTimer  = null;
let _s3RefreshTimer  = null;
let _sdTestTimer = null;
let _statusPollTimer = null;

function _applyTabVisibilityGated() {
  const list = _savedEnabledTabs.filter(t => t !== "zello" || _zelloInstalled);
  applyTabVisibility(list);
}


function stopTabPolling(tab) {
  let cleared = false;
  if (tab === "ports"    && _ptRefreshTimer) { clearInterval(_ptRefreshTimer); _ptRefreshTimer = null; cleared = true; }
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

  if (typeof d.zello_installed === "boolean" && d.zello_installed !== _zelloInstalled) {
    _zelloInstalled = d.zello_installed;
    _applyTabVisibilityGated();
  }

  window._portConflicts = d.port_conflicts || {};

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

function _ovSecurityJump(checkId) {
  if (!_enabledTabSet.has("security")) return;
  switchTab("security", "255,90,120");
  setTimeout(() => {
    if (typeof secToggle === "function" && !_secOpen.has(checkId + ":why")) {
      secToggle(checkId, "why");
    }
    document.getElementById("sec-row-" + checkId)
            ?.scrollIntoView({block: "center", behavior: "smooth"});
  }, 350);
}

function _ovWireSecurityJump(el, checkId, why) {
  if (!_enabledTabSet.has("security")) return;
  el.classList.add("sec-link");
  el.title = (el.title ? el.title + "\n\n" : "") + why;
  el.onclick = e => { e.preventDefault(); e.stopPropagation(); _ovSecurityJump(checkId); };
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
  if (svc.owner_is_root && !svc.owner_exempt) {
    _ovWireSecurityJump(el, "service_nonroot",
                         "Click for the Security tab's explanation");
  }
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
  if (svc.perm_verdict === "fail" || svc.perm_verdict === "warn") {
    _ovWireSecurityJump(el, "unit_file_perms",
                         "Click for the Security tab's explanation");
  }
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

let _dpUnit       = "";
let _dpActiveView = "";
let _dpOriginTab  = "";
const TAB_RGB = {
  overview:"0,255,229", services:"0,255,229", ports:"34,212,255",
  journal:"212,102,255", asldvs:"255,61,90", phone:"0,255,176",
  tune:"255,68,204", hardware:"0,200,120", dvsm:"255,170,34",
  stfu:"0,191,255", zello:"255,140,0", sdcard:"180,140,255", edit:"255,208,64"
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

  if (d.cpu_pct != null) mkBadge(`CPU ${d.cpu_pct}%`, "dpbadge-info");
  if (d.rss_mb  != null) mkBadge(`${d.rss_mb} MiB`,  "dpbadge-info");

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
let _jpLines = 200;
let _jpRaw   = "";
let _jpFilteredText = "";

window.loadTab_journal = function() { loadJournalList(); };

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

async function openJournalPopup(unit) {
  _jpUnit = unit;
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
}

function jpOverlayClick(e) {
  if (e.target === document.getElementById("jp-overlay")) closeJournalPopup();
}

async function jpCopy() {
  if (!_jpFilteredText) { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(_jpFilteredText);
}

async function jpRefresh() {
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

  try {
    const check = await navigator.clipboard.readText();
    if (check === src) {
      toast("Copied ✓", "ok", 2000);
    } else {
      await alertModal(
        `⚠ Clipboard copy may be incomplete (${check.length} of ${src.length} ` +
        `characters). This can happen on some mobile browsers with large ` +
        `files — try again, or use a desktop browser if this persists.`
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

window.loadTab_asldvs = function() { loadAstFiles(); loadAllmon3Files(); loadDvsFiles(); loadDstarGw(); };

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
    if (body)   body.innerHTML = `<div class="stub-panel" style="color:#f88;min-height:60px">Error: ${e.message}</div>`;
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
          font-size: 0.9rem;
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
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; font-size:var(--fs-sm); color: #5a7898">
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
        <div style="font-size:var(--fs-xs); color: #5a7898">${g.note}</div>
        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(9.5rem, 1fr)); gap: 0.5rem">
          ${cells}
        </div>`;
      const titleCss = "font-weight: 600; font-size: 0.9rem; color: var(--text)";
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
          font-size: 0.9rem;
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
            <span style="font-size:var(--fs-xs); color: #5a7898">${f.hint}</span>
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
          font-size: 0.9rem;
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
        <div style="color: #3a5278; font-weight: 500; margin-bottom: 0.2rem">USB Device</div>
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
        color: #5a7898;
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


let _zelloSampleText    = "";
let _zelloOverridePath  = "";
let _zelloLoadedContent = null;

window.loadTab_zello = function() { loadZello(); };


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

let _secData = null;
let _secBusy = false;
const _secOpen = new Set();

const _SEC_LAYER_IDS = ["dvswitch", "asl", "usrp2m17", "cross-cutting"];

function secToggle(id, kind) {
  const key   = id + ":" + kind;
  const panel = document.getElementById("sec-" + kind + "-" + id);
  const btn   = document.getElementById("sec-btn-" + kind + "-" + id);
  if (!panel) return;
  const show = panel.hidden;
  panel.hidden = !show;
  if (show) _secOpen.add(key); else _secOpen.delete(key);
  if (btn) {
    btn.classList.toggle("on", show);
    btn.setAttribute("aria-expanded", show ? "true" : "false");
  }
}

window.loadTab_security = function() {
  if (!_enabledTabSet.has("security")) return;
  _secFetch(false);
};

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
  loadPorts();
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
  return `<div style="font-size:var(--fs-xs);color:#5a7898">${esc(src)}</div>`;
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
          <span style="font-size:var(--fs-xs);color:#5a7898">${esc(n.role)}${n.private ? " · private" : ""}</span>
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
            <div style="font-size:var(--fs-xs);color:#5a7898">Default 5000 ms · range 0–60000 ms</div>
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
      <div style="font-size:var(--fs-base);color:#5a7898;line-height:1.4">
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
async function loadHardware() {
  const d = await api("/api/hardware");
  if (!d) {
    document.getElementById("hw-ambe-meta").textContent  = "error";
    document.getElementById("hw-audio-meta").textContent = "error";
    document.getElementById("hw-pwr-meta").textContent   = "error";
    return;
  }
  renderAmbeSection(d.ambe  || []);
  renderAudioSection(d.audio || []);
  renderPowerSection(d.power || null);
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
    <span style="font-family:var(--sans);font-size:.946rem;
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
    <span style="font-family:var(--sans);font-size:.946rem;
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
  
  const orig = btn.textContent;
  btn.textContent = "✓ Copied";
  setTimeout(() => { btn.textContent = orig; }, 1400);
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
  const orig = btn.textContent;
  btn.textContent = "✓ Copied";
  setTimeout(() => { btn.textContent = orig; }, 1400);
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
// TAB: Zello
// ========================================================================
// ---- general ----
function _zelloRenderInstall(bodyId, badgeId, inst) {
  _renderInstallTable(bodyId, badgeId, inst, {
    binDefault: "/opt/asl-zello-bridge/venv/bin/asl-zello-bridge",
    binLabel:   "Bridge installed (pip+venv or setup.py)",
    binFix:     "See README — pip+venv install (recommended) or deprecated setup.py",
    unit:       "asl-zello-bridge",
    unitFix:    "Copy asl-zello-bridge.service to /etc/systemd/system/ → systemctl daemon-reload",
  });
}

function _zelloRenderStatus(bodyId, status, inst) {
  const body = document.getElementById(bodyId);
  if (!body) return;

  const chip = (label, ok, warnOnly) => {
    const cls = ok ? "pass" : (warnOnly ? "warn" : "fail");
    const bc  = _dvsmBadgeClass(cls);
    return `<span class="dpbadge ${bc}" style="margin-right:.4rem">${_esc(label)}</span>`;
  };

  let html = `<div style="padding:.5rem .6rem">`;
  html += chip("Service: " + (inst.service_active ? "active" : "inactive"), inst.service_active);
  html += chip("Auth: " + (status.authenticated ? "logged in" : "not authenticated"), status.authenticated);
  html += chip("Channel: " + (status.channel_ready ? "ready" : "not ready"), status.channel_ready);
  if (status.currently_keyed) {
    html += chip("On air: " + (status.keyed_by || "unknown"), true);
  }
  html += `</div>`;

  const notes = [];
  if (status.last_activity) {
    const rel = status.last_activity_at ? ` (${_esc(status.last_activity_at)})` : "";
    notes.push(`<div class="dvsm-note src">Last activity: ${_esc(status.last_activity)}${rel}</div>`);
  }
  if (status.last_warn) {
    notes.push(`<div class="dvsm-note warn">&#x26A0; ${_esc(status.last_warn)}</div>`);
  }
  if (status.last_error) {
    notes.push(`<div class="dvsm-note err">&#x2717; ${_esc(status.last_error)}</div>`);
  }
  if (!status.journal_ok) {
    notes.push(`<div class="dvsm-note src">No journal history yet — status will populate once the service has logged something</div>`);
  }

  body.innerHTML = html + notes.join("");
}

function _zelloRenderSample(bodyId, rawText) {
  _zelloSampleText = rawText;
  _renderSampleCode(bodyId, rawText, /^\s*#/, /^(Environment=[^=]+)(=)(.*)/);
}

function zelloCopySample(btn) {
  dvsmCopy(btn, _zelloSampleText);
  const orig = btn.textContent;
  btn.textContent = "✓ Copied";
  setTimeout(() => { btn.textContent = orig; }, 1400);
}

async function loadZello() {
  ["install", "config"].forEach(k =>
    _dvsmSetBadge("zello-badge-" + k, "info", "...")
  );

  const d = await api("/api/zello");
  if (!d || !d.ok) {
    ["install", "config"].forEach(k =>
      _dvsmSetBadge("zello-badge-" + k, "fail", "ERR")
    );
    toast("Zello: failed to load config", "warn");
    return;
  }

  _zelloOverridePath = d.override_path || "";

  _zelloRenderInstall("zello-body-install", "zello-badge-install", d.install || {});
  _zelloRenderStatus("zello-body-status", d.status || {}, d.install || {});
  _dvsmRenderAccount("zello-body-config", "zello-badge-config", d.config || {}, "zello");
  _dvsmRenderCompat("zello-body-compat", d.compat || []);
  _zelloRenderSample("zello-body-sample", d.sample_override || "");

  const pathEl = document.getElementById("zello-config-path");
  if (pathEl) {
    pathEl.textContent = `${d.config?.mode === "work" ? "Work" : "Free"} mode — ${_zelloOverridePath}`;
  }

  window._zelloEditableCache = d.editable_content || "";
}

async function zelloOpenEditor() {
  const taExisting = document.getElementById("zello-textarea");
  if (taExisting && _zelloLoadedContent !== null && taExisting.value !== _zelloLoadedContent) {
    if (!await confirm("Discard unsaved changes to the Zello override?")) return;
  }

  const d = await api("/api/zello");
  if (!d || !d.ok) { toast(d?.message || "Could not load Zello config", "err"); return; }

  const ta = document.getElementById("zello-textarea");
  if (ta) ta.value = d.editable_content || "";
  _zelloLoadedContent = d.editable_content || "";
  _zelloOverridePath  = d.override_path || _zelloOverridePath;

  const pathEl = document.getElementById("zello-editor-path");
  if (pathEl) pathEl.textContent = _zelloOverridePath;

  const wrap   = document.getElementById("zello-editor-wrap");
  const togBtn = document.getElementById("zello-editor-toggle");
  if (wrap)   wrap.classList.add("open");
  if (togBtn) togBtn.textContent = "▲ Collapse";

  if (wrap) wrap.closest(".s3-card").scrollIntoView({ behavior: "smooth", block: "start" });
}

function zelloToggleEditor() {
  const wrap   = document.getElementById("zello-editor-wrap");
  const togBtn = document.getElementById("zello-editor-toggle");
  if (!wrap) return;
  const opening = !wrap.classList.contains("open");
  wrap.classList.toggle("open", opening);
  if (togBtn) togBtn.textContent = opening ? "▲ Collapse" : "▼ Expand";
  if (opening) zelloOpenEditor();
}

async function zelloAction(action) {
  const verbs = {start: "Start", stop: "Stop", restart: "Restart"};
  const verb  = verbs[action] || action;
  if (!await confirm(`${verb} asl-zello-bridge?`)) return;
  const d = await api("/api/zello", "POST", {action});
  if (!d || !d.ok) { toast(d?.message || `${verb} failed`, "err"); return; }
  toast(`asl-zello-bridge: ${verb.toLowerCase()}ed`, "ok");
  setTimeout(loadZello, 1200);
}

function zelloDiscardEdit() {
  const wrap   = document.getElementById("zello-editor-wrap");
  const togBtn = document.getElementById("zello-editor-toggle");
  if (wrap)   wrap.classList.remove("open");
  if (togBtn) togBtn.textContent = "▼ Expand";
  _zelloLoadedContent = null;
}

// ---- card: Edit Override ----
async function zelloSave() {
  const ta = document.getElementById("zello-textarea");
  if (!ta) return;
  const content = ta.value;
  if (!await confirm(
    "Save changes to the Zello systemd override?\n\n" +
    "This overwrites override.conf on disk, including the plaintext password. " +
    "Won't take effect until you Restart.")) return;

  const d = await api("/api/zello", "POST", {action: "save_override_raw", content});
  if (!d || !d.ok) { toast(d?.message || "Save failed", "err"); return; }
  _zelloLoadedContent = content;
  toast("Saved — restart to apply", "ok");
  loadZello();
}

async function zelloCopy() {
  const ta = document.getElementById("zello-textarea");
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
// TAB: Security
// ========================================================================
// ---- general ----
function _secIcon(status) {
  if (status === "pass") return ["ok",   "✓"];
  if (status === "fail") return ["fail", "✗"];
  if (status === "warn") return ["warn", "⚠"];
  return ["pend", "◌"];
}

function _secRowDetail(c) {
  const d = c.detail || {};
  if (Array.isArray(d.binds) && d.binds.length) {
    const bad = d.binds.filter(b => b.verdict && b.verdict !== "pass");
    if (bad.length) {
      const b = bad[0];
      return `${b.addr || "?"}:${b.port} ${b.scope}` +
             (bad.length > 1 ? ` +${bad.length - 1}` : "");
    }
    const listening = d.binds.filter(b => b.scope !== "not_listening");
    return listening.length ? `${listening.length} bind(s), all local/VPN`
                            : "configured, not listening";
  }
  if (Array.isArray(d.units) && d.units.length) {
    const bad = d.units.filter(u => u.verdict !== "pass");
    return bad.length ? `${bad.length} unit(s) as root` : `${d.units.length} unit(s) ok`;
  }
  if (Array.isArray(d.reasons) && d.reasons.length) return d.reasons[0];
  if (Array.isArray(d.notes)   && d.notes.length)   return d.notes[0];
  if (Array.isArray(d.findings) && d.findings.length) return d.findings[0];
  if (d.jails && d.jails.length) return d.jails.join(", ");
  return "";
}

function _secRefs(refs) {
  if (!Array.isArray(refs) || !refs.length) return "";
  const items = refs.map(r => r && r.url
    ? `<a href="${_esc(r.url)}" target="_blank" rel="noopener noreferrer"
         >&#8599; ${_esc(r.label)}</a>`
    : `<span class="sec-ref-plain">&#8226; ${_esc((r && r.label) || "")}</span>`
  ).join("");
  return `<span class="sec-note-h">References</span>
    <span class="sec-refs">${items}</span>`;
}

function _secNoteWhy(c) {
  const p = t => `<span class="sec-note-p">${_esc(t)}</span>`;
  return `<div class="ast-check-note sec-note" id="sec-why-${_esc(c.id)}"${
      _secOpen.has(c.id + ":why") ? "" : " hidden"}>
    <span class="sec-note-h">Severity</span>
    <span class="sec-sev ${_esc(c.severity)}">${_esc(c.severity)}</span>
    <span class="sec-note-h">What this check reads</span>${p(c.source)}
    <span class="sec-note-h">What the result means</span>${p(c.meaning)}
    ${c.risk ? `<span class="sec-note-h">Why it matters</span>${p(c.risk)}` : ""}
    <span class="sec-note-h">How to fix it</span>${p(c.remediation)}
    ${_secRefs(c.references)}
  </div>`;
}

function _secNoteRaw(c) {
  let body;
  try { body = JSON.stringify(c.detail, null, 2); }
  catch (e) { body = String(c.detail); }
  const redacted = c.sensitive
    ? `<div class="sec-redacted">&#128274; This check reads credential
         material. What you see below is all the backend produces for it:
         booleans and lengths, redacted server-side before the response was
         built. No secret value is sent to this page.</div>`
    : "";
  return `<div class="ast-check-note sec-note" id="sec-raw-${_esc(c.id)}"${
      _secOpen.has(c.id + ":raw") ? "" : " hidden"}>
    <span class="sec-note-h">Raw check output</span>
    ${redacted}
    <div class="sec-note-raw">${_esc(body)}</div>
  </div>`;
}

function _secRow(c) {
  const [icls, ichar] = _secIcon(c.status);
  const dcls = c.status === "pass" ? "ok" : c.status === "fail" ? "fail"
             : c.status === "warn" ? "warn" : "";
  const id   = _esc(c.id);
  const whyOn = _secOpen.has(c.id + ":why") ? " on" : "";
  const rawOn = _secOpen.has(c.id + ":raw") ? " on" : "";
  return `<div class="hw-check-row" id="sec-row-${id}">
    <span class="hw-check-icon ${icls}">${ichar}</span>
    <span class="hw-check-label">${_esc(c.label)}</span>
    <span class="sec-row-actions">
      <span class="sec-row-detail ${dcls}" title="${_esc(_secRowDetail(c))}"
        >${_esc(_secRowDetail(c))}</span>
      <button class="ast-toggle${whyOn}" id="sec-btn-why-${id}"
              aria-expanded="${_secOpen.has(c.id + ":why")}"
              title="source, meaning and fix"
              onclick="secToggle('${id}','why')">?</button>
      <button class="ast-toggle${rawOn}" id="sec-btn-raw-${id}"
              aria-expanded="${_secOpen.has(c.id + ":raw")}"
              title="raw check output"
              onclick="secToggle('${id}','raw')">raw</button>
    </span>
  </div>` + _secNoteWhy(c) + _secNoteRaw(c);
}

function _secSetCard(layerId, layer, checks) {
  const body   = document.getElementById("sec-body-" + layerId);
  const badge  = document.getElementById("sec-status-" + layerId);
  const meta   = document.getElementById("sec-meta-" + layerId);
  if (!body) return;

  if (badge) {
    const st = (layer && layer.status) || "info";
    badge.className   = "reg-card-status " + (st === "not_implemented" || st === "error" ? "info" : st);
    badge.textContent = st.replace("_", " ").toUpperCase();
  }
  if (meta) {
    const c = (layer && layer.counts) || {};
    meta.textContent = c.fail ? `${c.fail} issue${c.fail === 1 ? "" : "s"}`
                     : c.warn ? `${c.warn} warning${c.warn === 1 ? "" : "s"}`
                     : c.total ? "all clear" : "—";
  }
  if (!checks.length) {
    body.innerHTML = '<div class="stub-panel" style="min-height:60px">No checks in this layer</div>';
    return;
  }
  body.innerHTML = checks.map(_secRow).join("");
}

function _secShowUnreachable() {
  _SEC_LAYER_IDS.forEach(l => {
    const body = document.getElementById("sec-body-" + l);
    if (body) body.innerHTML =
      '<div class="stub-panel" style="min-height:60px">Server unreachable</div>';
    const badge = document.getElementById("sec-status-" + l);
    if (badge) { badge.className = "reg-card-status"; badge.textContent = "—"; }
  });
  ["pass","warn","fail","total"].forEach(k => {
    const el = document.getElementById("sec-n-" + k);
    if (el) el.textContent = "–";
  });
}

function secRender(d) {
  _secData = d;
  const sum = d.summary || {};
  const set = (id, v) => { const el = document.getElementById(id);
                            if (el) el.textContent = (v === undefined ? "–" : v); };
  set("sec-n-pass",  sum.pass);
  set("sec-n-warn",  sum.warn);
  set("sec-n-fail",  sum.fail);
  set("sec-n-total", sum.total);

  const ts = document.getElementById("sec-last-run");
  if (ts) {
    const when = d.last_run_timestamp
      ? new Date(d.last_run_timestamp * 1000).toLocaleTimeString()
      : "never";
    ts.textContent = d.cached
      ? `last run ${when} · cached (${d.cache_age_sec || 0}s old)`
      : `last run ${when}`;
  }

  const byLayer = {};
  (d.layers || []).forEach(l => { byLayer[l.id] = l; });
  _SEC_LAYER_IDS.forEach(l => {
    _secSetCard(l, byLayer[l], (d.checks || []).filter(c => c.layer === l));
  });
}

function _secSetBusy(busy) {
  _secBusy = busy;
  const all = document.getElementById("sec-rerun-all");
  if (all) {
    all.disabled    = busy;
    all.textContent = busy ? "Running…" : "↻ Re-run checks";
  }
  document.querySelectorAll(".sec-card-rerun").forEach(b => { b.disabled = busy; });
  const bar = document.querySelector("#panel-security .sec-summary");
  if (bar) bar.classList.toggle("sec-busy", busy);
}

async function _secFetch(refresh) {
  if (_secBusy) return;
  _secSetBusy(true);
  try {
    const d = await api("/api/security/checks" + (refresh ? "?refresh=1" : ""));
    if (!d || !d.ok) { _secShowUnreachable(); return; }
    secRender(d);
  } finally {
    _secSetBusy(false);
  }
}

function secRerun() { _secFetch(true); }

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

  const nrWarn = document.getElementById("ed-nr-warn");
  const nrCrit = document.getElementById("ed-nr-crit");
  if (nrWarn) _cfg_nr_warn = nrWarn.value;
  if (nrCrit) _cfg_nr_crit = nrCrit.value;
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
  const d = await api(`/api/ports?proto=${_ptProto}`);
  if (!d) return;
  renderPorts(d.ports || []);

  const ts = document.getElementById("pt-refresh-ts");
  if (ts) ts.textContent = "↻ " + new Date().toTimeString().slice(0,8);
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
// SHARED: DVSM + Zello
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
// SHARED: DVSM + STFU + M17 + Zello
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

function dvsmCopy(btn, value) {
  navigator.clipboard.writeText(String(value || "")).catch(() => {});
  const orig = btn.textContent;
  btn.textContent = "✓";
  btn.classList.add("copied");
  setTimeout(() => { btn.textContent = orig; btn.classList.remove("copied"); }, 1200);
}

function dvsmCopyAttr(btn) { dvsmCopy(btn, btn.getAttribute("data-copyval") || ""); }

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

_PUBLIC_GET_PATHS  = {"/", "/api/ping"}

class _EarlyReturn(Exception):
    pass

_MAX_CONCURRENT_CONNS = 24
_conn_sem = threading.Semaphore(_MAX_CONCURRENT_CONNS)

class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    
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

    def handle(self) -> None:
        
        with _conn_sem:
            super().handle()

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

def _zello_quick_installed() -> bool:
    if _ZELLO_VENV_BIN.exists() and os.access(str(_ZELLO_VENV_BIN), os.X_OK):
        return True
    return any(p.exists() for p in _ZELLO_SERVICE_PATHS)

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
        "zello_installed": _zello_quick_installed(),
        "wifimon_shutdown": snap.get("wifimon_shutdown") or {"active": False},
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

def _route_reboot(h: Handler, data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "root required"}); return
    _log("REBOOT requested", stderr=True)
    h.send_json({"ok": True, "message": "Rebooting…"})
    threading.Thread(
        target=lambda: (time.sleep(1), os.system("reboot")),
        daemon=True,
    ).start()

def _route_shutdown(h: Handler, data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "root required"}); return
    _log("SHUTDOWN requested", stderr=True)
    h.send_json({"ok": True, "message": "Shutting down…"})
    threading.Thread(
        target=lambda: (time.sleep(1), os.system("shutdown -h now")),
        daemon=True,
    ).start()

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

CHK_PASS            = "pass"
CHK_WARN            = "warn"
CHK_FAIL            = "fail"
CHK_NOT_IMPLEMENTED = "not_implemented"
CHK_ERROR           = "error"

_SECURITY_LAYERS     = {"dvswitch", "asl", "usrp2m17", "cross-cutting"}
_SECURITY_SEVERITIES = {"high", "medium", "low"}

_SECURITY_STATUS_RANK = {
    CHK_PASS: 0, CHK_NOT_IMPLEMENTED: 1, CHK_ERROR: 2, CHK_WARN: 3, CHK_FAIL: 4,
}
_SECURITY_SUBPROC_TIMEOUT = 2

def _check_result(status: str, **raw) -> dict:
    return {"status": status, "raw": raw}

def _sec_worst(statuses) -> str:
    worst = CHK_PASS
    for s in statuses:
        if _SECURITY_STATUS_RANK.get(s, 0) > _SECURITY_STATUS_RANK.get(worst, 0):
            worst = s
    return worst
_SECURITY_RUNCTX: dict = {}

def _sec_ctx(key: str, producer):
    if key not in _SECURITY_RUNCTX:
        try:
            _SECURITY_RUNCTX[key] = producer()
        except Exception as exc:
            log.debug("security: ctx %s failed: %s", key, exc)
            _SECURITY_RUNCTX[key] = None
    return _SECURITY_RUNCTX[key]

def _sec_run(cmd: list, timeout: int = _SECURITY_SUBPROC_TIMEOUT) -> "tuple[str, bool]":
    deadline = _SECURITY_RUNCTX.get("_deadline")
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0.2:
            log.debug("security: run budget spent, skipping %s", cmd[:2])
            return "", False
        timeout = max(1, min(timeout, int(remaining)))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "").strip(), True
    except subprocess.TimeoutExpired:
        log.debug("security: %s timed out after %ss", cmd[:2], timeout)
        return "", False
    except (FileNotFoundError, PermissionError, OSError) as exc:
        log.debug("security: %s unavailable: %s", cmd[:2], exc)
        return "", False
    except Exception as exc:
        log.debug("security: %s failed: %s", cmd[:2], exc)
        return "", False

def _sec_have_binary(name: str) -> bool:
    return bool(shutil.which(name))

def _sec_installed_units() -> set:
    def _produce():
        out, ran = _sec_run(
            ["systemctl", "list-unit-files", "--no-pager", "--no-legend", "--type=service"],
            timeout=3)
        if not ran or not out:
            return set()
        names = set()
        for line in out.splitlines():
            parts = line.split()
            if parts:
                names.add(parts[0].strip())
        return names
    return _sec_ctx("units", _produce) or set()

def _sec_unit_installed(unit: str) -> bool:
    return unit in _sec_installed_units()

def _sec_unit_props(units: list, props: list) -> "dict[str, dict]":
    if not units:
        return {}
    args = ["systemctl", "show"]
    for pr in props:
        args += ["-p", pr]
    args += list(units)
    out, ran = _sec_run(args, timeout=3)
    if not ran or not out:
        return {}

    result: "dict[str, dict]" = {}
    for block in out.split("\n\n"):
        kv: dict = {}
        for line in block.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                kv[k.strip()] = v.strip()
        unit = kv.get("Id", "")
        if unit:
            result[unit] = kv
    return result

def _sec_ss_entries() -> list:
    def _produce():
        raw = _ss_tlnpu_fetch()
        return _parse_ss_entries(raw) if raw else []
    return _sec_ctx("ss_entries", _produce) or []

_SEC_VPN_IFACE_PREFIXES = ("wg", "tailscale", "tun", "tap", "zt", "nebula")

def _sec_vpn_interfaces() -> "dict[str, dict]":
    def _produce():
        out: "dict[str, dict]" = {}
        base = Path("/sys/class/net")
        try:
            names = sorted(p.name for p in base.iterdir())
        except Exception as exc:
            log.debug("security: /sys/class/net unreadable: %s", exc)
            return out
        for name in names:
            if not name.startswith(_SEC_VPN_IFACE_PREFIXES):
                continue
            operstate = ""
            flags_up  = False
            try:
                operstate = (base / name / "operstate").read_text().strip().lower()
            except Exception as exc:
                log.debug("security: operstate %s: %s", name, exc)
            try:
                raw_flags = (base / name / "flags").read_text().strip()
                flags_up  = bool(int(raw_flags, 16) & 0x1)
            except Exception as exc:
                log.debug("security: flags %s: %s", name, exc)
            up = (operstate == "up") or (flags_up and operstate != "down")
            out[name] = {"operstate": operstate or "unknown",
                          "flags_up": flags_up, "up": up}
        return out
    return _sec_ctx("vpn_ifaces", _produce) or {}

def _sec_addr_iface_map() -> "dict[str, str]":
    def _produce():
        out: "dict[str, str]" = {}
        raw, ran = _sec_run(["ip", "-o", "addr", "show"])
        if not ran or not raw:
            return out
        for line in raw.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            iface = parts[1].split("@", 1)[0]
            if parts[2] not in ("inet", "inet6"):
                continue
            addr = parts[3].split("/", 1)[0].split("%", 1)[0]
            out.setdefault(addr, iface)
        return out
    return _sec_ctx("addr_iface", _produce) or {}

def _sec_norm_addr(addr: str) -> str:
    a = (addr or "").strip()
    if a.startswith("[") and a.endswith("]"):
        a = a[1:-1]
    a = a.split("%", 1)[0]
    if a in ("*", ""):
        return "0.0.0.0"
    return a

def _sec_classify_bind(addr: str) -> dict:
    a = _sec_norm_addr(addr)

    if a.startswith("127.") or a in ("::1", "0:0:0:0:0:0:0:1"):
        return {"scope": "loopback", "verdict": CHK_PASS, "iface": "lo",
                "vpn_up": None, "addr": a}
    if a in ("0.0.0.0", "::", "0:0:0:0:0:0:0:0"):
        return {"scope": "wildcard", "verdict": CHK_FAIL, "iface": "",
                "vpn_up": None, "addr": a}

    iface = _sec_addr_iface_map().get(a, "")
    if not iface:
        return {"scope": "unknown", "verdict": CHK_WARN, "iface": "",
                "vpn_up": None, "addr": a}

    vpn = _sec_vpn_interfaces().get(iface)
    if vpn is not None:
        return {"scope": "vpn", "verdict": CHK_PASS if vpn["up"] else CHK_WARN,
                "iface": iface, "vpn_up": vpn["up"], "addr": a}

    return {"scope": "lan", "verdict": CHK_FAIL, "iface": iface,
            "vpn_up": None, "addr": a}

def _sec_binds_for_port(port: str, proto: str = "") -> list:
    port = str(port).strip()
    if not port.isdigit():
        return []
    out = []
    for e in _sec_ss_entries():
        if e["port"] != port:
            continue
        if proto and e["proto"] != proto:
            continue
        cls = _sec_classify_bind(e["addr"])
        out.append({
            "port": e["port"], "proto": e["proto"], "addr": cls["addr"],
            "scope": cls["scope"], "verdict": cls["verdict"],
            "iface": cls["iface"], "vpn_up": cls["vpn_up"],
            "process": e.get("process", ""),
        })
    return out

def _sec_exposure_verdict(targets: list) -> "tuple[str, list, list]":
    rows:  list = []
    notes: list = []
    statuses:  list = []

    for t in targets:
        port  = str(t.get("port", "")).strip()
        proto = t.get("proto", "")
        if not port.isdigit():
            continue
        binds = _sec_binds_for_port(port, proto)
        if not binds:
            rows.append({"port": port, "proto": proto or "-", "addr": "",
                          "scope": "not_listening", "verdict": CHK_PASS,
                          "iface": "", "vpn_up": None, "process": "",
                          "role": t.get("role", ""), "source": t.get("source", "")})
            notes.append(f"{t.get('role', 'port')} {port}/{proto or '?'}: "
                          f"configured but nothing is listening")
            continue
        for b in binds:
            b = dict(b)
            b["role"]   = t.get("role", "")
            b["source"] = t.get("source", "")
            rows.append(b)
            statuses.append(b["verdict"])

    if not rows:
        return CHK_WARN, rows, ["no ports could be read from config"]
    return _sec_worst(statuses) if statuses else CHK_PASS, rows, notes

_SEC_WEAK_SECRETS = frozenset({
    "", "password", "passw0rd", "pass", "secret", "changeme", "change-me",
    "letmein", "admin", "administrator", "root", "test", "guest", "default",
    "asterisk", "allstar", "allstarlink", "node", "radio", "repeater",
    "dvswitch", "brandmeister", "hotspot", "iaxrpt", "manager", "monitor",
    "12345", "123456", "1234567", "12345678", "123456789", "1234567890",
    "0000", "1111", "1234", "qwerty", "abc123", "supersecret", "mypassword",
})

_SEC_DEFAULT_AMI_USERS = frozenset({
    "admin", "administrator", "manager", "asterisk", "allmon", "allmon3",
    "monitor", "dvswitch", "user", "test",
})

def _sec_identity() -> dict:
    def _produce():
        rpt  = _dvsm_read_rpt_conf()
        iax  = _dvsm_read_iax_conf()
        cfg_cs = _cfg.get("identity", "callsign", fallback="").strip()
        cfg_nd = _cfg.get("identity", "node",     fallback="").strip()

        callsign = (rpt.get("callsign", "")
                    or iax.get("iaxrpt_callerid", "")
                    or cfg_cs).strip().upper()

        nodes = [n["id"] for n in rpt.get("nodes", []) if n.get("id")]
        if cfg_nd and cfg_nd not in nodes:
            nodes.append(cfg_nd)
        for r in iax.get("registers", []):
            nid = str(r.get("node", "")).strip()
            if nid and nid not in nodes:
                nodes.append(nid)

        dmr_id = ""
        mb = _sec_read_mmdvm_bridge()
        if mb.get("raw_ok"):
            dmr_id = mb["sections"].get("GENERAL", {}).get("Id", "").strip()
        if not dmr_id:
            ab_content, ab_path = _sec_read_first(_STFU_AB_CANDIDATES)
            if ab_content:
                ambe = _dvs_parse_sections(ab_content).get("AMBE_AUDIO", {})
                dmr_id = (ambe.get("gatewayDmrId", "")
                          or ambe.get("repeaterID", "")).strip()

        return {"callsign": callsign, "nodes": nodes, "dmr_id": dmr_id}
    return _sec_ctx("identity", _produce) or {"callsign": "", "nodes": [], "dmr_id": ""}

def _sec_secret_facts(secret: str, label: str = "") -> dict:
    s = (secret or "").strip()
    ident = _sec_identity()
    cs    = ident["callsign"]
    nodes = {str(n).strip() for n in ident["nodes"] if str(n).strip()}
    dmr   = str(ident["dmr_id"]).strip()

    su = s.upper()
    matches_callsign = bool(cs) and (
        su == cs or (su.startswith(cs) and su[len(cs):].isdigit() and len(su) > len(cs))
    )
    matches_node = bool(s) and s in nodes
    matches_dmr  = bool(s) and bool(dmr) and s == dmr

    return {
        "label":            label,
        "present":          bool(s),
        "length":           len(s),
        "matches_callsign": matches_callsign,
        "matches_node":     matches_node,
        "matches_dmr_id":   matches_dmr,
        "known_weak":       s.lower() in _SEC_WEAK_SECRETS,
        "all_same_char":    bool(s) and len(set(s)) == 1,
        "too_short":        bool(s) and len(s) < 8,
    }

def _sec_facts_verdict(facts: list) -> "tuple[str, list]":
    reasons: list = []
    status = CHK_PASS
    for f in facts:
        who = f.get("label") or "secret"
        if not f["present"]:
            reasons.append(f"{who}: not set")
            status = _sec_worst([status, CHK_FAIL]); continue
        if f["matches_callsign"]:
            reasons.append(f"{who}: equals the node callsign")
            status = _sec_worst([status, CHK_FAIL])
        if f["matches_node"]:
            reasons.append(f"{who}: equals a node number")
            status = _sec_worst([status, CHK_FAIL])
        if f["matches_dmr_id"]:
            reasons.append(f"{who}: equals the DMR ID")
            status = _sec_worst([status, CHK_FAIL])
        if f["known_weak"]:
            reasons.append(f"{who}: known-weak/default value")
            status = _sec_worst([status, CHK_FAIL])
        if f["all_same_char"]:
            reasons.append(f"{who}: single repeated character")
            status = _sec_worst([status, CHK_FAIL])
        if f["too_short"] and not any((f["matches_callsign"], f["matches_node"],
                                        f["matches_dmr_id"], f["known_weak"],
                                        f["all_same_char"])):
            reasons.append(f"{who}: shorter than 8 characters")
            status = _sec_worst([status, CHK_WARN])
    if not facts:
        return CHK_WARN, ["no secret found to evaluate"]
    if not reasons:
        reasons.append("no weak-secret pattern matched")
    return status, reasons

def _sec_read_first(candidates) -> "tuple[str, str]":
    for cand in candidates:
        content, err = read_path_file(cand)
        if not err:
            return content, str(cand)
    return "", ""

_SEC_MB_CANDIDATES = [
    Path("/opt/MMDVM_Bridge/MMDVM_Bridge.ini"),
    Path("/etc/MMDVM_Bridge/MMDVM_Bridge.ini"),
    Path("/etc/dvswitch/MMDVM_Bridge.ini"),
]
_SEC_MB_BINARIES = [
    Path("/opt/MMDVM_Bridge/MMDVM_Bridge"),
    Path("/usr/local/bin/MMDVM_Bridge"),
]
_SEC_MONIT_CANDIDATES = [
    Path("/etc/monit/monitrc"),
    Path("/etc/monitrc"),
    Path("/etc/monit.conf"),
]
_SEC_SSHD_CONFIG     = Path("/etc/ssh/sshd_config")
_SEC_SSHD_CONFIG_DIR = Path("/etc/ssh/sshd_config.d")
_SEC_ASTERISK_DIR    = _AST_DIR
_SEC_ASTERISK_EXPECTED_MODE  = 0o750
_SEC_ASTERISK_EXPECTED_GROUP = "asterisk"
_SEC_ASTERISK_SECRET_FILES   = ("iax.conf", "manager.conf", "rpt.conf")

def _sec_read_mmdvm_bridge() -> dict:
    def _produce():
        content, path = _sec_read_first(_SEC_MB_CANDIDATES)
        installed = (any(p.exists() for p in _SEC_MB_BINARIES)
                     or _sec_unit_installed("mmdvm_bridge.service"))
        if not content:
            return {"raw_ok": False, "path": "", "sections": {},
                     "installed": installed}
        return {"raw_ok": True, "path": path,
                 "sections": _dvs_parse_sections(content), "installed": True}
    return _sec_ctx("mmdvm_bridge", _produce) or {
        "raw_ok": False, "path": "", "sections": {}, "installed": False}

def _sec_read_manager_conf() -> dict:
    def _produce():
        content, err = read_asterisk_file("manager.conf")
        if err:
            return {"raw_ok": False, "error": err, "sections": {}}
        return {"raw_ok": True, "error": "", "sections": _parse_sections(content),
                 "has_permit": bool(re.search(r"(?mi)^\s*permit\s*=", content)),
                 "has_deny":   bool(re.search(r"(?mi)^\s*deny\s*=",   content))}
    return _sec_ctx("manager_conf", _produce) or {
        "raw_ok": False, "error": "read failed", "sections": {}}

def _sec_read_iax() -> dict:
    return _sec_ctx("iax_conf", _dvsm_read_iax_conf) or {"raw_ok": False}

def _sec_read_rpt() -> dict:
    return _sec_ctx("rpt_conf", _dvsm_read_rpt_conf) or {"raw_ok": False}

def _sec_read_m17() -> dict:
    return _sec_ctx("m17_ini", _m17_read_config) or {"raw_ok": False}

def _check_usrp_port_exposure() -> dict:
    targets: list = []

    m17 = _sec_read_m17()
    if m17.get("raw_ok"):
        for key, role in (("usrp_local_port", "usrp2m17 USRP listen"),
                          ("usrp_dst_port",   "usrp2m17 USRP peer")):
            val = str(m17.get(key, "")).strip()
            if val.isdigit():
                targets.append({"port": val, "proto": "udp", "role": role,
                                 "source": m17.get("ini_path", "USRP2M17.ini")})

    ab = _dvsm_read_ab()
    if ab.get("raw_ok"):
        for key, role in (("rx_port", "Analog_Bridge USRP rx"),
                          ("tx_port", "Analog_Bridge USRP tx")):
            val = str(ab.get(key, "")).strip()
            if val.isdigit():
                targets.append({"port": val, "proto": "udp", "role": role,
                                 "source": ab.get("source", "Analog_Bridge.ini")})

    rpt = _sec_read_rpt()
    for node in rpt.get("nodes", []):
        for key, role in (("usrp_rx", f"rpt.conf node {node.get('id','')} USRP rx"),
                          ("usrp_tx", f"rpt.conf node {node.get('id','')} USRP tx")):
            val = str(node.get(key, "")).strip()
            if val.isdigit():
                targets.append({"port": val, "proto": "udp", "role": role,
                                 "source": str(_RPT_CONF)})

    seen, uniq = set(), []
    for t in targets:
        key = (t["port"], t["proto"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(t)

    if not uniq:
        return _check_result(
            CHK_WARN, binds=[], notes=["no USRP ports found in USRP2M17.ini, "
                                        "Analog_Bridge.ini or rpt.conf"],
            vpn=_sec_vpn_summary())

    status, rows, notes = _sec_exposure_verdict(uniq)
    return _check_result(status, binds=rows, notes=notes, vpn=_sec_vpn_summary())

def _check_m17_port_exposure() -> dict:
    m17 = _sec_read_m17()
    if not m17.get("raw_ok"):
        return _check_result(
            CHK_WARN, binds=[],
            notes=[m17.get("error") or "USRP2M17.ini not readable"],
            vpn=_sec_vpn_summary())

    targets = []
    for key, role in (("m17_local_port", "M17 local"),
                      ("m17_dst_port",   "M17 reflector")):
        val = str(m17.get(key, "")).strip()
        if val.isdigit():
            targets.append({"port": val, "proto": "udp", "role": role,
                             "source": m17.get("ini_path", "USRP2M17.ini")})

    if not targets:
        return _check_result(
            CHK_WARN, binds=[],
            notes=["no M17 ports configured in USRP2M17.ini [M17 NETWORK]"],
            vpn=_sec_vpn_summary())

    status, rows, notes = _sec_exposure_verdict(targets)
    addr = str(m17.get("address", "")).strip()
    if addr == _M17_PLACEHOLDER_ADDRESS:
        notes.append("USRP2M17.ini Address is still the 0.0.0.0 placeholder "
                      "(bridge not pointed at a reflector)")
    return _check_result(status, binds=rows, notes=notes, vpn=_sec_vpn_summary())

def _check_ami_port_exposure() -> dict:
    mgr = _sec_read_manager_conf()
    if not mgr.get("raw_ok"):
        return _check_result(CHK_WARN, binds=[],
                              notes=[mgr.get("error") or "manager.conf unreadable"],
                              enabled=None, vpn=_sec_vpn_summary())

    general = mgr["sections"].get("general", {})
    enabled = general.get("enabled", "").strip().lower()
    if enabled and enabled not in ("yes", "true", "on", "1"):
        return _check_result(CHK_PASS, binds=[], enabled=False,
                              notes=["AMI is disabled in manager.conf "
                                     "([general] enabled=no) -- nothing listening"],
                              acl_checked=False, vpn=_sec_vpn_summary())

    bindaddr = general.get("bindaddr", "").strip() or "0.0.0.0"
    port     = general.get("port", "").strip() or "5038"

    targets = [{"port": port, "proto": "tcp", "role": "AMI",
                 "source": str(_AST_DIR / "manager.conf")}]
    status, rows, notes = _sec_exposure_verdict(targets)

    cfg_cls = _sec_classify_bind(bindaddr)
    if not rows or all(r["scope"] == "not_listening" for r in rows):
        status = cfg_cls["verdict"]
        notes.append(f"not currently listening; manager.conf bindaddr is "
                      f"{cfg_cls['addr']} ({cfg_cls['scope']})")
    else:
        status = _sec_worst([status, cfg_cls["verdict"]])

    notes.append("bind address only -- manager.conf permit=/deny= ACL lines "
                  "are NOT evaluated by this check (v1 limitation)")

    return _check_result(
        status, binds=rows, notes=notes, enabled=True,
        configured_bindaddr=cfg_cls["addr"], configured_scope=cfg_cls["scope"],
        configured_port=port,
        acl_lines_present=bool(mgr.get("has_permit") or mgr.get("has_deny")),
        acl_checked=False, vpn=_sec_vpn_summary())

def _sec_vpn_summary() -> dict:
    ifaces = _sec_vpn_interfaces()
    return {
        "interfaces": [{"name": n, "operstate": v["operstate"], "up": v["up"]}
                        for n, v in sorted(ifaces.items())],
        "any_up": any(v["up"] for v in ifaces.values()),
        "present": bool(ifaces),
    }

_SEC_IAX_DOCUMENTED_STANZAS = {"allstar-public", "allstar-pub"}

def _check_iax2_secret_strength() -> dict:
    iax = _sec_read_iax()
    if not iax.get("raw_ok"):
        return _check_result(CHK_WARN, evaluated=0,
                              reasons=[iax.get("error") or "iax.conf unreadable"])

    facts:   list = []
    skipped: list = []
    for cand in iax.get("iaxrpt_candidates", []):
        name = str(cand.get("name", "")).strip() or "user"
        if name.lower() in _SEC_IAX_DOCUMENTED_STANZAS:
            skipped.append(name)
            continue
        facts.append(_sec_secret_facts(cand.get("secret", ""), f"[{name}] secret"))
    for reg in iax.get("registers", []):
        node = str(reg.get("node", "")).strip() or "?"
        facts.append(_sec_secret_facts(reg.get("password", ""),
                                        f"register=> node {node}"))

    if not facts:
        http_content, http_err = read_asterisk_file("rpt_http_registrations.conf")
        reasons = []
        if skipped:
            reasons.append(f"skipped documented AllStar stanza(s): "
                            f"{', '.join(skipped)}")
        if not http_err and http_content.strip():
            reasons.append("no local IAX2 client secret is defined, and this node "
                            "registers over HTTP (rpt_http_registrations.conf) -- "
                            "nothing to grade")
            return _check_result(CHK_PASS, evaluated=0, reasons=reasons,
                                  http_registration=True)
        reasons.append("no IAX2 user secrets or register= lines found in iax.conf, "
                        "and no HTTP registration config either")
        return _check_result(CHK_WARN, evaluated=0, reasons=reasons,
                              http_registration=False)

    status, reasons = _sec_facts_verdict(facts)
    if skipped:
        reasons.insert(0, f"skipped documented AllStar stanza(s): "
                           f"{', '.join(skipped)} (protected by ASL token validation)")
    return _check_result(
        status,
        evaluated=len(facts),
        reasons=reasons,
        secret_matches_callsign=any(f["matches_callsign"] for f in facts),
        secret_matches_node=any(f["matches_node"] or f["matches_dmr_id"] for f in facts),
        secret_is_known_weak=any(f["known_weak"] or f["all_same_char"] for f in facts),
        secret_length=min([f["length"] for f in facts if f["present"]] or [0]),
    )

def _check_ami_default_credentials() -> dict:
    mgr = _sec_read_manager_conf()
    if not mgr.get("raw_ok"):
        return _check_result(CHK_WARN, evaluated=0,
                              reasons=[mgr.get("error") or "manager.conf unreadable"])

    users = {name: kv for name, kv in mgr["sections"].items()
             if name.lower() != "general"}
    if not users:
        return _check_result(CHK_WARN, evaluated=0,
                              reasons=["no AMI users configured in manager.conf"])

    facts:   list = []
    reasons: list = []
    default_user = False
    for name, kv in users.items():
        if name.strip().lower() in _SEC_DEFAULT_AMI_USERS:
            default_user = True
            reasons.append(f"user '{name}': default/predictable username")
        facts.append(_sec_secret_facts(kv.get("secret", ""), f"user '{name}' secret"))

    status, sec_reasons = _sec_facts_verdict(facts)
    reasons.extend(sec_reasons)

    if default_user:
        status = _sec_worst([status, CHK_WARN])

    return _check_result(
        status,
        evaluated=len(facts),
        reasons=reasons,
        username_is_default=default_user,
        secret_matches_callsign=any(f["matches_callsign"] for f in facts),
        secret_is_known_weak=any(f["known_weak"] or f["all_same_char"]
                                  or not f["present"] for f in facts),
    )

def _check_brandmeister_hotspot_password() -> dict:
    mb = _sec_read_mmdvm_bridge()
    if not mb.get("raw_ok"):
        if not mb.get("installed"):
            return _check_result(CHK_PASS, evaluated=0,
                                  reasons=["MMDVM_Bridge is not installed on this "
                                           "node -- no DMR network password to check"])
        return _check_result(CHK_WARN, evaluated=0,
                              reasons=["MMDVM_Bridge is installed but "
                                       "MMDVM_Bridge.ini is missing or unreadable"])

    sections = mb["sections"]
    net = sections.get("DMR NETWORK", {}) or sections.get("DMR_NETWORK", {})
    if not net:
        return _check_result(CHK_WARN, evaluated=0,
                              reasons=["no [DMR Network] section in MMDVM_Bridge.ini"])

    enabled = str(net.get("Enable", "")).strip().lower()
    if enabled in ("0", "no", "false", "off"):
        return _check_result(CHK_PASS, evaluated=0,
                              reasons=["[DMR Network] is disabled in MMDVM_Bridge.ini"])

    facts = [_sec_secret_facts(net.get("Password", ""), "[DMR Network] Password")]
    status, reasons = _sec_facts_verdict(facts)
    f = facts[0]

    return _check_result(
        status,
        evaluated=1,
        reasons=reasons,
        password_matches_callsign=f["matches_callsign"],
        password_is_known_default=f["known_weak"] or f["all_same_char"] or not f["present"],
        password_length=f["length"],
    )

def _check_chan_sip_disabled() -> dict:
    conf_state = module_state("chan_sip.so")

    loaded   = None
    peers    = None
    ast_seen = False
    if _sec_have_binary("asterisk"):
        out, ran = _sec_run(["asterisk", "-rx", "module show like chan_sip"])
        if ran and out:
            ast_seen = True
            loaded   = "chan_sip.so" in out.lower()
            if loaded:
                pout, pran = _sec_run(["asterisk", "-rx", "sip show peers"])
                if pran and pout:
                    m = re.search(r"(\d+)\s+sip peers", pout, re.IGNORECASE)
                    peers = int(m.group(1)) if m else None

    notes = [f"modules.conf state: {conf_state}"]
    if not ast_seen:
        notes.append("Asterisk CLI not reachable -- verdict from modules.conf alone")

    if loaded is True:
        if peers:
            status = CHK_FAIL
            notes.append(f"chan_sip is loaded and has {peers} configured peer(s)")
        else:
            status = CHK_WARN
            notes.append("chan_sip is loaded but has no configured peers")
    elif loaded is False:
        status = CHK_PASS
        notes.append("chan_sip is not loaded in the running Asterisk")
    else:
        status = CHK_PASS if conf_state == "noload" else CHK_WARN
        if conf_state != "noload":
            notes.append("chan_sip is not set to noload in modules.conf")

    return _check_result(status, notes=notes, modules_conf_state=conf_state,
                          loaded=loaded, peers=peers)

def _check_monit_auth() -> dict:
    path = None
    for cand in _SEC_MONIT_CANDIDATES:
        if cand.exists():
            path = cand
            break

    if path is None:
        if not _sec_have_binary("monit") and not _sec_unit_installed("monit.service"):
            return _check_result(CHK_PASS, notes=["monit is not installed on this "
                                                   "node -- nothing to configure"],
                                  installed=False)
        return _check_result(CHK_WARN, notes=["monit appears installed but no "
                                               "monitrc was found"], installed=True)

    try:
        st   = path.stat()
        mode = st.st_mode & 0o777
    except Exception as exc:
        return _check_result(CHK_WARN, notes=[f"{path}: {exc}"], installed=True)

    content, err = read_path_file(path)
    if err:
        return _check_result(CHK_WARN, notes=[f"{path}: {err} (mode {oct(mode)})"],
                              installed=True, mode=oct(mode))
    if "[truncated" in content:
        return _check_result(
            CHK_WARN,
            notes=[f"{path} exceeds the 64 KB read cap and was truncated -- "
                   f"`allow` lines past that point cannot be seen, so auth "
                   f"configuration cannot be verified (mode {oct(mode)})"],
            installed=True, mode=oct(mode), truncated=True)

    mode_ok  = (mode & 0o077) == 0
    owner_ok = (st.st_uid == 0)

    allows = [a.strip() for a in
              re.findall(r"(?mi)^\s*allow\s+(.+?)\s*$", content)]
    creds, acls, wide = [], [], []
    for a in allows:
        first = a.split()[0] if a.split() else ""
        low   = first.lower().rstrip(",")
        if low.startswith("@") or (":" in low and not low.startswith("/")):
            creds.append("@group" if low.startswith("@") else "user:password")
        else:
            acls.append(low)
            if low in ("0.0.0.0/0.0.0.0", "0.0.0.0/0", "0.0.0.0",
                       "::/0", "::0/0", "any"):
                wide.append(low)

    notes = [f"config: {path}",
             f"mode: {oct(mode)} (monit requires no more than 0700)",
             f"allow lines: {len(allows)} "
             f"({len(creds)} credential, {len(acls)} host ACL)"]

    status = CHK_PASS
    if not allows:
        status = CHK_WARN
        notes.append("no `allow` line at all -- monit's HTTP interface has no "
                      "access control, and monit will not serve it either")
    elif not creds and wide:
        status = CHK_WARN
        notes.append(f"the only access control is a wide-open host ACL "
                      f"({', '.join(wide)}) with no credentials")
    elif not creds:
        notes.append("host-ACL access control only (no username/password); "
                      "acceptable when the ACL is loopback or a trusted subnet")
    if not mode_ok:
        status = _sec_worst([status, CHK_WARN])
        notes.append(f"mode {oct(mode)} grants group/other access -- any "
                      f"credentials in this file are readable by other users")
    if not owner_ok:
        status = _sec_worst([status, CHK_FAIL])
        notes.append(f"control file is owned by uid {st.st_uid}, not root -- "
                      f"monit requires the control file be owned by the user "
                      f"it runs as, and this node's monit runs as root, so "
                      f"monit will refuse to start against this file "
                      f"regardless of its mode")

    notes.append("auth configuration only -- whether port 2812 is bound or "
                  "firewalled is NOT checked (v1 limitation)")

    return _check_result(status, notes=notes, installed=True, mode=oct(mode),
                          mode_ok=mode_ok, owner_ok=owner_ok, owner_uid=st.st_uid,
                          allow_credentials=len(creds),
                          allow_host_acls=acls, allow_wide_open=wide,
                          has_allow=bool(allows), port_checked=False)

_SEC_DASH_UNIT       = "asl_dvs_dashboard.service"
_SEC_DASH_CANDIDATES = [
    Path("/usr/local/lib/asl_dvs_dashboard/asl_dvs_dashboard.py"),
    Path("/usr/local/bin/asl_dvs_dashboard.py"),
    Path("/opt/asl_dvs_dashboard/asl_dvs_dashboard.py"),
    Path("/usr/local/lib/asl_dvs_sysmon/asl_dvs_dashboard.py"),
]
_SEC_DASH_AUTH_MARKERS = ("_SESSION_COOKIE_NAME", "_require_auth", "/api/login")

def _check_dashboard_web_auth() -> dict:
    installed = _sec_unit_installed(_SEC_DASH_UNIT)

    src_path = ""
    exec_start, ran = _sec_run(
        ["systemctl", "show", "-p", "ExecStart", "--value", _SEC_DASH_UNIT])
    if ran and exec_start:
        m = re.search(r"(/\S+\.py)", exec_start)
        if m and Path(m.group(1)).exists():
            src_path = m.group(1)
    if not src_path:
        for cand in _SEC_DASH_CANDIDATES:
            if cand.exists():
                src_path = str(cand)
                break

    if not src_path:
        if not installed:
            return _check_result(CHK_PASS, notes=["asl_dvs_dashboard is not "
                                                   "installed on this node"],
                                  installed=False)
        return _check_result(CHK_WARN, notes=["dashboard service is installed but "
                                               "its source file could not be located "
                                               "-- cannot confirm it requires auth"],
                              installed=True)

    content, err = read_path_file(Path(src_path))
    if err:
        return _check_result(CHK_WARN, notes=[f"{src_path}: {err}"],
                              installed=True, source=src_path)

    found   = [m for m in _SEC_DASH_AUTH_MARKERS if m in content]
    missing = [m for m in _SEC_DASH_AUTH_MARKERS if m not in content]
    vm      = re.search(r'(?m)^\s*VERSION\s*=\s*["\']([^"\']+)["\']', content)
    version = vm.group(1) if vm else ""

    shared_ok = _SHARED_AUTH_DIR.exists()
    notes = [f"source: {src_path}",
             f"dashboard version: {version or 'unknown'}",
             f"auth markers found: {', '.join(found) if found else 'none'}"]
    if shared_ok:
        notes.append(f"shared session store present: {_SHARED_AUTH_DIR}")

    if not missing:
        status = CHK_PASS
    elif found:
        status = CHK_WARN
        notes.append(f"partial auth implementation -- missing: {', '.join(missing)}")
    else:
        status = CHK_FAIL
        notes.append("no session-auth markers at all -- this dashboard build "
                      "serves its API unauthenticated on port "
                      f"{DASHBOARD_PORT}")

    return _check_result(status, notes=notes, installed=True, source=src_path,
                          version=version, markers_found=found,
                          markers_missing=missing, probed=False)

_SEC_ROOT_EXEMPT_UNITS = _ROOT_EXEMPT_UNITS
_SEC_SELF_EXCLUDED_UNITS = {
    "sysmon.service", "instmon.service", "44helper.service",
    "wifimon.service",
}

_SEC_NONROOT_FLOOR_UNITS = [
    "asterisk.service", "fail2ban.service",
    "analog_bridge.service", "mmdvm_bridge.service", "md380-emu.service",
    "stfu.service", "usrp2m17.service", "analog_reflector.service",
    "asl_dvs_dashboard.service",
]

def _sec_nonroot_target_units() -> list:
    out, seen = [], set()
    for unit in _SEC_NONROOT_FLOOR_UNITS:
        if unit not in seen:
            seen.add(unit); out.append(unit)
    for entry in _pinned:
        unit = entry.get("unit", "")
        if (not unit or unit in seen or unit in _SEC_SELF_EXCLUDED_UNITS
                or not _validate_unit(unit)):
            continue
        seen.add(unit); out.append(unit)
    return out

def _check_service_nonroot() -> dict:
    rows:     list = []
    statuses: list = []

    present = [u for u in _sec_nonroot_target_units() if _sec_unit_installed(u)]
    props   = _sec_unit_props(present, ["Id", "User", "Group"])

    for unit in present:
        kv = props.get(unit)
        if kv is None:
            rows.append({"unit": unit, "user": "", "group": "",
                          "exempt": unit in _SEC_ROOT_EXEMPT_UNITS,
                          "verdict": CHK_WARN,
                          "note": "systemctl show returned nothing for this unit"})
            statuses.append(CHK_WARN)
            continue

        user    = kv.get("User", "")
        group   = kv.get("Group", "")
        as_root = (user == "" or user == "root")
        exempt  = unit in _SEC_ROOT_EXEMPT_UNITS

        if not as_root:
            verdict, note = CHK_PASS, f"runs as {user}"
        elif exempt:
            verdict, note = CHK_PASS, "root by design (documented exemption)"
        else:
            verdict, note = CHK_WARN, "runs as root but does not require it"

        rows.append({"unit": unit, "user": user or "root", "group": group,
                      "exempt": exempt, "verdict": verdict, "note": note})
        statuses.append(verdict)

    if not rows:
        return _check_result(CHK_WARN, units=[],
                              notes=["none of the target units are installed"])

    return _check_result(_sec_worst(statuses), units=rows,
                          notes=[f"{len(rows)} unit(s) inspected; exemptions: "
                                 f"{', '.join(sorted(_SEC_ROOT_EXEMPT_UNITS))}"])

_SEC_DROPIN_ROOTS = [
    Path("/etc/systemd/system"), Path("/run/systemd/system"),
    Path("/usr/lib/systemd/system"), Path("/lib/systemd/system"),
]

def _sec_unit_dropins(unit: str) -> list:
    out = []
    for root in _SEC_DROPIN_ROOTS:
        d = root / f"{unit}.d"
        try:
            if not d.is_dir():
                continue
            out.append(_stat_mode_info(str(d)))
            for f in sorted(d.glob("*.conf")):
                out.append(_stat_mode_info(str(f)))
        except Exception as exc:
            log.debug("security: dropins %s: %s", d, exc)
    return out

def _check_unit_file_perms() -> dict:
    present = [u for u in _sec_nonroot_target_units() if _sec_unit_installed(u)]
    props   = _sec_unit_props(present, ["Id", "FragmentPath", "ExecStart"])

    rows:     list = []
    statuses: list = []
    checked   = 0

    for unit in present:
        kv = props.get(unit)
        if kv is None:
            rows.append({"unit": unit, "verdict": CHK_WARN, "artifacts": [],
                          "note": "systemctl show returned nothing for this unit"})
            statuses.append(CHK_WARN)
            continue

        frag = (kv.get("FragmentPath") or "").strip()
        m    = _EXECSTART_PATH_RE.search(kv.get("ExecStart", "") or "")
        binp = m.group(1) if m else ""

        infos = []
        if frag:
            infos.append(_stat_mode_info(frag))
        if binp:
            infos.append(_stat_mode_info(binp))
        infos.extend(_sec_unit_dropins(unit))
        checked += len(infos)

        verdict, reasons = _perm_verdict(*infos)
        status = {"ok": CHK_PASS, "warn": CHK_WARN, "fail": CHK_FAIL}[verdict]
        if not frag:
            status  = _sec_worst([status, CHK_WARN])
            reasons.append("systemd reported no FragmentPath for this unit")

        rows.append({
            "unit":      unit,
            "verdict":   status,
            "reasons":   reasons,
            "artifacts": [{"path": i["path"], "mode": i["mode"],
                            "owner": f"{i['owner']}:{i['group']}" if i["exists"] else "",
                            "exists": i["exists"]} for i in infos],
        })
        statuses.append(status)

    if not rows:
        return _check_result(CHK_WARN, units=[], artifacts_checked=0,
                              notes=["none of the target units are installed"])

    return _check_result(
        _sec_worst(statuses), units=rows, artifacts_checked=checked,
        notes=[f"{len(rows)} unit(s), {checked} file(s)/directory(ies) inspected"])

def _sec_sshd_directives() -> "tuple[dict, list, list]":
    directives: dict = {}
    read_files: list = []
    truncated:  list = []
    seen:       set  = set()

    def _walk(path: Path, depth: int = 0) -> None:
        if depth > 4 or str(path) in seen:
            return
        seen.add(str(path))
        content, err = read_path_file(path)
        if err:
            return
        read_files.append(str(path))
        if "[truncated" in content:
            truncated.append(str(path))
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            key, val = parts[0].lower(), parts[1].strip()
            if key == "match":
                break
            if key == "include":
                for pattern in val.split():
                    if not pattern.startswith("/"):
                        pattern = str(_SEC_SSHD_CONFIG.parent / pattern)
                    try:
                        matches = sorted(Path("/").glob(pattern.lstrip("/")))
                    except Exception as exc:
                        log.debug("security: sshd Include %s: %s", pattern, exc)
                        continue
                    for m in matches:
                        if m.is_file():
                            _walk(m, depth + 1)
                continue
            directives.setdefault(key, val.split()[0].lower())

    if _SEC_SSHD_CONFIG.exists():
        _walk(_SEC_SSHD_CONFIG)
    try:
        if _SEC_SSHD_CONFIG_DIR.is_dir():
            for f in sorted(_SEC_SSHD_CONFIG_DIR.glob("*.conf")):
                _walk(f, 1)
    except Exception as exc:
        log.debug("security: sshd_config.d: %s", exc)

    return directives, read_files, truncated

def _check_ssh_hardening() -> dict:
    if not _SEC_SSHD_CONFIG.exists() and not _sec_have_binary("sshd"):
        return _check_result(CHK_PASS, notes=["no sshd on this node"],
                              installed=False)

    directives, files, truncated = _sec_sshd_directives()
    if not files:
        return _check_result(CHK_WARN, notes=["sshd_config present but unreadable"],
                              installed=True)
    if truncated:
        return _check_result(
            CHK_WARN,
            notes=["config file(s) exceed the 64 KB read cap and were "
                   "truncated -- directives past that point cannot be seen, "
                   "so no verdict can be trusted: " + ", ".join(truncated)],
            installed=True, files=files, truncated=truncated)

    permit_root = directives.get("permitrootlogin", "prohibit-password")
    password_au = directives.get("passwordauthentication", "yes")
    empty_pw    = directives.get("permitemptypasswords", "no")
    pubkey      = directives.get("pubkeyauthentication", "yes")

    findings: list = []
    status = CHK_PASS

    if permit_root == "yes":
        findings.append("PermitRootLogin yes -- direct root login over SSH")
        status = _sec_worst([status, CHK_FAIL])
    if empty_pw == "yes":
        findings.append("PermitEmptyPasswords yes -- accounts with no password "
                         "can log in")
        status = _sec_worst([status, CHK_FAIL])
    if password_au == "yes":
        findings.append("PasswordAuthentication yes -- brute-forceable without "
                         "key-only auth")
        status = _sec_worst([status, CHK_WARN])
    if pubkey == "no":
        findings.append("PubkeyAuthentication no -- key auth disabled")
        status = _sec_worst([status, CHK_WARN])
    if not findings:
        findings.append("root login and password auth are both restricted")

    return _check_result(
        status, installed=True, files=files, findings=findings,
        permit_root_login=permit_root, password_authentication=password_au,
        permit_empty_passwords=empty_pw, pubkey_authentication=pubkey)

def _check_fail2ban_jails() -> dict:
    if not _sec_have_binary("fail2ban-client"):
        return _check_result(CHK_WARN, installed=False, jails=[],
                              notes=["fail2ban is not installed -- recommended "
                                     "but not required, so this is a warning "
                                     "rather than a failure"])

    out, ran = _sec_run(["fail2ban-client", "status"])
    if not ran:
        return _check_result(CHK_WARN, installed=True, jails=[],
                              notes=["`fail2ban-client status` timed out or "
                                     "failed -- is fail2ban.service running?"])
    if not out:
        return _check_result(CHK_WARN, installed=True, jails=[],
                              notes=["fail2ban-client returned no status -- "
                                     "the server is probably not running"])

    m = re.search(r"Jail list:\s*(.*)", out)
    jails = [j.strip() for j in (m.group(1) if m else "").split(",") if j.strip()]

    if not jails:
        return _check_result(CHK_WARN, installed=True, jails=[],
                              notes=["fail2ban is running but has no active jails"])

    has_ssh = any("ssh" in j.lower() for j in jails)
    notes   = [f"active jails: {', '.join(jails)}"]
    status  = CHK_PASS
    if not has_ssh:
        status = CHK_WARN
        notes.append("no sshd jail among the active jails")

    return _check_result(status, installed=True, jails=jails, has_ssh_jail=has_ssh,
                          notes=notes)

def _check_asterisk_perms() -> dict:
    import grp, pwd, stat as _stat

    if not _SEC_ASTERISK_DIR.exists():
        return _check_result(CHK_WARN, notes=[f"{_SEC_ASTERISK_DIR} does not exist"])

    try:
        st   = _SEC_ASTERISK_DIR.stat()
        mode = _stat.S_IMODE(st.st_mode)
    except Exception as exc:
        return _check_result(CHK_WARN, notes=[f"{_SEC_ASTERISK_DIR}: {exc}"])

    perm   = mode & 0o777
    setgid = bool(mode & 0o2000)

    try:
        owner = pwd.getpwuid(st.st_uid).pw_name
    except Exception:
        owner = str(st.st_uid)
    try:
        group = grp.getgrgid(st.st_gid).gr_name
    except Exception:
        group = str(st.st_gid)

    notes  = [f"{_SEC_ASTERISK_DIR}: mode {oct(perm)}"
              f"{' +setgid' if setgid else ''} owner {owner}:{group} "
              f"(expected {oct(_SEC_ASTERISK_EXPECTED_MODE)} "
              f"root:{_SEC_ASTERISK_EXPECTED_GROUP})"]
    status = CHK_PASS

    if perm & 0o007:
        status = _sec_worst([status, CHK_FAIL])
        notes.append("directory is world-accessible -- any local user can read "
                      "the secrets in iax.conf/manager.conf")
    elif perm & ~_SEC_ASTERISK_EXPECTED_MODE:
        status = _sec_worst([status, CHK_WARN])
        notes.append(f"mode {oct(perm)} is looser than the expected "
                      f"{oct(_SEC_ASTERISK_EXPECTED_MODE)}")
    elif perm != _SEC_ASTERISK_EXPECTED_MODE:
        notes.append(f"mode {oct(perm)} is stricter than the expected "
                      f"{oct(_SEC_ASTERISK_EXPECTED_MODE)} -- fine, noted only")

    if owner != "root":
        status = _sec_worst([status, CHK_WARN])
        notes.append(f"owner is {owner}, expected root")
    if group != _SEC_ASTERISK_EXPECTED_GROUP and (perm & 0o070):
        status = _sec_worst([status, CHK_WARN])
        notes.append(f"group {group} has access but "
                      f"{_SEC_ASTERISK_EXPECTED_GROUP} was expected")

    files: list = []
    for fname in _SEC_ASTERISK_SECRET_FILES:
        fp = _SEC_ASTERISK_DIR / fname
        if not fp.exists():
            continue
        try:
            fmode = _stat.S_IMODE(fp.stat().st_mode) & 0o777
        except Exception as exc:
            log.debug("security: stat %s: %s", fp, exc)
            continue
        world = bool(fmode & 0o004)
        files.append({"file": fname, "mode": oct(fmode), "world_readable": world})
        if world:
            status = _sec_worst([status, CHK_FAIL])
            notes.append(f"{fname} is world-readable (mode {oct(fmode)}) -- it "
                          f"contains live IAX/AMI secrets")

    return _check_result(status, notes=notes, mode=oct(perm), setgid=setgid,
                          owner=owner, group=group,
                          expected_mode=oct(_SEC_ASTERISK_EXPECTED_MODE),
                          files=files)

def _detail_passthrough(raw: dict) -> dict:
    return dict(raw)

def _detail_iax2_secret_strength(raw: dict) -> dict:
    return {
        "evaluated":               raw.get("evaluated"),
        "reasons":                 raw.get("reasons"),
        "secret_matches_callsign": raw.get("secret_matches_callsign"),
        "secret_matches_node":     raw.get("secret_matches_node"),
        "secret_is_known_weak":    raw.get("secret_is_known_weak"),
        "secret_length":           raw.get("secret_length"),
    }

def _detail_ami_default_credentials(raw: dict) -> dict:
    return {
        "evaluated":               raw.get("evaluated"),
        "reasons":                 raw.get("reasons"),
        "username_is_default":     raw.get("username_is_default"),
        "secret_matches_callsign": raw.get("secret_matches_callsign"),
        "secret_is_known_weak":    raw.get("secret_is_known_weak"),
    }

def _detail_brandmeister_hotspot_password(raw: dict) -> dict:
    return {
        "evaluated":                 raw.get("evaluated"),
        "reasons":                   raw.get("reasons"),
        "password_matches_callsign": raw.get("password_matches_callsign"),
        "password_is_known_default": raw.get("password_is_known_default"),
        "password_length":           raw.get("password_length"),
    }

SECURITY_CHECKS = [
    {
        "id":       "usrp_port_exposure",
        "layer":    "usrp2m17",
        "label":    "USRP bridge port exposure",
        "severity": "high",
        "source":   "USRP2M17.ini [USRP NETWORK] DstPort/LocalPort, Analog_Bridge.ini "
                    "[USRP] rxPort/txPort, and rpt.conf rxchannel= lines, all "
                    "cross-referenced against a passive `ss -tlnpu` snapshot. Ports "
                    "are read from your config -- nothing here is hardcoded.",
        "meaning":  ("Whether the UDP ports that carry audio between Asterisk, "
                     "Analog_Bridge and usrp2m17 are reachable from outside this "
                     "host.\n\n"
                     "PASS -- every bind is on loopback, or on a VPN interface's own "
                     "address while that interface is up; or the port is configured "
                     "but nothing is listening on it.\n"
                     "WARN -- a bind sits on a VPN address whose interface is "
                     "currently down, or on an address that cannot be attributed to "
                     "any interface. Warn rather than fail: an unattributable address "
                     "is missing information, not proven exposure.\n"
                     "FAIL -- a bind is on 0.0.0.0 (every interface, including the "
                     "one facing your router) or on a LAN address.\n\n"
                     "The USRP link is normally entirely local: Asterisk and the "
                     "bridge run on the same Pi and talk over 127.0.0.1. The stock "
                     "pairing is 32001 (ASL listening) and 34001 (bridge listening); "
                     "this node's actual pair is whatever the files above say."),
        "risk":     ("USRP is a bare UDP transport. There is no authentication, no "
                     "session setup, no shared secret and no encryption -- a packet "
                     "that arrives on the port is accepted as audio and keying from "
                     "the peer, because the design assumes the peer is a process on "
                     "the same machine.\n\n"
                     "So anyone who can reach an exposed USRP port can key your "
                     "transmitter and put audio on the air under your callsign and "
                     "licence, inject that audio into every node currently linked to "
                     "yours, and listen to everything the node hears. There is "
                     "nothing to brute-force and nothing in the logs to rate-limit: "
                     "the first packet works. This is why the check treats 0.0.0.0 as "
                     "a failure even on a home LAN behind NAT -- a single "
                     "port-forward, UPnP rule or compromised device on that LAN is "
                     "the whole distance between 'local only' and 'anyone'."),
        "remediation": ("Bind both ends to 127.0.0.1. In USRP2M17.ini the USRP "
                         "address belongs on loopback; in rpt.conf the rxchannel line "
                         "should read USRP/127.0.0.1:<local>:<dst>.\n\n"
                         "If you genuinely bridge between two hosts, do it inside "
                         "WireGuard or Tailscale and bind to that interface's "
                         "address rather than 0.0.0.0 -- then this check passes while "
                         "the tunnel is up.\n\n"
                         "Add a firewall rule for the UDP port regardless: binding "
                         "and firewalling are independent layers, and the bind is the "
                         "one a config edit can silently undo."),
        "references": [
            {"label": "M17 Project wiki -- usrp2m17 bridge (USRP port pairing)",
             "url":   "https://wiki.m17.link/usrp2m17_bridge"},
            {"label": "AllStarLink manual -- what's new in ASL3",
             "url":   "https://allstarlink.github.io/install/whats-new/"},
            {"label": "ss(8) -- the listening-socket snapshot this check reads",
             "url":   "https://manpages.debian.org/trixie/iproute2/ss.8.en.html"},
        ],
        "check_fn":  _check_usrp_port_exposure,
        "detail_fn": _detail_passthrough,
        "sensitive": False,
    },
    {
        "id":       "m17_port_exposure",
        "layer":    "usrp2m17",
        "label":    "M17 gateway port exposure",
        "severity": "high",
        "source":   "USRP2M17.ini [M17 NETWORK] LocalPort/DstPort/Address, "
                    "cross-referenced against a passive `ss -tlnpu` snapshot.",
        "meaning":  ("The same exposure logic as the USRP check, applied to the "
                     "M17-side UDP port the bridge uses to reach reflectors. UDP "
                     "17000 is the standardised default in the M17 specification "
                     "(\"recommended but not required\"), so a node may legitimately "
                     "use another.\n\n"
                     "PASS -- loopback, or a VPN address with the interface up, or "
                     "nothing listening.\n"
                     "WARN -- VPN address with the interface down, or an "
                     "unattributable address.\n"
                     "FAIL -- 0.0.0.0 or a LAN address.\n\n"
                     "The panel also notes when USRP2M17.ini still carries the "
                     "0.0.0.0 placeholder address, which means the bridge is not "
                     "pointed at a reflector at all."),
        "risk":     ("The M17 reflector protocol has no authentication whatsoever. A "
                     "client announces itself with a CONN packet carrying a 6-byte "
                     "callsign and a module letter; the reflector replies ACKN. There "
                     "is no password, no key exchange, and no encryption in the "
                     "default configuration -- the callsign in the packet is simply "
                     "believed.\n\n"
                     "Connecting OUT to a reflector needs no inbound exposure at all. "
                     "If the port is nonetheless open to the world, anyone who finds "
                     "it can send voice frames straight into your bridge, which "
                     "relays them to your node and onto the air, stamped with "
                     "whatever callsign the sender chose to put in the packet."),
        "remediation": ("Bind the M17 local port to 127.0.0.1 or a VPN address. "
                         "Outbound reflector connections keep working -- the bridge "
                         "initiates them, and the reply arrives on the same flow.\n\n"
                         "If something genuinely must reach the port from outside, "
                         "firewall it to the specific reflector addresses you use, "
                         "rather than leaving it open to the internet."),
        "references": [
            {"label": "M17 specification -- IP networking, CONN/ACKN packets and port 17000",
             "url":   "https://m17-protocol-specification.readthedocs.io/en/latest/ip_encapsulation.html"},
            {"label": "M17 Project wiki -- usrp2m17 bridge configuration",
             "url":   "https://wiki.m17.link/usrp2m17_bridge"},
            {"label": "ss(8) -- the listening-socket snapshot this check reads",
             "url":   "https://manpages.debian.org/trixie/iproute2/ss.8.en.html"},
        ],
        "check_fn":  _check_m17_port_exposure,
        "detail_fn": _detail_passthrough,
        "sensitive": False,
    },
    {
        "id":       "ami_port_exposure",
        "layer":    "asl",
        "label":    "Asterisk Manager Interface (AMI) port exposure",
        "severity": "high",
        "source":   "manager.conf [general] enabled=/bindaddr=/port=, cross-referenced "
                    "against a passive `ss -tlnpu` snapshot. Asterisk's shipped sample "
                    "has enabled=yes, port=5038 and bindaddr=0.0.0.0, so an untouched "
                    "manager.conf is an exposed one.",
        "meaning":  ("Where the Asterisk Manager Interface is listening.\n\n"
                     "PASS -- AMI is disabled, or bound to loopback, or bound to a "
                     "VPN address whose interface is up.\n"
                     "WARN -- the VPN interface is down, or the address cannot be "
                     "attributed to an interface.\n"
                     "FAIL -- bound to 0.0.0.0 or a LAN address, regardless of VPN "
                     "state.\n\n"
                     "The configured bindaddr is judged even when nothing is "
                     "listening, so a stopped Asterisk cannot hide a bad setting.\n\n"
                     "KNOWN v1 LIMITATION: this reads the bind address only. It does "
                     "NOT evaluate manager.conf's permit=/deny= ACL lines, so a node "
                     "bound to a private address with a wide-open "
                     "permit=0.0.0.0/0.0.0.0 passes here. The panel reports whether "
                     "ACL lines exist at all (acl_lines_present) and states "
                     "acl_checked=false so the gap is visible rather than implied. "
                     "Evaluating those ACL lines is a tracked v1.1 candidate."),
        "risk":     ("AMI is manager-level control of Asterisk over a plaintext TCP "
                     "socket. Credentials and traffic cross the wire in cleartext "
                     "unless you have configured MD5 challenge auth or TLS.\n\n"
                     "Treat an exposed AMI as host compromise, not information "
                     "disclosure. CVE-2024-42365 (CVSS 7.4) showed that an AMI "
                     "account holding only write=originate -- long assumed to be a "
                     "low-privilege setting -- could chain the FILE()/CURL() dialplan "
                     "functions to write into /etc/asterisk, reload, and execute "
                     "arbitrary commands. It affects Asterisk up to and including "
                     "20.9.1, which is the version family ASL3 is built on, and it "
                     "works regardless of the live_dangerously setting. Separately, "
                     "an account with the `command` class can run any Asterisk CLI "
                     "command by design.\n\n"
                     "AMI has no built-in lockout or rate limiting either, so an "
                     "exposed port is also an unlimited password-guessing oracle."),
        "remediation": ("Set bindaddr=127.0.0.1 in manager.conf [general] -- or "
                         "enabled=no if nothing on this node uses AMI. Allmon3 and "
                         "similar tools run locally and are happy on loopback.\n\n"
                         "Patch Asterisk to 20.9.2 or later for CVE-2024-42365.\n\n"
                         "Regardless of bind address, write an explicit ACL: "
                         "deny=0.0.0.0/0.0.0.0 first, then permit only the addresses "
                         "that need it. Give each consumer its own account with the "
                         "narrowest read=/write= classes that work, and keep "
                         "`command` and `originate` off monitoring accounts."),
        "references": [
            {"label": "CVE-2024-42365 -- AMI write=originate is sufficient for code execution",
             "url":   "https://github.com/asterisk/asterisk/security/advisories/GHSA-c4cg-9275-6w44"},
            {"label": "Asterisk docs -- privilege escalation with dialplan functions (live_dangerously)",
             "url":   "https://docs.asterisk.org/Configuration/Dialplan/Privilege-Escalations-with-Dialplan-Functions/"},
            {"label": "manager.conf reference -- plaintext protocol, permit/deny, permission classes",
             "url":   "https://www.voip-info.org/asterisk-config-managerconf/"},
            {"label": "ss(8) -- the listening-socket snapshot this check reads",
             "url":   "https://manpages.debian.org/trixie/iproute2/ss.8.en.html"},
        ],
        "check_fn":  _check_ami_port_exposure,
        "detail_fn": _detail_passthrough,
        "sensitive": False,
    },
    {
        "id":       "ami_default_credentials",
        "layer":    "asl",
        "label":    "AMI default/weak credentials",
        "severity": "high",
        "source":   "manager.conf user sections -- the stanza name (the AMI username) "
                    "and its secret=.",
        "meaning":  ("Grades every AMI account on this node.\n\n"
                     "FAIL -- a secret that is empty, a known-weak or vendor-default "
                     "string, a single repeated character, or equal to this node's "
                     "callsign, node number or DMR ID.\n"
                     "WARN -- a predictable username (admin, manager, asterisk, "
                     "allmon, monitor...) with an otherwise sound secret, or a unique "
                     "secret shorter than eight characters.\n"
                     "PASS -- a non-obvious username with a secret that matches none "
                     "of the above.\n\n"
                     "A predictable username on its own is only a warning: it halves "
                     "the guessing work but is worth little against a strong "
                     "secret.\n\n"
                     "The secret itself never leaves the backend. The check converts "
                     "it to booleans before it is placed in any result, and the "
                     "registry's detail_fn whitelists named fields on top of that -- "
                     "the redaction is proven at import time by a poison probe, not "
                     "promised by a comment."),
        "risk":     ("Your callsign, node number and DMR ID are public directory data "
                     "-- they are in the AllStarLink node list, on QRZ and on the "
                     "BrandMeister dashboard. A secret equal to any of them is not a "
                     "secret; it is a lookup.\n\n"
                     "What a guessed AMI password buys an attacker is severe: full "
                     "manager control of Asterisk, and on any Asterisk up to 20.9.1 "
                     "the CVE-2024-42365 path from a mere write=originate account to "
                     "arbitrary command execution on the Pi. Asterisk applies no "
                     "lockout or delay to failed AMI logins, so guessing is limited "
                     "only by bandwidth."),
        "remediation": ("Generate a real secret -- `openssl rand -hex 24` -- and give "
                         "the account a name that is not in every wordlist. One "
                         "account per consuming application, each with the narrowest "
                         "read=/write= classes it actually needs.\n\n"
                         "manager.conf holds that secret in cleartext, so keep it at "
                         "mode 640 owned root:asterisk (the /etc/asterisk permissions "
                         "check on this page covers that), and prefer loopback-only "
                         "AMI over any credential strength."),
        "references": [
            {"label": "CVE-2024-42365 -- what a low-privilege AMI account is worth to an attacker",
             "url":   "https://github.com/asterisk/asterisk/security/advisories/GHSA-c4cg-9275-6w44"},
            {"label": "manager.conf reference -- cleartext auth, permission classes",
             "url":   "https://www.voip-info.org/asterisk-config-managerconf/"},
        ],
        "check_fn":  _check_ami_default_credentials,
        "detail_fn": _detail_ami_default_credentials,
        "sensitive": True,
    },
    {
        "id":       "iax2_secret_strength",
        "layer":    "asl",
        "label":    "IAX2 secret strength",
        "severity": "medium",
        "source":   "iax.conf user/peer secret= entries and any register=> lines; "
                    "falls back to rpt_http_registrations.conf to tell a modern "
                    "HTTP-registered node from an unconfigured one.",
        "meaning":  ("Grades the IAX2 secrets this node presents or accepts on UDP "
                     "4569.\n\n"
                     "FAIL -- a secret that is empty, known-weak, a single repeated "
                     "character, or equal to the callsign, node number or DMR ID.\n"
                     "WARN -- a unique secret shorter than eight characters, or no "
                     "IAX2 secret at all on a node that also has no HTTP "
                     "registration configured.\n"
                     "PASS -- everything graded looks unguessable, or the node "
                     "registers over HTTP and defines no local IAX client stanza.\n\n"
                     "Two deliberate exemptions, both to avoid crying wolf on a "
                     "correct ASL3 config. The documented [allstar-public] stanza "
                     "ships with secret = allstar and is skipped -- the ASL manual "
                     "notes that connection is authenticated further down the chain "
                     "by token validation. And ASL3 deprecated iax.conf register= in "
                     "favour of rpt_http_registrations.conf, so a node with neither a "
                     "register= line nor a client stanza is modern, not broken.\n\n"
                     "Only booleans and the shortest length are reported; no secret "
                     "value leaves the backend.\n\n"
                     "NOT CHECKED (v1.1 candidate): requirecalltoken. Asterisk's "
                     "own default is yes, but the stock configuration is NOT clean "
                     "here: ASL3's shipped iax.conf sets requirecalltoken = no "
                     "inside the [iaxrpt](!) template, which IAXRpt and DVSwitch "
                     "Mobile phone-mode clients inherit. That is deliberate -- the "
                     "AllStarLink manual notes most common ASL client applications "
                     "do not support call tokens -- so it is not something to fix. "
                     "It does mean those stanzas rely on the secret alone, which is "
                     "what this check grades."),
        "risk":     ("IAX2 is how AllStar nodes link. A guessed secret lets someone "
                     "connect to your node as a trusted peer and transmit through "
                     "your repeater under your licence -- and the guess is easy when "
                     "the secret is the callsign or node number, because both are "
                     "published in the AllStarLink node list.\n\n"
                     "Call tokens (requirecalltoken) address a different problem: "
                     "they stop an attacker with a spoofed source address from "
                     "exhausting your finite pool of IAX2 call numbers, which would "
                     "deny service to legitimate links. They do nothing about a weak "
                     "secret, which is what this check grades.\n\n"
                     "Where your node actually stands on them: Asterisk defaults to "
                     "yes, but ASL3 ships requirecalltoken = no in the [iaxrpt](!) "
                     "template for client compatibility. Stanzas inheriting it have "
                     "no call-token protection, so the secret is the only thing in "
                     "front of them."),
        "remediation": ("Use a long random secret -- `openssl rand -hex 24` -- for "
                         "every stanza this check flags, and rotate any that were "
                         "flagged: a value derived from your callsign should be "
                         "treated as already known.\n\n"
                         "Leave requirecalltoken alone. Switching it on for "
                         "[iaxrpt] would break the phone-mode clients it was "
                         "switched off for, and it was never what protects your "
                         "secret. Remember too that 4569/UDP has to be open for "
                         "IAX2 to work at all, so closing the port is not a "
                         "mitigation either. The secret is the control that matters "
                         "here, and on the [iaxrpt] stanzas it is the only one."),
        "references": [
            {"label": "Asterisk docs -- IAX2 security and call token validation",
             "url":   "https://docs.asterisk.org/Configuration/Channel-Drivers/Inter-Asterisk-eXchange-protocol-version-2-IAX2/IAX2-Security/"},
            {"label": "iax.conf sample -- requirecalltoken defaults to yes",
             "url":   "https://github.com/asterisk/asterisk/blob/master/configs/samples/iax.conf.sample"},
            {"label": "AllStarLink manual -- iax.conf, [allstar-public] and HTTP registration",
             "url":   "https://allstarlink.github.io/config/iax_conf/"},
        ],
        "check_fn":  _check_iax2_secret_strength,
        "detail_fn": _detail_iax2_secret_strength,
        "sensitive": True,
    },
    {
        "id":       "brandmeister_hotspot_password",
        "layer":    "dvswitch",
        "label":    "BrandMeister hotspot password",
        "severity": "medium",
        "source":   "MMDVM_Bridge.ini [DMR Network] Enable=/Password=.",
        "meaning":  ("Grades the DMR network password this node presents to its "
                     "master server.\n\n"
                     "FAIL -- empty, a known default, or equal to the callsign or DMR "
                     "ID. The single most common finding here is passw0rd, which is "
                     "the literal value DVSwitch ships in the MMDVM_Bridge.ini sample "
                     "([DMR Network] Address=hblink.dvswitch.org, Port=62031, "
                     "Local=62032, Password=passw0rd) -- so a node that was never "
                     "edited fails on the stock file.\n"
                     "WARN -- MMDVM_Bridge is installed but its INI is missing or "
                     "unreadable.\n"
                     "PASS -- a unique-looking password, or [DMR Network] disabled, "
                     "or MMDVM_Bridge not installed at all. There is nothing to "
                     "protect in the last two cases, so this check stays quiet rather "
                     "than warning forever on a node that does no DMR.\n\n"
                     "Only booleans and length are reported."),
        "risk":     ("On BrandMeister the hotspot security password is what binds "
                     "your DMR ID to your device on the master server. Anyone who "
                     "knows it can connect their own hotspot as you: traffic they "
                     "originate appears on the network, and on the public "
                     "BrandMeister dashboard, as your DMR ID and callsign. You would "
                     "be answering for it.\n\n"
                     "BrandMeister strongly recommends a personalised password "
                     "precisely because shared and default values made this "
                     "trivial, and some masters now enforce it -- but many still "
                     "accept the shipped one, which is why this check exists. Were "
                     "it universally mandatory, a node still set to passw0rd simply "
                     "would not connect, and you would learn that from the failed "
                     "link rather than from here. Connecting successfully is "
                     "therefore not evidence that this is set. A password left at "
                     "the shipped passw0rd is equivalent to no password at all."),
        "remediation": ("Set a personalised password in BrandMeister SelfCare -- log "
                         "in on the dashboard, click your callsign, open SelfCare, "
                         "then the Radio ID tab, and use the Hotspot Security "
                         "section at the bottom. Mirror the same value into "
                         "MMDVM_Bridge.ini [DMR Network] Password.\n\n"
                         "Mind BrandMeister's constraints: 20 characters or fewer, "
                         "and no special characters. `openssl rand -hex 10` gives "
                         "exactly 20 hex characters and satisfies both.\n\n"
                         "If this node does no DMR, set Enable=0 in [DMR Network] "
                         "rather than leaving a default password pointed at a live "
                         "master."),
        "references": [
            {"label": "BrandMeister docs -- Hotspot Security password (SelfCare, 20 chars, no specials)",
             "url":   "https://help.brandmeister.network/dashboard/hotspot-security/"},
            {"label": "DVSwitch MMDVM_Bridge.ini sample -- ships Password = passw0rd",
             "url":   "https://github.com/DVSwitch/MMDVM_Bridge/blob/master/MMDVM_Bridge.ini"},
        ],
        "check_fn":  _check_brandmeister_hotspot_password,
        "detail_fn": _detail_brandmeister_hotspot_password,
        "sensitive": True,
    },
    {
        "id":       "chan_sip_disabled",
        "layer":    "asl",
        "label":    "Legacy chan_sip module disabled",
        "severity": "low",
        "source":   "modules.conf load/noload state, plus `asterisk -rx 'module show "
                    "like chan_sip'` and -- only when it turns out to be loaded -- "
                    "`asterisk -rx 'sip show peers'`.",
        "meaning":  ("Whether the obsolete chan_sip channel driver is loaded.\n\n"
                     "PASS -- not loaded in the running Asterisk.\n"
                     "WARN -- loaded with no configured peers, or the Asterisk CLI "
                     "was unreachable and modules.conf does not noload it.\n"
                     "FAIL -- loaded with configured peers.\n\n"
                     "Version context matters here: chan_sip was deprecated in "
                     "Asterisk 17 and removed outright in Asterisk 21. ASL3 runs on "
                     "Asterisk 20, which is the last family that still has it -- so "
                     "on this node it is genuinely possible to be carrying an "
                     "unmaintained SIP stack, which is exactly why the check exists. "
                     "It is rated low severity because a default ASL3 node does not "
                     "load it."),
        "risk":     ("A loaded chan_sip binds UDP 5060 and answers anything that asks "
                     "-- and 5060 is among the most relentlessly scanned ports on the "
                     "internet. Scanners enumerate extensions, then brute-force them, "
                     "and the payoff they are looking for is toll fraud: calls placed "
                     "through your box to premium-rate numbers, billed to whatever "
                     "trunk it can reach.\n\n"
                     "The module is also no longer maintained. Security fixes land in "
                     "chan_pjsip; chan_sip is frozen and then gone in the next major "
                     "version. Running it on a node that does not need SIP at all is "
                     "attack surface bought for nothing."),
        "remediation": ("If nothing on this node uses SIP, put `noload => chan_sip.so` "
                         "in /etc/asterisk/modules.conf and restart Asterisk.\n\n"
                         "If you do want a SIP phone on the node, use chan_pjsip -- "
                         "that is what the ASL3 manual documents, and Asterisk ships "
                         "contrib/scripts/sip_to_pjsip/sip_to_pjsip.py to convert an "
                         "existing sip.conf. Doing this now also means Asterisk 21+ "
                         "will not break the node when it removes chan_sip entirely."),
        "references": [
            {"label": "Asterisk -- chan_sip removal in Asterisk 21 (deprecated in 17)",
             "url":   "https://www.asterisk.org/asterisk-21-module-removal-chan_sip/"},
            {"label": "AllStarLink manual -- setting up a SIP phone with chan_pjsip",
             "url":   "https://allstarlink.github.io/adv-topics/sip-phone/"},
        ],
        "check_fn":  _check_chan_sip_disabled,
        "detail_fn": _detail_passthrough,
        "sensitive": False,
    },
    {
        "id":       "ssh_hardening",
        "layer":    "cross-cutting",
        "label":    "SSH hardening",
        "severity": "medium",
        "source":   "/etc/ssh/sshd_config with Include directives expanded IN PLACE, "
                    "so /etc/ssh/sshd_config.d/*.conf takes the precedence sshd "
                    "actually gives it. Parsed rather than queried with `sshd -T`, "
                    "which needs a valid host key and fails on exactly the "
                    "half-configured box worth checking.",
        "meaning":  ("Grades the four directives that decide how hard this node is to "
                     "log into.\n\n"
                     "FAIL -- PermitRootLogin yes, or PermitEmptyPasswords yes.\n"
                     "WARN -- PasswordAuthentication yes, or PubkeyAuthentication "
                     "no.\n"
                     "PASS -- root login and password auth are both restricted, or "
                     "there is no sshd on this node at all.\n\n"
                     "Where a value is not stated anywhere, OpenSSH's own defaults "
                     "are assumed: PermitRootLogin prohibit-password, "
                     "PasswordAuthentication yes, PubkeyAuthentication yes, "
                     "PermitEmptyPasswords no.\n\n"
                     "Precedence is the subtle part. sshd_config(5) says \"for each "
                     "keyword, the first obtained value will be used\", and Debian "
                     "and Raspberry Pi OS put `Include /etc/ssh/sshd_config.d/*.conf` "
                     "at the TOP of the file -- so a drop-in overrides the main file, "
                     "not the other way round. This check follows that ordering, "
                     "which means it reports what sshd is really using rather than "
                     "the first line you happen to find with grep."),
        "risk":     ("A repeater node is a small Linux box with a public IP or a "
                     "forwarded port, and SSH is the front door. Password auth plus "
                     "root login is the combination automated scanners are built for: "
                     "they find the port in minutes and then guess continuously, "
                     "forever, at no cost.\n\n"
                     "There is a sysmon-specific twist. This tool and the dashboard "
                     "authenticate against the box's own root password -- that is the "
                     "whole credential store. So a weak or guessable root password is "
                     "not only an SSH exposure; it is also the login to the web "
                     "interface that can restart services, rewrite systemd units and "
                     "edit Asterisk configs. The two share a fate."),
        "remediation": ("Put your public key in ~/.ssh/authorized_keys and confirm it "
                         "works before changing anything else. Then create "
                         "/etc/ssh/sshd_config.d/99-hardening.conf with "
                         "PermitRootLogin prohibit-password and "
                         "PasswordAuthentication no, and restart sshd.\n\n"
                         "Verify with `sshd -T | grep -Ei "
                         "'permitrootlogin|passwordauth'` -- that prints what the "
                         "daemon resolved, which is the number that counts.\n\n"
                         "Keep a second way in (console or an existing session) until "
                         "you have proven the new config works."),
        "references": [
            {"label": "sshd_config(5) -- first obtained value wins, Include, and defaults",
             "url":   "https://man.openbsd.org/sshd_config"},
            {"label": "sshd_config(5), Debian build -- the Include note that decides precedence here",
             "url":   "https://manpages.debian.org/trixie/openssh-server/sshd_config.5.en.html"},
        ],
        "check_fn":  _check_ssh_hardening,
        "detail_fn": _detail_passthrough,
        "sensitive": False,
    },
    {
        "id":       "fail2ban_jails",
        "layer":    "cross-cutting",
        "label":    "fail2ban jail coverage",
        "severity": "medium",
        "source":   "`fail2ban-client status` -- the ACTIVE jail list from the running "
                    "server, not merely the presence of a jail.local file.",
        "meaning":  ("PASS -- fail2ban is running with at least one active jail, and "
                     "one of them covers sshd.\n"
                     "WARN -- fail2ban is not installed, is installed but not "
                     "running, has no active jails, or has jails but none for "
                     "sshd.\n\n"
                     "Absence is a warning rather than a failure on purpose: "
                     "fail2ban is a good idea, not a requirement, and a node that "
                     "allows no password logins at all has far less need of it.\n\n"
                     "The check deliberately asks the daemon instead of reading "
                     "config. A jail defined in jail.local but never started -- "
                     "because of a typo, a missing log path or a failed reload -- "
                     "protects nothing, and reading the file would have called that "
                     "a pass."),
        "risk":     ("Without fail2ban, a scanner that finds your SSH port gets "
                     "unlimited attempts. With it, the same scanner gets a handful "
                     "before the source address is dropped at the firewall. On "
                     "Debian the sshd jail is the one enabled out of the box, which "
                     "covers the common case.\n\n"
                     "Be clear about what it cannot do, though. fail2ban works by "
                     "reading logs for authentication failures, so it only protects "
                     "services that authenticate and log. USRP and M17 do neither -- "
                     "there is no failed login to notice, because there is no login. "
                     "For those, binding to loopback and firewalling are the whole "
                     "defence, and fail2ban is no substitute for them."),
        "remediation": ("`apt install fail2ban`, then confirm with `fail2ban-client "
                         "status` that the sshd jail is actually in the list -- "
                         "installing the package is not the same as running the "
                         "jail.\n\n"
                         "fail2ban ships filters for many services; if this node "
                         "exposes SIP or IAX2 to the internet, an Asterisk jail "
                         "pointed at /var/log/asterisk/security.log is worth adding "
                         "on top."),
        "references": [
            {"label": "fail2ban project -- filters, jails and fail2ban-client",
             "url":   "https://github.com/fail2ban/fail2ban"},
            {"label": "jail.conf(5) -- jail definitions and enabled state",
             "url":   "https://manpages.debian.org/trixie/fail2ban/jail.conf.5.en.html"},
            {"label": "fail2ban-client(1) -- the command this check reads jail status from",
             "url":   "https://manpages.debian.org/trixie/fail2ban/fail2ban-client.1.en.html"},
        ],
        "check_fn":  _check_fail2ban_jails,
        "detail_fn": _detail_passthrough,
        "sensitive": False,
    },
    {
        "id":       "monit_auth",
        "layer":    "cross-cutting",
        "label":    "Monit authentication configured",
        "severity": "medium",
        "source":   "the monitrc file mode plus its `allow` lines "
                    "(/etc/monit/monitrc, /etc/monitrc, /etc/monit.conf).",
        "meaning":  ("Whether Monit's web interface has real access control.\n\n"
                     "PASS -- at least one credential-bearing allow line "
                     "(`allow user:password` or `allow @group`), or a host ACL that "
                     "is not wide open, with the file mode no wider than 0700. Also "
                     "passes when monit is not installed.\n"
                     "WARN -- no allow line at all; or the only access control is a "
                     "wide-open host ACL such as `allow 0.0.0.0/0.0.0.0` with no "
                     "credentials; or the file is readable by group or other; or it "
                     "cannot be read.\n\n"
                     "Two details this check gets right that a naive version gets "
                     "wrong. Monit's own requirement is that the control file have "
                     "permissions \"no more than 0700\" -- it refuses to start "
                     "otherwise -- so 0700 is correct and demanding exactly 0600 "
                     "would warn about a conforming file. And `allow` means two "
                     "different things: a credential, or a host ACL. Counting any "
                     "allow line as authentication would pass a monitrc whose only "
                     "directive is `allow 0.0.0.0/0.0.0.0`.\n\n"
                     "KNOWN v1 LIMITATION: this reads auth configuration only. "
                     "Whether port 2812 is bound to localhost or firewalled is NOT "
                     "checked -- that is a tracked v1.1 candidate. The label says "
                     "\"auth configured\" and never \"secured\" for exactly that "
                     "reason -- a PASS here does not mean the port is safe."),
        "risk":     ("Monit's web interface does more than display status: it can "
                     "start, stop and restart the services it monitors. An unguarded "
                     "one on a reachable address is a remote control for the node.\n\n"
                     "Basic-auth credentials are sent base64-encoded, which is "
                     "encoding and not encryption, so they are readable by anyone on "
                     "the path unless SSL is configured. And because the monitrc "
                     "holds those credentials in cleartext, its file mode is part of "
                     "the control, not a detail -- which is why monit enforces the "
                     "permission itself."),
        "remediation": ("Bind the interface to loopback with `use address 127.0.0.1` "
                         "inside the `set httpd` block, and keep an `allow "
                         "localhost` alongside a real `allow user:password`.\n\n"
                         "`chmod 600 /etc/monit/monitrc`. If the interface must be "
                         "reachable from elsewhere, add SSL and restrict the host "
                         "ACL to specific addresses -- and firewall 2812 as well, "
                         "since that is the part this check cannot see."),
        "references": [
            {"label": "Monit documentation -- control file permissions, allow forms, httpd security",
             "url":   "https://www.mmonit.com/monit/documentation/monit.html"},
            {"label": "monit(1) -- control file must be no more than 0700, and the allow forms",
             "url":   "https://manpages.debian.org/trixie/monit/monit.1.en.html"},
        ],
        "check_fn":  _check_monit_auth,
        "detail_fn": _detail_passthrough,
        "sensitive": False,
    },
    {
        "id":       "dashboard_web_auth",
        "layer":    "cross-cutting",
        "label":    "Dashboard companion app requires auth",
        "severity": "high",
        "source":   "the installed asl_dvs_dashboard source, located via `systemctl "
                    "show -p ExecStart` and scanned for the session-auth markers "
                    "(_SESSION_COOKIE_NAME, _require_auth, /api/login), plus the "
                    "presence of the shared session store at /run/asl_dvs.",
        "meaning":  ("Whether the dashboard on port 8989 enforces the same session "
                     "auth sysmon does.\n\n"
                     "PASS -- all auth markers present, or the dashboard is not "
                     "installed on this node.\n"
                     "WARN -- a partial implementation, or the service is installed "
                     "but its source file could not be located to confirm.\n"
                     "FAIL -- the installed build carries no session-auth markers at "
                     "all.\n\n"
                     "This check reads the dashboard's source. It never connects to "
                     "port 8989 -- no check on this page opens a socket, which is "
                     "what keeps running the tab from writing entries into the very "
                     "logs an operator is trying to read."),
        "risk":     ("sysmon and the dashboard deliberately share one session table "
                     "at /run/asl_dvs/auth_session.json, so that logging into either "
                     "authenticates both. That convenience runs in reverse too: an "
                     "unauthenticated dashboard is an unauthenticated path to the "
                     "same node control sysmon carefully gates.\n\n"
                     "This is not hypothetical. Before v8.1.0 the dashboard served "
                     "its API to anyone who could reach the port, and sysmon itself "
                     "had no authentication at all until v6.6.0 -- where "
                     "/api/unit_file plus /api/svc was a two-request path from "
                     "unauthenticated to root. Both were fixed the same way. This "
                     "check exists so a downgrade or a half-finished upgrade of the "
                     "companion app cannot quietly reopen that door."),
        "remediation": ("Run asl_dvs_dashboard v8.1.0 or later -- the build that "
                         "added session auth and the shared session table -- and "
                         "restart it after upgrading.\n\n"
                         "There is no separate credential to set: both apps "
                         "authenticate against the box's root password, so the "
                         "strength of that password is the strength of both web "
                         "interfaces. See also the SSH hardening check on this page, "
                         "which grades the same secret from the other direction."),
        "references": [
            {"label": "Project doc: Security_Audit_asl_dvs_dashboard_v8.0.6.md (findings behind the v8.1.0 fix)",
             "url":   ""},
            {"label": "Project doc: Security_Audit_sysmon_v6.5.32.md (findings 1 and 2, fixed in sysmon v6.6.0)",
             "url":   ""},
        ],
        "check_fn":  _check_dashboard_web_auth,
        "detail_fn": _detail_passthrough,
        "sensitive": False,
    },
    {
        "id":       "asterisk_perms",
        "layer":    "asl",
        "label":    "/etc/asterisk permissions",
        "severity": "low",
        "source":   "stat() on /etc/asterisk and on iax.conf, manager.conf and "
                    "rpt.conf inside it.",
        "meaning":  ("Whether the directory holding this node's cleartext secrets is "
                     "readable by accounts that should not have them. Expected: mode "
                     "0750, owner root:asterisk.\n\n"
                     "FAIL -- the directory is world-accessible, or a secret-bearing "
                     "config file is world-readable.\n"
                     "WARN -- the mode is LOOSER than expected (group-writable, say), "
                     "the owner is not root, or a different group has access.\n"
                     "PASS -- as expected, or stricter.\n\n"
                     "Two things this check is careful about. A mode tighter than "
                     "0750, such as 0700, is better than the expectation and is "
                     "noted rather than warned about. And Debian's asterisk "
                     "packaging ships /etc/asterisk setgid (02750); the setgid bit is "
                     "reported separately instead of being mistaken for a wrong "
                     "permission, which would warn on a stock, correct install."),
        "risk":     ("iax.conf and manager.conf hold live secrets in cleartext -- "
                     "Asterisk has no other way to use them. If those files are "
                     "readable beyond root and the asterisk group, then every local "
                     "account, and every service running as a non-root user, can "
                     "read the node's IAX2 secrets and AMI passwords.\n\n"
                     "That turns a small compromise into a large one. A bug in some "
                     "unrelated daemon running as `nobody` becomes IAX2 link access "
                     "and AMI credentials -- and, on an Asterisk older than 20.9.2, "
                     "AMI credentials are a route to running commands as root via "
                     "CVE-2024-42365. This is rated low severity only because it "
                     "needs a foothold on the box first; given one, it is the step "
                     "that makes the foothold matter."),
        "remediation": ("`chown root:asterisk /etc/asterisk` and `chmod 750 "
                         "/etc/asterisk`, then `chmod 640` the config files inside "
                         "it. Keeping the setgid bit (2750) is fine.\n\n"
                         "If you edit these files as a normal user or copy them "
                         "around, re-check afterwards -- a restored backup or an "
                         "editor writing a new file is the usual way a 644 appears "
                         "where a 640 used to be."),
        "references": [
            {"label": "inode(7) -- permission bits, and the setgid bit Debian ships on /etc/asterisk",
             "url":   "https://manpages.debian.org/trixie/manpages/inode.7.en.html"},
        ],
        "check_fn":  _check_asterisk_perms,
        "detail_fn": _detail_passthrough,
        "sensitive": False,
    },
    {
        "id":       "service_nonroot",
        "layer":    "cross-cutting",
        "label":    "Services run as non-root where possible",
        "severity": "medium",
        "source":   "`systemctl show -p User -p Group` -- one batched call, not one "
                    "per unit -- for every installed unit in the target list: a fixed "
                    "floor (Asterisk, fail2ban, the DVSwitch stack, usrp2m17, the "
                    "dashboard) plus everything pinned in the Services config, so a "
                    "bridge added to this node gets graded without editing the check.",
        "meaning":  ("WARN -- a unit that does not need root is running as root.\n"
                     "PASS -- it drops privileges, or it is one of the documented "
                     "exemptions.\n\n"
                     "Four exemptions pass with a note rather than warning. Asterisk "
                     "needs root on ASL3: app_rpt wants realtime scheduling and direct "
                     "DAHDI/USB access, and that is how upstream ships it. fail2ban "
                     "needs root because its entire job is rewriting firewall rules. "
                     "sshd must be root to authenticate and then setuid to the user "
                     "logging in. Cockpit's privileged side is the point of Cockpit.\n\n"
                     "sysmon, instmon and 44helper are excluded from the check "
                     "altogether -- they are root by design, per the v6.6.0 auth "
                     "migration, and a tool grading itself is noise. Units that are "
                     "not installed are skipped rather than counted, so an ASL-only "
                     "node is not warned about DVSwitch services it does not have.\n\n"
                     "The target list is the fixed floor plus whatever is pinned in "
                     "the Services config: pin a new bridge and it is graded on the "
                     "next run; un-pin one on the floor and it is still graded, "
                     "because hiding a row is a display choice, not a security "
                     "decision.\n\n"
                     "The Overview tab's Owner column carries the same verdict per "
                     "row, computed from the same shared constant, and an amber owner "
                     "there links straight back to this check."),
        "risk":     ("The units this check actually cares about -- Analog_Bridge, "
                     "MMDVM_Bridge, usrp2m17, the reflector bridges -- are C and C++ "
                     "programs whose day job is parsing UDP frames that arrive from "
                     "the network. That is the classic place for a memory-safety "
                     "bug.\n\n"
                     "Whether such a bug is a bad afternoon or a rebuild depends "
                     "entirely on what the process was running as. As a dedicated "
                     "user, it is contained. As root, it is the whole Pi: the "
                     "Asterisk secrets, the SSH keys, persistence. None of these "
                     "bridges need root -- they open high UDP ports and read their "
                     "own config -- so running them as root buys nothing and risks "
                     "everything."),
        "remediation": ("Add User= and Group= to the unit's [Service] section (use "
                         "`systemctl edit <unit>` so the change survives package "
                         "updates), make sure that user can read the config and "
                         "write its logs, then `systemctl daemon-reload` and restart "
                         "it.\n\n"
                         "While you are in there, systemd's sandboxing is nearly free "
                         "on these services: NoNewPrivileges=yes, PrivateTmp=yes, "
                         "ProtectSystem=strict with a narrow ReadWritePaths=, and "
                         "ProtectHome=yes. They limit what a compromised bridge can "
                         "touch even when it is running as the right user."),
        "references": [
            {"label": "AllStarLink manual -- what's new in ASL3 (Asterisk 20+)",
             "url":   "https://allstarlink.github.io/install/whats-new/"},
            {"label": "systemd.exec(5) -- User= and Group=, and what an unset User= means",
             "url":   "https://manpages.debian.org/trixie/systemd/systemd.exec.5.en.html"},
        ],
        "check_fn":  _check_service_nonroot,
        "detail_fn": _detail_passthrough,
        "sensitive": False,
    },
    {
        "id":       "unit_file_perms",
        "layer":    "cross-cutting",
        "label":    "Service unit files and binaries not writable",
        "severity": "high",
        "source":   "stat() on each target unit's FragmentPath, its ExecStart binary, "
                    "and its drop-in directories and *.conf files under "
                    "/etc, /run, /usr/lib and /lib systemd/system. Paths come from one "
                    "batched `systemctl show`; the stats are pure stdlib, no "
                    "subprocess.",
        "meaning":  ("Whether anyone other than root can change what these services "
                     "execute.\n\n"
                     "FAIL -- an artifact is world-writable. Any local account can "
                     "rewrite it and own the next restart.\n"
                     "WARN -- an artifact is group-writable by a non-root group, is "
                     "owned by a non-root user, could not be read, or systemd reported "
                     "no FragmentPath for the unit.\n"
                     "PASS -- everything present is root-owned with no foreign write "
                     "bit.\n\n"
                     "root:root group-writable is deliberately not flagged: it is "
                     "untidy, but nobody who is not already root can write it.\n\n"
                     "Drop-ins are inspected, not just the unit file. `systemctl edit` "
                     "writes <unit>.d/override.conf, and a writable override replaces "
                     "ExecStart exactly as effectively as a writable unit file -- "
                     "checking only FragmentPath would pass a node that is wide open. "
                     "The drop-in directory itself counts too: a writable directory is "
                     "the same finding one step earlier, since nothing stops a local "
                     "user creating a new .conf in it.\n\n"
                     "The Overview tab's Perms column shows the same verdict per row "
                     "and links here."),
        "risk":     ("This is the shortest path to root on the whole tab, and unlike "
                     "most of it, the attacker needs no credentials at all -- only a "
                     "local account, or any process running as a non-root user that "
                     "can be made to write a file.\n\n"
                     "The chain is two steps: edit the unit file, drop-in or binary to "
                     "point at something of your choosing, then wait. You do not even "
                     "need to trigger the restart yourself -- a reboot, a package "
                     "upgrade, a watchdog, or an operator clicking Restart in this very "
                     "interface will do it, and the payload runs as whatever the unit "
                     "runs as, which on most of these is root.\n\n"
                     "It matters specifically on this node because instmon and 44helper "
                     "both WRITE unit files as part of installing the stack. A helper "
                     "that creates a unit with a careless mode leaves a permanent hole "
                     "behind it, and nothing else in the suite would notice."),
        "remediation": ("`chmod 644` and `chown root:root` every unit file, drop-in and "
                         "drop-in directory this check names; `chmod 755 root:root` the "
                         "ExecStart binaries.\n\n"
                         "The usual causes are a unit file copied from a home directory "
                         "with its ownership intact, a `chmod -R` aimed at something "
                         "else, or a build that installed a binary under a non-root "
                         "account. Fix the mode, then check whether whatever produced "
                         "it will do so again on the next run.\n\n"
                         "After changing a unit file or drop-in, `systemctl "
                         "daemon-reload`."),
        "references": [
            {"label": "systemd.unit(5) -- drop-in directories and unit file load path",
             "url":   "https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html"},
            {"label": "Project doc: 44Helper_Root_Auth_Migration.md (this suite writes unit files)",
             "url":   ""},
            {"label": "systemd.unit(5) -- unit file lookup order and drop-in directories",
             "url":   "https://manpages.debian.org/trixie/systemd/systemd.unit.5.en.html"},
            {"label": "systemctl(1) -- `systemctl edit`, which writes the overrides this check stats",
             "url":   "https://manpages.debian.org/trixie/systemd/systemctl.1.en.html"},
        ],
        "check_fn":  _check_unit_file_perms,
        "detail_fn": _detail_passthrough,
        "sensitive": False,
    },
]

_EXPECTED_SECURITY_CHECK_COUNT = 14

def _validate_security_registry(checks: "list[dict]") -> None:
    if len(checks) != _EXPECTED_SECURITY_CHECK_COUNT:
        raise AssertionError(
            f"SECURITY_CHECKS: expected {_EXPECTED_SECURITY_CHECK_COUNT} entries, "
            f"found {len(checks)} -- update _EXPECTED_SECURITY_CHECK_COUNT if this "
            f"is an intentional change")

    poison = "SYSMON_SECURITY_POISON_PROBE_DO_NOT_LEAK"
    poisoned_raw = {k: poison for k in
                    ("secret", "password", "raw_secret", "raw_password", "value")}

    seen_ids = set()
    for entry in checks:
        cid = entry.get("id")
        if not cid or cid in seen_ids:
            raise AssertionError(f"SECURITY_CHECKS: missing or duplicate id {cid!r}")
        seen_ids.add(cid)

        if entry.get("layer") not in _SECURITY_LAYERS:
            raise AssertionError(f"SECURITY_CHECKS[{cid}]: bad layer {entry.get('layer')!r}")
        if entry.get("severity") not in _SECURITY_SEVERITIES:
            raise AssertionError(f"SECURITY_CHECKS[{cid}]: bad severity {entry.get('severity')!r}")
        if not callable(entry.get("check_fn")):
            raise AssertionError(f"SECURITY_CHECKS[{cid}]: check_fn is not callable")

        for field, floor in (("source", 40), ("meaning", 120),
                             ("risk", 120), ("remediation", 60)):
            val = entry.get(field)
            if not isinstance(val, str) or len(val.strip()) < floor:
                raise AssertionError(
                    f"SECURITY_CHECKS[{cid}]: {field} must be a string of at least "
                    f"{floor} characters (got {len(val or '') if isinstance(val, str) else type(val).__name__})")
        refs = entry.get("references")
        if not isinstance(refs, list):
            raise AssertionError(f"SECURITY_CHECKS[{cid}]: references must be a list")
        for ref in refs:
            if not isinstance(ref, dict) or not ref.get("label"):
                raise AssertionError(
                    f"SECURITY_CHECKS[{cid}]: each reference needs a label")
            url = ref.get("url", "")
            if url and not url.startswith("https://"):
                raise AssertionError(
                    f"SECURITY_CHECKS[{cid}]: reference url must be https:// or empty "
                    f"(got {url!r})")

        if entry.get("sensitive"):
            detail_fn = entry.get("detail_fn")
            if not callable(detail_fn):
                raise AssertionError(
                    f"SECURITY_CHECKS[{cid}]: sensitive=True requires a detail_fn "
                    f"(registry redaction contract)")
            redacted = detail_fn(poisoned_raw)
            if poison in json.dumps(redacted, default=str):
                raise AssertionError(
                    f"SECURITY_CHECKS[{cid}]: detail_fn let a raw value through "
                    f"unredacted -- fix before this ships")

_validate_security_registry(SECURITY_CHECKS)


# ==========================================================================
# TAB: Overview
# ==========================================================================

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


# ==========================================================================
# TAB: Services
# ==========================================================================

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


# ==========================================================================
# TAB: Ports
# ==========================================================================

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


# ==========================================================================
# TAB: Journal
# ==========================================================================

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


# ==========================================================================
# TAB: ASL-DVS
# ==========================================================================

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


# ==========================================================================
# TAB: Phone
# ==========================================================================

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
        nets.append({
            "id": name, "name": names.get(name, name),
            "type": "sip" if (out_auth or reg) else "sip_ip",
            "type_label": "SIP with login" if (out_auth or reg) else "SIP by IP address",
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
        dial = _ph_first_dial(routed or entries)
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
        elif nd["context"]:
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
    iax = any(n["type"] == "iax2" for n in nets)
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
            if (pj and not sip) or (name.startswith("chan_iax2") and not iax):
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
        rpt_txt = "\n".join(f"{k} = {v}" for x in ctx["conf"]["rpt.conf"] for k, v, *_ in x["kv"])
        hl = ctx["dash"].get("hoip_link") or {}
        if hl.get("username"):
            user = hl["username"]
            if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_\-]{2,31}$", user):
                C.append(_ph_check("hoiplink", "HOIP AllStar Link", "warn", "username in phone.json looks wrong"))
            else:
                peer = _ph_cli(f"iax2 show peer {user}", 4)
                okp = "Name" in peer and "not found" not in peer.lower()
                C.append(_ph_check("hoiplink", "HOIP AllStar Link account", "ok" if okp else "fail",
                                   f"IAX2 account '{user}' loaded" if okp else f"Asterisk has no IAX2 account '{user}'",
                                   "" if okp else "Save Phone on the dashboard's Edit page, then check iax.conf includes "
                                                  "dvs_phone_iax.conf"))
            okc = "dvs-hoiplink" in ctx["dialplan"]
            C.append(_ph_check("hoiplinkctx", "HOIP AllStar Link answering rules", "ok" if okc else "fail",
                               f"callers join node {hl.get('node') or '?'}" if okc else "[dvs-hoiplink] is missing",
                               "" if okc else "Save Phone on the dashboard's Edit page"))
            fq = hl.get("fqdn", "")
            addr = ""
            if fq:
                try:
                    addr = _socket.gethostbyname(fq)
                except (OSError, UnicodeError):
                    addr = ""
            C.append(_ph_check("hoiplinkdns", "HOIP AllStar Link internet name", "info" if addr else "warn",
                               f"{fq} points at {addr}" if addr else f"{fq or '(none)'} doesn't resolve",
                               f"It should be your home's public address, with UDP {hl.get('port') or '4569'} "
                               f"forwarded to this Pi" if addr else
                               "Check the dynamic DNS name is set up and updating"))
        if "dvs_phone_tonecode" in rpt_txt:
            C.append(_ph_check("radiocodes", "Radio tone codes", "info", "*980-*987 set up",
                               "During a call: *980 sends *, *981 #, *982 *99, *983-*987 the tone buttons 1-5"))
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
    for n in nodes:
        for h in n["hangup"]:
            if h["kind"] != "script":
                continue
            p = Path(h["path"])
            try:
                st = p.stat()
                exe = os.access(p, os.X_OK)
                worldw = bool(st.st_mode & 0o002)
            except OSError:
                C.append(_ph_check("script", "Hang-up script", "fail", f"{h['path']} missing",
                                   "Code *%s can't end incoming calls without it" % h["code"]))
                continue
            problem = "not executable" if not exe else ("world-writable" if worldw else "")
            C.append(_ph_check("script", "Hang-up script", "fail" if problem else "ok",
                               f"{h['path']} {problem}".strip() if problem else "present and runnable"))
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
            fc["note"] = f"Your router also needs UDP {port} and the audio ports forwarded to the Pi"
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
            C.append(_ph_check("nopin", f"Incoming on {i['network']}", "warn", "no PIN",
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
    """How to open a port, for the firewall this Pi runs (v6.11.8; Pi02w: no Firewall tab)."""
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
    C.append(_ph_check("router", "Router", "info", f"forward UDP {sip_port} and UDP {lo}-{hi} to this Pi",
                       "The Pi can't see the router. Turn off SIP ALG there, then prove it with a test call to your HOIP number"))
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
    """modules.conf, line by line: every load/noload line with where it sits."""
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
    """{module: True/False} from 'module show'; None when Asterisk isn't up."""
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
    """The package that owns a file (or should: dpkg keeps the list even when
    the file itself was deleted)."""
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
    if need["sip"]:
        for m in ("chan_pjsip.so", "res_pjsip.so", "res_pjsip_session.so", "res_pjsip_sdp_rtp.so",
                  "res_pjproject.so", "res_rtp_asterisk.so"):
            rows.append((m, B, True, "carries every SIP call"))
    if need["iax"]:
        rows.append(("chan_iax2.so", B, True, "carries IAX2 calls, and node links"))
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
    """(new text or None on refusal, message, warnings)."""
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
    """One STUN Binding request from local_port.  Returns the public (ip, port)."""
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
                           "Have another Hams Over IP member call your extension, then press Check"))
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
                            "Reached the Pi -- so port 5060 gets in" +
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


# ==========================================================================
# TAB: Tune
# ==========================================================================

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


# ==========================================================================
# TAB: Hardware
# ==========================================================================

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

_HARDWARE_ACTIONS = {
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


# ==========================================================================
# TAB: DVSM
# ==========================================================================

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


# ==========================================================================
# TAB: STFU
# ==========================================================================

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


# ==========================================================================
# TAB: M17
# ==========================================================================

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
        f"LocalPort={cfg['m17_local_port'] or '32010'}",
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


# ==========================================================================
# CARD: D-Star -- ircDDBGateway (ASL-DVS tab)
# ==========================================================================
# v6.13.66: read-only checks on /etc/ircddbgateway for the dashboard's
# D-STAR tab (v9.3.71+), which links to gateway callsigns as well as
# reflectors.  Gateway links need ircDDB (callsign lookup) and DExtra; the
# dashboard sends them through ircDDBGateway's remote control when it is
# enabled, and falls back to dvswitch.sh tune when it isn't.  Nothing here
# writes the file -- Edit opens it in the DVSwitch config-file editor.

_IRCDDB_CONF_PATH = Path("/etc/ircddbgateway")
_IRCDDB_SERVICE   = "ircddbgatewayd.service"


def _cmd_or_problem(argv: list, timeout: int = 8) -> "tuple[str, str]":
    """(output, problem).  problem is '' when the command ran."""
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
    """(key -> value, problem).  problem is '' when the file was read."""
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

    irc = kv.get("ircddbEnabled", "0") == "1"
    row(f"ircddbEnabled = {kv.get('ircddbEnabled', '(not set)')}", "ircDDB (gateway callsign lookup)",
        "pass" if irc else "fail",
        None if irc else "Set ircddbEnabled=1 -- gateway callsigns can't be found without it")

    dx = kv.get("dextraEnabled", "0") == "1"
    row(f"dextraEnabled = {kv.get('dextraEnabled', '(not set)')}", "DExtra (gateway links use it)",
        "pass" if dx else "warn", None if dx else "Set dextraEnabled=1 to link to gateways")

    rc_on = kv.get("remoteEnabled", "0") == "1"
    row(f"remoteEnabled = {kv.get('remoteEnabled', '(not set)')}", "Remote control (dashboard gateway links)",
        "pass" if rc_on else "warn",
        None if rc_on else "Optional: set remoteEnabled=1 so gateway links keep their module "
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

    # v6.13.67: gatewayAddress is the Pi's own address ircDDBGateway binds ALL
    # its sockets to (DExtra, D-Plus, DCS, G2 and remote control) -- not the
    # router's.  Blank is normal.  127.0.0.1 cuts off internet linking, and an
    # address this Pi doesn't have (e.g. the router's) stops it binding at all.
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


# ==========================================================================
# TAB: Zello
# ==========================================================================

_ZELLO_SERVICE_NAME  = "asl-zello-bridge"

_ZELLO_OVERRIDE_DIR  = Path("/etc/systemd/system/asl-zello-bridge.service.d")

_ZELLO_OVERRIDE_PATH = _ZELLO_OVERRIDE_DIR / "override.conf"

_ZELLO_EXPECT_USRP_RXPORT = "34012"

_ZELLO_EXPECT_USRP_TXPORT = "32012"

_ZELLO_NODE_ID            = "1918"

_ZELLO_ENV_KEYS = (
    "USRP_BIND", "USRP_HOST", "USRP_RXPORT", "USRP_TXPORT",
    "USRP_GAIN_RX_DB", "USRP_GAIN_TX_DB",
    "ZELLO_USERNAME", "ZELLO_PASSWORD", "ZELLO_CHANNEL",
    "ZELLO_PRIVATE_KEY", "ZELLO_ISSUER", "ZELLO_WS_ENDPOINT",
    "ZELLO_API_ENDPOINT",
    "LOG_LEVEL", "LOG_FORMAT",
)

def _zello_install_check() -> dict:

    venv_ok   = (
        _ZELLO_VENV_BIN.exists()
        and os.access(str(_ZELLO_VENV_BIN), os.X_OK)
    )
    path_bin  = "" if venv_ok else _run(["which", "asl_zello_bridge"]).strip()
    binary_ok = venv_ok or bool(path_bin)
    binary_path = str(_ZELLO_VENV_BIN) if venv_ok else path_bin

    svc_path, svc_installed, svc_active, svc_enabled = _svc_install_state(
        _ZELLO_SERVICE_NAME, _ZELLO_SERVICE_PATHS)

    return {
        "binary_ok":         binary_ok,
        "binary_path":       binary_path,
        "service_installed": svc_installed,
        "service_path":      svc_path,
        "service_active":    svc_active,
        "service_enabled":   svc_enabled,
        "installed":         binary_ok or svc_installed,
    }

def _zello_parse_env_lines(content: str) -> dict:
    env: dict = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if not line.lower().startswith("environment="):
            continue
        rest = line.split("=", 1)[1].strip()
        if not rest or "=" not in rest:
            continue
        key, val = rest.split("=", 1)
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        if key:
            env[key] = val
    return env

def _zello_read_env_override() -> dict:
    env: dict = {}
    source     = ""
    override_ok = _ZELLO_OVERRIDE_PATH.exists()

    if override_ok:
        content, err = read_path_file(_ZELLO_OVERRIDE_PATH)
        if not err:
            env    = _zello_parse_env_lines(content)
            source = "override.conf"

    if not env:
        raw = _run(
            ["systemctl", "show", _ZELLO_SERVICE_NAME, "--property=Environment"],
            timeout=4,
        )
        if raw.startswith("Environment="):
            rest = raw[len("Environment="):]
            for tok in rest.split():
                if "=" in tok:
                    k, v = tok.split("=", 1)
                    env[k] = v
            if env:
                source = "systemctl show (no override.conf yet)"

    return {
        "env":              {k: env.get(k, "") for k in _ZELLO_ENV_KEYS},
        "raw_ok":           bool(env),
        "override_present": override_ok,
        "override_path":    str(_ZELLO_OVERRIDE_PATH),
        "source":           source,
        "mode":             "work" if env.get("ZELLO_API_ENDPOINT") else "free",
    }

def _zello_libopus_present() -> bool:
    try:
        raw = _run(["ldconfig", "-p"], timeout=4)
        return "libopus.so" in raw
    except Exception as e:
        log.debug("_zello_libopus_present: %s", e)
        return False

def _zello_build_fields(cfg: dict) -> list:
    env = cfg["env"]

    return [

        {"group": "Zello Account"},
        {"label": "Username", "value": env["ZELLO_USERNAME"] or None,
         "masked": False, "secret": None,
         "note": None if env["ZELLO_USERNAME"] else "Dedicated bridge account — not your personal login"},
        {"label": "Password", "value": None,
         "masked": True, "secret": env["ZELLO_PASSWORD"],
         "note": None if env["ZELLO_PASSWORD"] else "Not set"},
        {"label": "Channel", "value": env["ZELLO_CHANNEL"] or None,
         "masked": False, "secret": None,
         "note": "Case-sensitive, must match exactly" if env["ZELLO_CHANNEL"] else "Not set"},

        {"group": "Free Auth"},
        {"label": "Private Key Path", "value": env["ZELLO_PRIVATE_KEY"] or None,
         "masked": False, "secret": None,
         "note": ("Issuer/Key from developers.zello.com" if env["ZELLO_PRIVATE_KEY"]
                   else "Not set — required for Zello Free")},
        {"label": "Issuer", "value": env["ZELLO_ISSUER"] or None,
         "masked": False, "secret": None,
         "note": None if env["ZELLO_ISSUER"] else "Not set"},
        {"label": "WS Endpoint", "value": env["ZELLO_WS_ENDPOINT"] or "wss://zello.io/ws",
         "masked": False, "secret": None, "note": None},

        {"group": "USRP Bridge Ports"},
        {"label": "Bind", "value": env["USRP_BIND"] or "127.0.0.1",
         "masked": False, "secret": None, "note": "Where this bridge listens for ASL"},
        {"label": "Host", "value": env["USRP_HOST"] or "127.0.0.1",
         "masked": False, "secret": None, "note": "Where this bridge sends audio back to ASL"},
        {"label": "RX Port", "value": env["USRP_RXPORT"] or None,
         "masked": False, "secret": None,
         "note": f"ASL sends here — expected {_ZELLO_EXPECT_USRP_RXPORT}"},
        {"label": "TX Port", "value": env["USRP_TXPORT"] or None,
         "masked": False, "secret": None,
         "note": f"ASL listens here — expected {_ZELLO_EXPECT_USRP_TXPORT}"},
        {"label": "RX Gain (dB)", "value": env["USRP_GAIN_RX_DB"] or "0",
         "masked": False, "secret": None, "note": None},
        {"label": "TX Gain (dB)", "value": env["USRP_GAIN_TX_DB"] or "0",
         "masked": False, "secret": None, "note": None},

        {"group": "Logging"},
        {"label": "Log Level", "value": env["LOG_LEVEL"] or "INFO",
         "masked": False, "secret": None, "note": None},
    ]

def _zello_build_compat(cfg: dict, inst: dict) -> list:
    env = cfg["env"]

    creds_ok  = bool(env["ZELLO_USERNAME"]) and bool(env["ZELLO_PASSWORD"])
    chan_ok   = bool(env["ZELLO_CHANNEL"])

    key_path  = env["ZELLO_PRIVATE_KEY"]
    key_ok    = False
    key_val   = "not set"
    if key_path:
        try:
            p = Path(key_path)
            key_ok  = p.exists() and os.access(str(p), os.R_OK)
            key_val = key_path if key_ok else f"{key_path} (unreadable)"
        except Exception as e:
            log.debug("_zello_build_compat key check: %s", e)
            key_val = f"{key_path} (error checking)"
    issuer_ok = bool(env["ZELLO_ISSUER"])

    ports_ok  = (env["USRP_RXPORT"] == _ZELLO_EXPECT_USRP_RXPORT and
                 env["USRP_TXPORT"] == _ZELLO_EXPECT_USRP_TXPORT)

    opus_ok   = _zello_libopus_present()

    compat = [
        {"key": "Zello credentials set",
         "enables": "Username + password present",
         "status": "pass" if creds_ok else "fail",
         "value":  "set" if creds_ok else "not set",
         "fix":    "Set ZELLO_USERNAME and ZELLO_PASSWORD in the systemd override" if not creds_ok else None},
        {"key": "Channel configured",
         "enables": "ZELLO_CHANNEL present",
         "status": "pass" if chan_ok else "fail",
         "value":  env["ZELLO_CHANNEL"] or "not set",
         "fix":    "Set ZELLO_CHANNEL (must match the Zello channel name exactly)" if not chan_ok else None},
        {"key": "Private key readable",
         "enables": "Zello Free token signing",
         "status": "pass" if key_ok else "fail",
         "value":  key_val,
         "fix":    ("Point ZELLO_PRIVATE_KEY at the .key file saved from developers.zello.com"
                    if not key_ok else None)},
        {"key": "Issuer set",
         "enables": "Zello Free token signing",
         "status": "pass" if issuer_ok else "fail",
         "value":  env["ZELLO_ISSUER"] or "not set",
         "fix":    "Set ZELLO_ISSUER from developers.zello.com → Keys" if not issuer_ok else None},
        {"key": "USRP ports match scheme",
         "enables": f"RXPORT={_ZELLO_EXPECT_USRP_RXPORT} / TXPORT={_ZELLO_EXPECT_USRP_TXPORT}",
         "status": "pass" if ports_ok else "fail",
         "value":  f"RX={env['USRP_RXPORT'] or '—'} TX={env['USRP_TXPORT'] or '—'}",
         "fix":    (f"Set USRP_RXPORT={_ZELLO_EXPECT_USRP_RXPORT} and "
                    f"USRP_TXPORT={_ZELLO_EXPECT_USRP_TXPORT} — must match rpt.conf "
                    f"[{_ZELLO_NODE_ID}]'s rxchannel") if not ports_ok else None},
        {"key": "libopus present",
         "enables": "Opus encode/decode for Zello audio",
         "status": "pass" if opus_ok else "fail",
         "value":  "found" if opus_ok else "not found",
         "fix":    "apt-get install libopus0 libopus-dev" if not opus_ok else None},
        {"key": "Service running",
         "enables": "asl-zello-bridge active",
         "status": ("pass" if inst["service_active"] else
                    "warn" if inst["service_installed"] else "fail"),
         "value":  ("active"    if inst["service_active"]    else
                    "installed" if inst["service_installed"] else "not installed"),
         "fix":    ("systemctl start asl-zello-bridge" if inst["service_installed"] and not inst["service_active"]
                    else "Install asl-zello-bridge.service — see README" if not inst["service_installed"]
                    else None)},
    ]

    rpt  = _dvsm_read_rpt_conf()
    node = _m17_find_rpt_node(rpt, _ZELLO_NODE_ID) if rpt.get("raw_ok") else None
    if not rpt.get("raw_ok"):
        compat.append({
            "key": f"rpt.conf [{_ZELLO_NODE_ID}] node stanza",
            "enables": "ASL <-> Zello USRP channel wiring",
            "status": "warn",
            "value":  "rpt.conf unreadable",
            "fix":    rpt.get("error") or "Check /etc/asterisk/rpt.conf permissions",
        })
    elif node is None:
        compat.append({
            "key": f"rpt.conf [{_ZELLO_NODE_ID}] node stanza",
            "enables": "ASL <-> Zello USRP channel wiring",
            "status": "warn",
            "value":  "not found",
            "fix":    (f"Add a [{_ZELLO_NODE_ID}] node stanza with "
                       f"rxchannel = USRP/127.0.0.1:{_ZELLO_EXPECT_USRP_RXPORT}:{_ZELLO_EXPECT_USRP_TXPORT}"),
        })
    else:
        rxch = node.get("rxchannel") or ""
        node_ports_match = (
            f":{_ZELLO_EXPECT_USRP_RXPORT}:{_ZELLO_EXPECT_USRP_TXPORT}" in rxch
        )
        compat.append({
            "key": f"rpt.conf [{_ZELLO_NODE_ID}] node stanza",
            "enables": "ASL <-> Zello USRP channel wiring",
            "status": "pass" if node_ports_match else "fail",
            "value":  rxch or "present, rxchannel unparsed",
            "fix":    (None if node_ports_match else
                       f"rxchannel ports don't match — expect "
                       f"USRP/127.0.0.1:{_ZELLO_EXPECT_USRP_RXPORT}:{_ZELLO_EXPECT_USRP_TXPORT}"),
        })

    return compat

def _zello_sample_override(cfg: dict) -> str:

    env = cfg["env"]
    lines = [
        "[Service]",
        f"Environment=USRP_BIND={env['USRP_BIND'] or '127.0.0.1'}",
        f"Environment=USRP_HOST={env['USRP_HOST'] or '127.0.0.1'}",
        f"Environment=USRP_RXPORT={env['USRP_RXPORT'] or _ZELLO_EXPECT_USRP_RXPORT}",
        f"Environment=USRP_TXPORT={env['USRP_TXPORT'] or _ZELLO_EXPECT_USRP_TXPORT}",
        "",
        f"Environment=ZELLO_USERNAME={_placeholder(env['ZELLO_USERNAME'], 'bridge account username')}",
        f"Environment=ZELLO_PASSWORD={_placeholder(env['ZELLO_PASSWORD'], 'bridge account password')}",
        f'Environment=ZELLO_CHANNEL="{env["ZELLO_CHANNEL"] or "<channel name>"}"',
        "",
        f"Environment=ZELLO_PRIVATE_KEY={_placeholder(env['ZELLO_PRIVATE_KEY'], '/opt/asl-zello-bridge/zello.key')}",
        f"Environment=ZELLO_ISSUER={_placeholder(env['ZELLO_ISSUER'], 'issuer-id from developers.zello.com')}",
        f"Environment=ZELLO_WS_ENDPOINT={env['ZELLO_WS_ENDPOINT'] or 'wss://zello.io/ws'}",
        "",
        f"Environment=USRP_GAIN_RX_DB={env['USRP_GAIN_RX_DB'] or '0'}",
        f"Environment=USRP_GAIN_TX_DB={env['USRP_GAIN_TX_DB'] or '0'}",
        f"Environment=LOG_LEVEL={env['LOG_LEVEL'] or 'INFO'}",
    ]
    return "\n".join(lines)

_ZELLO_RE_UNKEYED = re.compile(r"UnKeyed:(\S+?)(?:\s*\(([\d.]+)s\))?\s*$")

_ZELLO_RE_KEYED    = re.compile(r"(?<!Un)Keyed:(\S+)\s*$")

_ZELLO_JOURNAL_TS  = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")

def _zello_relative_time(iso_ts: str) -> str:
    try:
        dt   = datetime.strptime(iso_ts, "%Y-%m-%dT%H:%M:%S")
        secs = (datetime.now() - dt).total_seconds()
    except Exception as e:
        log.debug("_zello_relative_time: %s", e)
        return ""
    if secs < 0:
        return "just now"
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"

def _zello_status_from_journal(lines_n: int = 200) -> dict:
    raw = _run(
        ["journalctl", "-u", _ZELLO_SERVICE_NAME, f"-n{lines_n}",
         "--no-pager", "-o", "short-iso"],
        timeout=8,
    )

    state = {
        "authenticated":   False,
        "channel_ready":   False,
        "currently_keyed": False,
        "keyed_by":        None,
        "last_activity":   None,
        "last_activity_at": "",
        "last_warn":       None,
        "last_error":      None,
        "journal_ok":      bool(raw),
    }

    if not raw:
        return state

    for line in raw.splitlines():
        m_ts = _ZELLO_JOURNAL_TS.match(line)
        ts   = m_ts.group(1) if m_ts else ""

        if "Logged in!" in line:
            state["authenticated"] = True
            state["last_error"] = None
        elif "Channel is ready" in line:
            state["channel_ready"] = True
        elif "Websocket closed" in line:
            state["authenticated"] = False
            state["channel_ready"] = False
            state["currently_keyed"] = False
            state["last_warn"] = "Websocket closed"
        elif "Kicked from channel" in line:
            state["authenticated"] = False
            state["channel_ready"] = False
            state["currently_keyed"] = False
            state["last_error"] = "Kicked from channel"
        elif "Woodpecker protection triggered" in line:
            state["last_warn"] = "Woodpecker protection (rate-limited by Zello)"
        elif "Channel not ready" in line:
            state["channel_ready"] = False
            state["last_warn"] = "Channel not ready"
            continue

        m_unkeyed = _ZELLO_RE_UNKEYED.search(line)
        m_keyed   = _ZELLO_RE_KEYED.search(line)
        if m_unkeyed:
            user = m_unkeyed.group(1)
            dur  = m_unkeyed.group(2)
            state["currently_keyed"] = False
            state["keyed_by"] = None
            state["last_activity"] = (
                f"UnKeyed: {user} ({dur}s)" if dur else f"UnKeyed: {user}"
            )
            state["last_activity_at"] = _zello_relative_time(ts) if ts else ""
        elif m_keyed:
            user = m_keyed.group(1)
            state["currently_keyed"] = True
            state["keyed_by"] = user
            state["last_activity"] = f"Keyed: {user}"
            state["last_activity_at"] = _zello_relative_time(ts) if ts else ""

    return state

def _zello_serialize_env(env: dict) -> str:

    def _fmt(key: str, val: str) -> str:
        if any(c in val for c in (" ", "\t")):
            escaped = val.replace('"', '\\"')
            return f'Environment={key}="{escaped}"'
        return f"Environment={key}={val}"

    groups = [
        ("USRP", ("USRP_BIND", "USRP_HOST", "USRP_RXPORT", "USRP_TXPORT",
                  "USRP_GAIN_RX_DB", "USRP_GAIN_TX_DB")),
        ("Zello", ("ZELLO_USERNAME", "ZELLO_PASSWORD", "ZELLO_CHANNEL")),
        ("Zello Free auth", ("ZELLO_PRIVATE_KEY", "ZELLO_ISSUER", "ZELLO_WS_ENDPOINT")),
        ("Zello Work (unused in Free mode)", ("ZELLO_API_ENDPOINT",)),
        ("Logging", ("LOG_LEVEL", "LOG_FORMAT")),
    ]

    lines = ["[Service]", ""]
    for label, keys in groups:
        block = [_fmt(k, env[k]) for k in keys if env.get(k)]
        if not block:
            continue
        lines.append(f"# {label}")
        lines.extend(block)
        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines) + "\n"

def _zello_validate_env_payload(payload: dict) -> "tuple[dict, str]":
    clean: dict = {}
    for key, val in (payload or {}).items():
        if key not in _ZELLO_ENV_KEYS:
            return {}, f"Unknown config key: {key!r}"
        if not isinstance(val, str):
            return {}, f"Value for {key} must be a string"
        if "\n" in val or "\r" in val:
            return {}, f"Value for {key} cannot contain newlines"
        clean[key] = val.strip()
    return clean, ""

def _build_zello_payload() -> dict:
    inst = _zello_install_check()
    cfg  = _zello_read_env_override()
    env  = cfg["env"]

    fields = _zello_build_fields(cfg)
    compat = _zello_build_compat(cfg, inst)
    status = _zello_status_from_journal() if inst["service_installed"] else {
        "authenticated": False, "channel_ready": False, "currently_keyed": False,
        "keyed_by": None, "last_activity": None, "last_activity_at": "",
        "last_warn": None, "last_error": None, "journal_ok": False,
    }

    creds_ok = bool(env["ZELLO_USERNAME"]) and bool(env["ZELLO_PASSWORD"])
    chan_ok  = bool(env["ZELLO_CHANNEL"])
    key_ok   = bool(env["ZELLO_PRIVATE_KEY"]) and bool(env["ZELLO_ISSUER"])
    config_status = ("pass" if (creds_ok and chan_ok and key_ok) else
                      "warn" if (creds_ok or chan_ok or key_ok) else "fail")

    if cfg["override_present"]:
        raw_content, raw_err = read_path_file(_ZELLO_OVERRIDE_PATH)
        editable_content = raw_content if not raw_err else _zello_serialize_env(env)
    else:
        editable_content = _zello_serialize_env(env)

    return {
        "ok":            True,
        "install":       inst,
        "config":        {
            "raw_ok":           cfg["raw_ok"],
            "override_present": cfg["override_present"],
            "override_path":    cfg["override_path"],
            "mode":             cfg["mode"],
            "status":           config_status,
            "fields":           fields,
        },
        "compat":            compat,
        "status":            status,
        "sample_override":   _zello_sample_override(cfg),
        "editable_content":  editable_content,
        "override_path":     cfg["override_path"],
        "node_id":           _ZELLO_NODE_ID,
    }

def _route_zello_get(h: Handler) -> None:
    h.send_json(_build_zello_payload())

def _route_zello_post(h: Handler, data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "root required"}); return

    action = str(data.get("action", "")).strip().lower()

    if action in ("restart", "start", "stop"):
        try:
            _run(["systemctl", action, _ZELLO_SERVICE_NAME], timeout=10)
            h.send_json({"ok": True, "message": f"{_ZELLO_SERVICE_NAME} {action}ed"})
        except Exception as exc:
            h.send_json({"ok": False, "message": str(exc)})
        return

    if action == "save_override_raw":
        content = data.get("content", "")
        if not isinstance(content, str) or not content.strip():
            h.send_json({"ok": False, "message": "Content must not be empty"}, 400)
            return

        parsed = _zello_parse_env_lines(content)
        clean, err = _zello_validate_env_payload(parsed)
        if err:
            h.send_json({"ok": False, "message": err}, 400)
            return

        out_content = _zello_serialize_env(clean)
        ok, msg = write_path_file(_ZELLO_OVERRIDE_PATH, out_content)
        if not ok:
            h.send_json({"ok": False, "message": msg})
            return

        try:
            _run(["systemctl", "daemon-reload"], timeout=8)
        except Exception as e:
            log.debug("_route_zello_post daemon-reload: %s", e)

        h.send_json({
            "ok":      True,
            "message": "Saved — restart asl-zello-bridge to apply",
        })
        return

    if action == "save_override":
        submitted, err = _zello_validate_env_payload(data.get("env", {}))
        if err:
            h.send_json({"ok": False, "message": err}, 400)
            return

        current = _zello_read_env_override()["env"]
        merged  = {**current, **submitted}

        content = _zello_serialize_env(merged)
        ok, msg = write_path_file(_ZELLO_OVERRIDE_PATH, content)
        if not ok:
            h.send_json({"ok": False, "message": msg})
            return

        try:
            _run(["systemctl", "daemon-reload"], timeout=8)
        except Exception as e:
            log.debug("_route_zello_post daemon-reload: %s", e)

        h.send_json({
            "ok":      True,
            "message": "Saved — restart asl-zello-bridge to apply",
        })
        return

    h.send_json({"ok": False, "message": f"unknown action '{action}'"}, 400)


# ==========================================================================
# TAB: SD Card
# ==========================================================================

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


# ==========================================================================
# TAB: Security
# ==========================================================================

_SECURITY_LAYER_ORDER  = ["dvswitch", "asl", "usrp2m17", "cross-cutting"]

_SECURITY_LAYER_LABELS = {
    "dvswitch":      "DVSwitch",
    "asl":           "AllStarLink",
    "usrp2m17":      "usrp2m17",
    "cross-cutting": "Cross-cutting",
}

_SECURITY_CACHE_TTL_SEC = 60

_SECURITY_RUN_BUDGET_SEC = 12

_SECURITY_LOCK   = threading.Lock()

_SECURITY_CACHE: dict  = {"payload": None, "ts": 0.0}

def _run_security_check(entry: dict) -> dict:
    cid = entry["id"]
    try:
        result = entry["check_fn"]()
        status = result.get("status", CHK_ERROR)
        raw    = result.get("raw", {})
    except Exception as exc:
        log.warning("security check %s: check_fn failed: %s", cid, exc)
        status, raw = CHK_ERROR, {"error": str(exc)[:200]}

    try:
        detail_fn = entry.get("detail_fn") or _detail_passthrough
        detail = detail_fn(raw)
    except Exception as exc:
        log.warning("security check %s: detail_fn failed: %s", cid, exc)
        detail = {}

    return {
        "id":          cid,
        "layer":       entry["layer"],
        "label":       entry["label"],
        "severity":    entry["severity"],
        "status":      status,
        "sensitive":   entry["sensitive"],
        "detail":      detail,
        "source":      entry["source"],
        "meaning":     entry["meaning"],
        "risk":        entry.get("risk", ""),
        "remediation": entry["remediation"],
        "references":  entry.get("references", []),
    }

def _security_summary(checks: "list[dict]") -> dict:
    counts = {CHK_PASS: 0, CHK_WARN: 0, CHK_FAIL: 0}
    other  = 0
    for c in checks:
        if c["status"] in counts:
            counts[c["status"]] += 1
        else:
            other += 1
    return {
        "pass":  counts[CHK_PASS],
        "warn":  counts[CHK_WARN],
        "fail":  counts[CHK_FAIL],
        "other": other,
        "total": len(checks),
        "worst": _sec_worst([c["status"] for c in checks]),
    }

def _security_layer_summary(checks: "list[dict]") -> list:
    out = []
    for layer in _SECURITY_LAYER_ORDER:
        rows = [c for c in checks if c["layer"] == layer]
        if not rows:
            continue
        out.append({
            "id":     layer,
            "label":  _SECURITY_LAYER_LABELS.get(layer, layer),
            "status": _sec_worst([r["status"] for r in rows]),
            "counts": _security_summary(rows),
        })
    return out

def _security_build_payload() -> dict:
    _SECURITY_RUNCTX.clear()
    _SECURITY_RUNCTX["_deadline"] = time.monotonic() + _SECURITY_RUN_BUDGET_SEC
    try:
        checks = [_run_security_check(entry) for entry in SECURITY_CHECKS]
    finally:
        _SECURITY_RUNCTX.clear()
    return {
        "ok":                 True,
        "summary":            _security_summary(checks),
        "layers":             _security_layer_summary(checks),
        "last_run_timestamp": time.time(),
        "checks":             checks,
        "cached":             False,
        "cache_ttl_sec":      _SECURITY_CACHE_TTL_SEC,
    }

def _route_security_checks(h: Handler) -> None:
    qs      = parse_qs(urlparse(h.path).query)
    refresh = qs.get("refresh", ["0"])[0].strip().lower() in ("1", "true", "yes")

    with _SECURITY_LOCK:
        now    = time.time()
        cached = _SECURITY_CACHE.get("payload")
        age    = now - float(_SECURITY_CACHE.get("ts") or 0)

        if cached and not refresh and age < _SECURITY_CACHE_TTL_SEC:
            payload = dict(cached)
            payload["cached"]        = True
            payload["cache_age_sec"] = int(age)
            h.send_json(payload)
            return

        payload = _security_build_payload()
        _SECURITY_CACHE["payload"] = payload
        _SECURITY_CACHE["ts"]      = now

    out = dict(payload)
    out["cache_age_sec"] = 0
    h.send_json(out)


# ==========================================================================
# TAB: Edit
# ==========================================================================

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
             "asldvs", "phone", "tune", "hardware", "dvsm", "stfu", "m17", "zello", "sdcard",
             "security", "edit")

_LOCKED_TABS = ("overview", "edit")

def _sanitize_enabled_tabs(raw) -> list:
    if isinstance(raw, str):
        items = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        items = raw
    else:
        items = []
    wanted = {str(t).strip().lower() for t in items}
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


# ==========================================================================
# SHARED: ASL-DVS + Edit
# ==========================================================================

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


# ==========================================================================
# TAB: Phone -- background job runner (/api/net/job)
# ==========================================================================

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


# ==========================================================================
# TAB: Phone -- helpers
# ==========================================================================

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


# ==========================================================================
# TAB: STFU -- helpers
# ==========================================================================

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


# ==========================================================================
# SHARED: Overview + Services + Journal
# ==========================================================================

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


# ==========================================================================
# SHARED: Phone + Tune
# ==========================================================================

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
    info = {"phone_node": "", "names": {}, "active": "", "asl_node": "", "tone_path": "", "hoip_link": {},
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
            hl = doc.get("hoip_link")
            if isinstance(hl, dict) and hl.get("enabled"):
                info["hoip_link"] = {k: str(hl.get(k, ""))[:120] for k in ("username", "fqdn", "port", "node")}
            for n in doc.get("networks", []):
                if isinstance(n, dict) and n.get("id"):
                    info["names"][str(n["id"])] = str(n.get("name", ""))[:40]
                    info["networks"].append({"id": str(n["id"])[:40], "name": str(n.get("name", ""))[:40],
                                             "node": str(n.get("node", "") or "")[:7]})
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


# ==========================================================================
# TAB: Phone -- firewall readers (read-only)
# ==========================================================================

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


# ==========================================================================
# SHARED: small helpers used by two or more tabs
# ==========================================================================

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


# ==========================================================================
# Routes and server start
# ==========================================================================


_GET_ROUTES = {
    "/":                       _route_html,
    "/api/ping":               lambda h: h.send_ping(),
    "/api/whoami":             lambda h: h.send_json({"ok": True}),
    "/api/dashboard-status":   lambda h: h.send_json(action_dashboard_status()),
    "/api/status":             _route_status,
    "/api/config":             _route_config_get,
    "/api/log":                _route_log,
    "/api/overview":           _route_overview,
    "/api/services":           _route_services,
    "/api/services/detail":    _route_service_detail,
    "/api/ports":              _route_ports,
    "/api/ports/probe":        _route_ports_probe,
    "/api/journal/list":       _route_journal_list,
    "/api/journal/fetch":      _route_journal_fetch,
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
    "/api/phone":              _route_phone_get,
    "/api/dvsm":               _route_dvsm,
    "/api/stfu":               _route_stfu_get,
    "/api/m17":                _route_m17_get,
    "/api/dstar-gw":           _route_dstar_gw_get,
    "/api/zello":              _route_zello_get,
    "/api/sdcard":             _route_sdcard_get,
    "/api/sdcard/test":        _route_sdcard_test_get,
    "/api/security/checks":    _route_security_checks,
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
    "/api/zello":           _route_zello_post,
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

_INSTALL_DIR   = "/usr/local/lib/asl_dvs_sysmon"
_INSTALL_LINK  = "/usr/local/bin/sysmon.py"
_SERVICE_PATH  = "/etc/systemd/system/sysmon.service"
_SERVICE_CONTENT = f"""[Unit]
Description=ASL-DVS SYSMON
After=network.target

[Service]
Type=notify
NotifyAccess=main
ExecStart=/usr/bin/python3 {_INSTALL_LINK}
Restart=always
RestartSec=3s
WatchdogSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""

def install_service() -> None:
    if os.geteuid() != 0:
        print("ERROR: install requires root  →  sudo python3 sysmon.py --install",
              file=sys.stderr)
        sys.exit(1)

    current_script = os.path.abspath(__file__)
    print("Installing sysmon...")

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
            target = os.readlink(_INSTALL_LINK)
        os.remove(_INSTALL_LINK)
        print(f"  [-] Removed {_INSTALL_LINK}")
        if target and os.path.basename(target).startswith("sysmon_") and os.path.isfile(target):
            os.remove(target)
            print(f"  [-] Removed {target}")

    print(f"\nUninstall complete. {CONFIG_FILE} was not touched.")

def run_selftest() -> int:
    print(f"sysmon --selftest  (v{VERSION})")
    print(f"registry: {len(SECURITY_CHECKS)} checks, import-time validation passed\n")

    counts = {CHK_PASS: 0, CHK_WARN: 0, CHK_FAIL: 0, CHK_NOT_IMPLEMENTED: 0, CHK_ERROR: 0}
    crashed = []
    for chk in SECURITY_CHECKS:
        cid = chk["id"]
        try:
            result = chk["check_fn"]()
            status = result.get("status", CHK_ERROR)
        except Exception as exc:
            status = CHK_ERROR
            crashed.append((cid, exc))
        counts[status] = counts.get(status, 0) + 1
        print(f"  [{status.upper():^15}] {cid}")

    print(f"\n{sum(counts.values())} checks run: "
          + ", ".join(f"{v} {k}" for k, v in counts.items() if v))

    if crashed:
        print(f"\n{len(crashed)} check(s) RAISED rather than returning a result "
              f"-- this is a selftest failure, not a security finding:")
        for cid, exc in crashed:
            print(f"  {cid}: {type(exc).__name__}: {exc}")
        return 1

    print("\nAll checks executed without raising. (WARN/FAIL above are "
          "findings, not selftest failures.)")
    return 0

def main() -> None:
    parser = argparse.ArgumentParser(description="ASL-DVS SYSMON")
    parser.add_argument("--install", action="store_true", help="Install sysmon as a systemd service")
    parser.add_argument("--uninstall", action="store_true", help="Remove sysmon systemd service")
    parser.add_argument("--selftest", action="store_true",
                         help="Run registry validation + all security checks against this box, "
                              "then exit (no HTTP server started)")
    args = parser.parse_args()

    if args.install:
        install_service()
        return
    if args.uninstall:
        uninstall_service()
        return
    if args.selftest:
        sys.exit(run_selftest())

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

    ip = _lan_ip()
    cs = _cfg.get("identity", "callsign", fallback="")
    nd = _cfg.get("identity", "node",     fallback="")

    print(f"""
╔══════════════════════════════════════════════╗
║           ASL-DVS SYSMON  v{VERSION:<17}║
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