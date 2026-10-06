#!/usr/bin/env python3

import argparse
import configparser
import gzip
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

VERSION      = "6.5.18"
BUILD_DATE   = "20260823"

CONFIG_FILE  = Path("/etc/sysmon/sysmon.conf")
DEFAULT_PORT    = 9999
DASHBOARD_PORT  = 8989
LOG_MAXLEN   = 500

AMBE_DEVICES: "dict[tuple, str]" = {
    ("0403", "6015"): "ThumbDV",
}

AMBE_FTDI_VIDS: "dict[str, str]" = {
    "0403": "Serial adapter (FTDI) — possible AMBE",
}

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
            "__GROUP__:AllStarLink Core\n"
            "asterisk.service | ASL3 Asterisk/app_rpt | /etc/asterisk/rpt.conf | 4569 | udp\n"
            "allmon3.service | Allmon3 web monitor | - | 8080 | tcp\n"
            "cockpit.service | ASL3 Cockpit admin UI | - | 9090 | tcp\n"
            "asl-dvs-dashboard.service | ASL+DVSwitch Dashboard | - | 8989 | tcp\n"
            "usrp2m17.service | USRP2M17 (M17 bridge) | /opt/USRP2M17/USRP2M17.ini | 34008 | udp\n"
            "__GROUP__:System\n"
            "ssh.service | SSH Access | - | 22 | tcp\n"
            "sysmon.service | Sysmon Monitor | - | 9999 | tcp\n"
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
        "usbradio_values":  "",
    },
    "ui": {

        "enabled_tabs": "overview,services,ports,firewall,journal,asldvs,reg,tune,hardware,dvsm,stfu,m17,zello,sdcard,edit",
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

def _get_hidden_files() -> set:
    raw = _cfg.get("asldvs", "hidden_files", fallback="")
    return {f.strip() for f in raw.split(",") if f.strip()}

_RADIO_PRESET_FIELDS = {
    "rxmixerset":   (int,   0,    1000),
    "txmixaset":    (int,   0,    1000),
    "txmixbset":    (int,   0,    1000),
    "txctcssadj":   (int,   0,    1000),
    "rxsquelchadj": (int,   0,    1000),
    "rxvoiceadj":   (float, 0.0,  1.0),
    "rxctcssadj":   (float, 0.0,  1.0),
    "txslimsp":     (int,   1000, 100000),
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

_RADIO_TUNE_DRIVERS = ("simpleusb", "usbradio")

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

def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)

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
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            _cfg.write(fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        _log(f"Config saved to {path}")
        return True
    except Exception as exc:
        _log(f"WARN — config save error: {exc}")
        return False

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

_ALL_TABS = ("overview", "services", "ports", "firewall", "journal",
             "asldvs", "reg", "tune", "hardware", "dvsm", "stfu", "m17", "zello", "sdcard", "edit")

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

def _get_pinned_raw() -> str:
    if CONFIG_FILE.exists():
        return _cfg.get("services", "pinned", fallback="")
    return _DEFAULT_CONFIG["services"]["pinned"]

_cfg  = load_config()
_pinned: list = parse_pinned_services(_get_pinned_raw())

def reload_config() -> None:
    global _cfg, _pinned
    _cfg    = load_config()
    _pinned = parse_pinned_services(_get_pinned_raw())

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

_BAUD_TO_TERMIOS: "dict[int, int]" = {}
try:
    import termios as _termios
    _BAUD_TO_TERMIOS = {
        230400: _termios.B230400,
        460800: _termios.B460800,
    }
except ImportError:
    pass

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

    seg = bytearray()
    try:
        while True:
            b = proc.stdout.read(1)
            if not b:
                break
            if b in (b"\n", b"\r"):
                _sd_test_record(seg.decode("utf-8", "replace").rstrip())
                seg = bytearray()
            else:
                seg += b
        if seg:
            _sd_test_record(seg.decode("utf-8", "replace").rstrip())
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

_DETAIL_PROPS = [
    "Description", "ActiveState", "UnitFileState",
    "MainPID", "NRestarts", "ExecMainStatus", "CanReload",
]

def _invalid_unit_detail(unit: str) -> dict:
    return {
        "unit": unit, "desc": "", "state": "unknown",
        "enabled": "unknown", "pid": 0, "nrestarts": 0,
        "exit_status": 0, "cpu_pct": None, "rss_mb": None,
        "can_reload": False, "installed": False,
        "error": "invalid unit name",
    }

def _not_installed_detail(unit: str) -> dict:
    return {
        "unit": unit, "desc": "", "state": "not-inst",
        "enabled": "unknown", "pid": 0, "nrestarts": 0,
        "exit_status": 0, "cpu_pct": None, "rss_mb": None,
        "can_reload": False, "installed": False,
    }

def _parse_show_block(unit: str, block: str) -> dict:
    values = {}
    for line in block.splitlines():
        if "=" in line:
            key, _, val = line.partition("=")
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
        ps_raw = _run(["ps", "-o", "pid=,%cpu=,rss=", "-p", pid_list], timeout=5)
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

    return result

def get_service_detail(unit: str) -> dict:
    return get_services_details([unit]).get(unit) or _invalid_unit_detail(unit)

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

_AST_DIR = Path("/etc/asterisk")
_AST_FILE_RE = re.compile(r'^[\w\-]+\.conf$')

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

def parse_rpt_conf(content: str) -> list:

    sections: "dict[str, dict]" = {}
    section      = ""
    current_kv: "dict[str, str]" = {}
    skip_section = False

    for line in content.splitlines():
        if _RPT_COMMENT_RE.match(line):
            continue
        if _TEMPLATE_SECTION_RE.match(line):
            if section and not skip_section:
                sections[section] = current_kv
            section, current_kv, skip_section = "_TPL_", {}, True
            continue
        sm = _RPT_SECTION_RE.match(line)
        if sm:
            if section and not skip_section:
                sections[section] = current_kv
            section      = sm.group(1).strip()
            current_kv   = {}
            skip_section = False
            continue
        if not skip_section:
            m = _RPT_KV_RE.match(line)
            if m:
                current_kv[m.group(1).lower()] = m.group(2).strip()
    if section and not skip_section:
        sections[section] = current_kv

    node_sects = {s: kv for s, kv in sections.items()
                  if s.isdigit() and not _RPT_NON_NODE_RE.match(s)}

    callsign = ""
    for s in sorted(node_sects.keys(), key=int):
        cs = _rpt_callsign(node_sects[s])
        if cs:
            callsign = cs
            break

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

def _parse_sections(content: str) -> "dict[str, dict]":
    sections: "dict[str, dict]" = {}
    section   = ""
    current_kv: "dict[str, str]" = {}
    for line in content.splitlines():
        sm = _RPT_SECTION_RE.match(line)
        if sm:
            if section:
                sections[section] = current_kv
            section    = sm.group(1).strip()
            current_kv = {}
            continue
        m = _RPT_KV_RE.match(line)
        if m:
            current_kv[m.group(1).lower()] = m.group(2).strip()
    if section:
        sections[section] = current_kv
    return sections

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

_REGISTER_RE = re.compile(
    r'^\s*register\s*=>\s*(\d+):([^@\s]+)@([\w.\-]+)(?::\d+)?(?:/\S*)?\s*(?:;.*)?$',
    re.IGNORECASE,
)

_ASL_URL  = "https://allstarlink.org"
_ASL_NOTE = "AllStarLink Node Password"

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

_REGISTER_LOOSE_RE = re.compile(r'^\s*register\s*[=:]', re.IGNORECASE)
_PLACEHOLDER_NODES = frozenset({"1999", "1998"})
_STATPOST_URL_RE   = re.compile(
    r'^https?://stats\.allstarlink\.org/uhandler\b', re.IGNORECASE
)
_NODE_LOOKUP_VALUES = frozenset({"dns", "file", "both"})
_DEFAULT_DNS_DOMAIN = "nodes.allstarlink.org"
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

    sections: "dict[str, dict]" = {}
    section      = ""
    current_kv: "dict[str, str]" = {}
    skip_section = False

    for line in content.splitlines():
        if _RPT_COMMENT_RE.match(line):
            continue
        if _TEMPLATE_SECTION_RE.match(line):
            if section and not skip_section:
                sections[section] = current_kv
            section, current_kv, skip_section = "_TPL_", {}, True
            continue
        sm = _RPT_SECTION_RE.match(line)
        if sm:
            if section and not skip_section:
                sections[section] = current_kv
            section      = sm.group(1).strip()
            current_kv   = {}
            skip_section = False
            continue
        if not skip_section:
            m = _RPT_KV_RE.match(line)
            if m:
                current_kv[m.group(1).lower()] = m.group(2).strip()
    if section and not skip_section:
        sections[section] = current_kv

    node_sects = {s: kv for s, kv in sections.items()
                  if s.isdigit() and not _RPT_NON_NODE_RE.match(s)}
    general_kv = next((kv for s, kv in sections.items()
                        if s.strip().lower() == "general"), {})
    return node_sects, general_kv

def get_reg_status() -> dict:
    checks: list = []

    http_content, http_err = read_asterisk_file("rpt_http_registrations.conf")
    iax_content,  iax_err  = read_asterisk_file("iax.conf")
    rpt_content,  rpt_err  = read_asterisk_file("rpt.conf")

    http_scan = _scan_register_lines(http_content) if not http_err else {"entries": [], "malformed": []}
    iax_scan  = _scan_register_lines(iax_content)  if not iax_err  else {"entries": [], "malformed": []}

    http_entries = http_scan["entries"]
    iax_entries  = iax_scan["entries"]
    http_active  = bool(http_entries)
    iax_active   = bool(iax_entries)

    if not http_active and not iax_active:
        checks.append({
            "title": "Registration", "value": "not configured",
            "status": "fail", "note": None, "url": None,
        })
    else:
        for node, has_pwd in http_entries:
            node_ok = node.isdigit() and len(node) >= 4
            checks.append({
                "title": f"HTTP Node {node}",
                "value": node if node_ok else "invalid",
                "status": "pass" if node_ok else "fail",
                "note": None, "url": None,
            })
            checks.append({
                "title": "Password", "value": None,
                "status": "pass" if has_pwd else "fail",
                "note": _ASL_NOTE, "url": _ASL_URL,
            })
        for node, has_pwd in iax_entries:
            node_ok = node.isdigit() and len(node) >= 4
            checks.append({
                "title": f"IAX Node {node}",
                "value": node if node_ok else "invalid",
                "status": "pass" if node_ok else "fail",
                "note": None, "url": None,
            })
            checks.append({
                "title": "Password", "value": None,
                "status": "pass" if has_pwd else "fail",
                "note": _ASL_NOTE, "url": _ASL_URL,
            })

    if http_active and iax_active:
        checks.append({
            "title": "Dual registration",
            "value": "HTTP and IAX both active",
            "status": "warn",
            "note": ("Don't register with both — wastes server load for "
                     "no gain. Pick one, comment out the other."),
            "url": "https://allstarlink.github.io/adv-topics/httpreg/",
        })

    all_malformed = http_scan["malformed"] + iax_scan["malformed"]
    if all_malformed:
        checks.append({
            "title": "Register line syntax",
            "value": all_malformed[0][:60],
            "status": "fail",
            "note": ("Looks like a register line but doesn't match the "
                     "required register=> node:password@host syntax "
                     "(missing arrow is a common copy/paste mistake)."),
            "url": None,
        })

    placeholder_hits = [n for n, _ in (http_entries + iax_entries)
                         if n in _PLACEHOLDER_NODES]
    if placeholder_hits:
        checks.append({
            "title": "Placeholder node number",
            "value": placeholder_hits[0],
            "status": "fail",
            "note": "Template default left unchanged — set your real assigned node number.",
            "url": None,
        })

    http_mod = module_state("res_rpt_http_registrations.so")
    if http_active and http_mod == "noload":
        checks.append({
            "title": "res_rpt_http_registrations.so",
            "value": "noload",
            "status": "fail",
            "note": "HTTP registration is configured but the module is set to noload in modules.conf.",
            "url": None,
        })
    elif http_active:
        checks.append({
            "title": "res_rpt_http_registrations.so",
            "value": http_mod,
            "status": "pass" if http_mod in ("load", "require", "blank") else "warn",
            "note": None, "url": None,
        })
    elif iax_active and http_mod in ("load", "require"):
        checks.append({
            "title": "res_rpt_http_registrations.so",
            "value": http_mod,
            "status": "warn",
            "note": "Only IAX registration is configured, but the HTTP registration module is still loaded.",
            "url": None,
        })

    if rpt_err:
        checks.append({
            "title": "rpt.conf", "value": rpt_err,
            "status": "fail", "note": None, "url": None,
        })
    else:
        node_sects, general_kv = _reg_scan_rpt_conf(rpt_content)
        registered_nodes = {n for n, _ in (http_entries + iax_entries)}

        for nid in sorted(node_sects.keys(), key=int):
            if registered_nodes and nid not in registered_nodes:
                checks.append({
                    "title": f"rpt.conf node {nid}",
                    "value": "no matching registration entry",
                    "status": "warn",
                    "note": "Node exists in rpt.conf but isn't in the registration file — check for a typo'd node number.",
                    "url": None,
                })

        for nid in sorted(node_sects.keys(), key=int):
            kv = node_sects[nid]
            statpost = kv.get("statpost_url", "").strip()
            if not statpost:
                continue
            url_ok = bool(_STATPOST_URL_RE.match(statpost))
            checks.append({
                "title": f"statpost {nid}",
                "value": statpost if url_ok else "unexpected URL",
                "status": "pass" if url_ok else "warn",
                "note": None, "url": None,
            })
            has_reg_entry = any(n == nid and pwd for n, pwd in http_entries)
            if not has_reg_entry:
                checks.append({
                    "title": f"statpost {nid} credential",
                    "value": "no matching HTTP registration password",
                    "status": "warn",
                    "note": ("statpost can 401 even on an otherwise healthy node if this "
                             "node/password pair drifts from rpt_http_registrations.conf — "
                             "this doesn't block registration itself."),
                    "url": None,
                })

        method = general_kv.get("node_lookup_method", "").strip().lower()
        if method and method not in _NODE_LOOKUP_VALUES:
            checks.append({
                "title": "node_lookup_method",
                "value": method,
                "status": "warn",
                "note": f"Expected one of {', '.join(sorted(_NODE_LOOKUP_VALUES))}.",
                "url": None,
            })
        domain = general_kv.get("dns_node_domain", "").strip()
        if domain and domain != _DEFAULT_DNS_DOMAIN:
            checks.append({
                "title": "dns_node_domain",
                "value": domain,
                "status": "info",
                "note": f"Overridden from the default ({_DEFAULT_DNS_DOMAIN}) — confirm this is intentional.",
                "url": None,
            })

    allmon3_path = _ALLMON3_DIR / "allmon3.ini"
    allmon3_content, allmon3_err = read_path_file(allmon3_path) if allmon3_path.is_file() \
        else ("", f"File not found: {allmon3_path}")
    manager_content, manager_err = read_asterisk_file("manager.conf")

    if not allmon3_err and not manager_err:
        allmon3_nodes = _reg_scan_allmon3(allmon3_content)
        manager_users = {s: kv for s, kv in _parse_sections(manager_content).items()
                          if s.strip().lower() != "general"}
        http_passwords = http_scan["passwords"]

        for nid in sorted(allmon3_nodes.keys(), key=lambda n: (not n.isdigit(), n)):
            am_user = allmon3_nodes[nid].get("user", "").strip()
            am_pass = allmon3_nodes[nid].get("pass", "").strip()
            if not am_user:
                continue

            mgr_kv = next((kv for s, kv in manager_users.items() if s.strip() == am_user), None)
            if mgr_kv is None:
                checks.append({
                    "title": f"AMI user [{nid}]",
                    "value": f"'{am_user}' not found in manager.conf",
                    "status": "warn",
                    "note": "Allmon3 will fail to connect locally even though AllStarLink registration can still succeed.",
                    "url": None,
                })
            else:
                mgr_secret = mgr_kv.get("secret", "").strip()
                if am_pass and mgr_secret and am_pass != mgr_secret:
                    checks.append({
                        "title": f"AMI credential [{nid}]",
                        "value": "allmon3.ini password != manager.conf secret",
                        "status": "warn",
                        "note": f"[{am_user}] secret in manager.conf has drifted from the password in allmon3.ini's [{nid}] stanza.",
                        "url": None,
                    })

            reg_pwd = http_passwords.get(nid)
            if reg_pwd and am_pass and reg_pwd != am_pass:
                checks.append({
                    "title": f"Registration vs AMI password [{nid}]",
                    "value": "differ",
                    "status": "info",
                    "note": "AllStarLink registration and local AMI access are separate credentials — this is only worth a look if you intended them to match.",
                    "url": None,
                })

    reg_live = get_state_snapshot().get("reg_live")
    if reg_live is None:
        checks.append({
            "title": "Live registration state",
            "value": "not yet polled",
            "status": "info",
            "note": "First background poll hasn't run yet — refresh in a moment.",
            "url": None,
        })
    elif not reg_live.get("ok"):
        checks.append({
            "title": "Live registration state",
            "value": reg_live.get("error") or "unavailable",
            "status": "warn",
            "note": "Couldn't reach the Asterisk CLI — the checks above are config-only until this clears.",
            "url": None,
        })
    else:
        live_nodes = reg_live.get("nodes", {})
        configured_http_nodes = {n for n, _ in http_entries}
        for nid in sorted(configured_http_nodes, key=str):
            live_state = live_nodes.get(nid, "not shown")
            if live_state == "registered":
                checks.append({
                    "title": f"Live registration [{nid}]",
                    "value": "registered", "status": "pass",
                    "note": None, "url": None,
                })
            elif live_state == "unregistered":
                checks.append({
                    "title": f"Live registration [{nid}]",
                    "value": "not registered",
                    "status": "fail",
                    "note": ("Config says this node should be registered but the live "
                             "state disagrees — check for a NAT/carrier issue (e.g. a "
                             "hotspot connection that intercepts and redirects HTTP "
                             "traffic) or a blocked outbound HTTPS path."),
                    "url": None,
                })
            else:
                checks.append({
                    "title": f"Live registration [{nid}]",
                    "value": live_state,
                    "status": "warn",
                    "note": ("Node is configured but didn't show up clearly in "
                             "`rpt show registrations` output — worth a manual look."),
                    "url": None,
                })

    if not checks:
        checks.append({
            "title": "Registration", "value": "nothing to check",
            "status": "info", "note": None, "url": None,
        })

    return {"ok": True, "checks": checks}

_SAVENODE_KV_RE = re.compile(r'^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(\S+)\s*(?:#.*)?$')

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
_AUTOLOAD_RE = re.compile(r'^\s*autoload\s*[=:]\s*(\S+)', re.IGNORECASE)

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

def validate_asterisk_filename(name: str) -> bool:
    return bool(_AST_FILE_RE.match(name)) and "/" not in name and ".." not in name

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

def read_asterisk_file(filename: str) -> "tuple[str, str | None]":
    if not validate_asterisk_filename(filename):
        return "", f"Invalid filename: {filename!r}"
    path = _AST_DIR / filename
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

def write_asterisk_file(filename: str, content: str) -> "tuple[bool, str]":
    if not validate_asterisk_filename(filename):
        return False, f"Invalid filename: {filename!r}"
    if not content.strip():
        return False, "Content must not be empty"
    path     = _AST_DIR / filename
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        _AST_DIR.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, content)  
        return True, f"Saved {path}"
    except Exception as exc:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception as e:
            log.debug("write_asterisk_file: %s", e)
            pass
        return False, f"Write failed: {exc}"

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
]

_SIMPLEUSB_FILE = Path("/etc/asterisk/simpleusb.conf")

_SIMPLEUSB_FIELD_SPECS = {
    "rxmixerset":  {"type": "int",  "min": 0, "max": 1000},
    "txmixaset":   {"type": "int",  "min": 0, "max": 1000},
    "txmixbset":   {"type": "int",  "min": 0, "max": 1000},
    "rxboost":     {"type": "bool"},
    "deemphasis":  {"type": "bool"},
    "preemphasis": {"type": "bool"},

    "rxondelay":   {"type": "int",  "min": 0, "max": 100},
    "txoffdelay":  {"type": "int",  "min": 0, "max": 100},
}

_USBRADIO_FILE = Path("/etc/asterisk/usbradio.conf")

_ALLMON3_DIR   = Path("/etc/allmon3")
_ALLMON3_FILES: "list[Path]" = [
    _ALLMON3_DIR / "allmon3.ini",
    _ALLMON3_DIR / "web.ini",
    _ALLMON3_DIR / "users",
    _ALLMON3_DIR / "menu.ini",
    _ALLMON3_DIR / "custom.css",
]

_ALLMON3_READONLY = {"users"}

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

    for key, val_str in formatted.items():
        occ_list = occurrences.get(key, [])
        non_tmpl = [o for o in occ_list if not o[2]]
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

    unplaced = set(formatted) - updated_keys - appended_keys
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
                normalized = val_clean.strip().lower()
                if normalized in ("yes", "no"):
                    result[key] = normalized
                else:
                    _log(f"WARN — simpleusb {key} not yes/no: {val_clean}")
    except Exception as e:
        _log(f"WARN — simpleusb parse error: {e}")

    return result

def parse_usbradio_settings(path: Path = _USBRADIO_FILE) -> dict:
    result = {
        "devstr":      None,
        "rxmixerset":  None,
        "txmixaset":   None,
        "txmixbset":   None,
        "rxvoiceadj":  None,
        "rxctcssadj":  None,
        "txctcssadj":  None,
        "rxsquelchadj":None,
        "fever":       None,
        "txslimsp":    None,
        "path":        str(path),
        "exists":      False,
    }

    if not path.exists():
        return result

    result["exists"] = True
    int_keys   = ("rxmixerset", "txmixaset", "txmixbset",
                  "txctcssadj", "rxsquelchadj", "fever", "txslimsp")
    float_keys = ("rxvoiceadj", "rxctcssadj")

    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        occurrences, _stanzas, _dev = _tune_scan_conf(lines, int_keys + float_keys)
        for key, occ_list in occurrences.items():
            val_clean = _tune_effective_value(lines, occ_list)
            if key == "devstr":
                result["devstr"] = val_clean
            elif key in int_keys:
                try:
                    result[key] = int(val_clean)
                except ValueError:
                    _log(f"WARN — usbradio {key} not numeric: {val_clean}")
            elif key in float_keys:
                try:
                    result[key] = float(val_clean)
                except ValueError:
                    _log(f"WARN — usbradio {key} not numeric: {val_clean}")
    except Exception as e:
        _log(f"WARN — usbradio parse error: {e}")

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
            normalized = str(val).strip().lower()
            if normalized not in ("yes", "no"):
                msg = f"{key} must be 'yes' or 'no', got {repr(val)}"
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
        msg = "; ".join(parts)

        audit_log = []
        for key in sorted(updated_keys | appended_keys):
            old_val = old_values.get(key)
            new_val = formatted[key]

            audit_log.append(f"{key} {old_val}→{new_val}")

        _log(f"simpleusb tune saved: {msg} ({'; '.join(audit_log)})")
        return True, msg

    except Exception as e:
        msg = f"Save failed: {str(e)}"
        _log(f"WARN — simpleusb save error: {msg}", stderr=True)
        return False, msg

_DVS_SECTION_RE = re.compile(r'^\s*\[([^\]]+)\]\s*(?:;.*)?$')
_DVS_KV_RE      = re.compile(r'^\s*([A-Za-z_][\w]*)\s*=\s*(.*?)\s*(?:;.*)?$')
_DVS_COMMENT_RE = re.compile(r'^\s*[;#]')

_AB_DEF_DMR_ID     = "1234567"
_AB_DEF_RPT_ID     = "123456789"
_MB_DEF_CALLSIGN   = "N0CALL"
_MB_DEF_DMR_ID     = "1234567"

_DVS_DEF_SERVER    = "3102.repeater.net"
_DVS_DEF_DMR_ID    = "1234567"
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

def save_usbradio_settings(updates: dict, path: Path = _USBRADIO_FILE) -> tuple[bool, str]:
    if not path.exists():
        msg = f"File not found: {path}"
        _log(f"WARN — usbradio save: {msg}")
        return False, msg
    
    validation_rules = {
        "rxmixerset":  ("int", 0, 1000),
        "txmixaset":   ("int", 0, 1000),
        "txmixbset":   ("int", 0, 1000),
        "txctcssadj":  ("int", 0, 1000),
        "rxsquelchadj":("int", 0, 1000),
        "fever":       ("int_enum", [0, 1]),
        "txslimsp":    ("int", 1000, 100000),
        "rxvoiceadj":  ("float", 0.0, 1.0),
        "rxctcssadj":  ("float", 0.0, 1.0),
    }
    
    for key, val in updates.items():
        if val is None or key == "devstr":

            continue
        
        if key not in validation_rules:
            return False, f"Unknown field: {key}"
        
        rule = validation_rules[key]
        rule_type = rule[0]
        
        try:
            if rule_type == "int":
                ival = int(val)
                min_val, max_val = rule[1], rule[2]
                if ival < min_val or ival > max_val:
                    return False, f"{key}: out of range [{min_val}, {max_val}], got {ival}"
            
            elif rule_type == "int_enum":
                ival = int(val)
                allowed = rule[1]
                if ival not in allowed:
                    return False, f"{key}: must be one of {allowed}, got {ival}"
            
            elif rule_type == "float":
                fval = float(val)
                min_val, max_val = rule[1], rule[2]
                if fval < min_val or fval > max_val:
                    return False, f"{key}: out of range [{min_val}, {max_val}], got {fval}"
        
        except (TypeError, ValueError) as e:
            return False, f"{key}: invalid type — {e}"
    
    try:
        old_values = parse_usbradio_settings(path)

        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        formatted = {}
        for key, val in updates.items():
            if val is None or key == "devstr":
                continue
            if validation_rules[key][0] == "float":
                formatted[key] = f"{float(val):.6f}"
            else:
                formatted[key] = str(int(val))
        if not formatted:
            return False, "no settings to update"

        new_lines, updated_keys, appended_keys, err = \
            _tune_apply_updates(lines, formatted)
        if err:
            _log(f"WARN — usbradio save: {err}")
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
        msg = "; ".join(parts)

        audit_log = []
        for key in sorted(updated_keys | appended_keys):
            audit_log.append(f"{key} {old_values.get(key)}→{updates[key]}")

        _log(f"usbradio save: {msg} ({'; '.join(audit_log)})")
        return True, msg

    except Exception as e:
        _log(f"WARN — usbradio save error: {e}")
        return False, str(e)

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
        if driver == "usbradio":
            settings = parse_usbradio_settings()
        else:
            settings = parse_simpleusb_tune_settings()
        if not settings:
            return True, "up (tune file empty or unparsed)"
    except Exception as e:
        return True, f"up (tune re-read failed: {e})"
    return True, "up"

def _dvs_parse_sections(content: str) -> "dict[str, dict]":
    sections: "dict[str, dict]" = {}
    section = ""
    kv: "dict[str, str]" = {}
    for line in content.splitlines():
        if _DVS_COMMENT_RE.match(line):
            continue
        sm = _DVS_SECTION_RE.match(line)
        if sm:
            if section:
                sections[section] = kv
            section, kv = sm.group(1).strip().upper(), {}
            continue
        m = _DVS_KV_RE.match(line)
        if m:
            kv[m.group(1)] = m.group(2).strip()
    if section:
        sections[section] = kv
    return sections

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

def parse_usrp2m17_ini(content: str) -> list:
    sections = _dvs_parse_sections(content)
    m17_net  = sections.get("M17 NETWORK", {})
    usrp_net = sections.get("USRP NETWORK", {})
    checks: list = []

    callsign = m17_net.get("Callsign", "").strip()
    address  = m17_net.get("Address",  "").strip()
    name     = m17_net.get("Name",     "").strip()

    checks.append({"title": "Callsign", "value": callsign or "not set",
                   "status": "pass" if callsign else "fail", "notes": None})
    is_disconnected = (not address) or address == _M17_PLACEHOLDER_ADDRESS
    checks.append({"title": "Reflector", "value": (name or "—") + (f" ({address})" if address else ""),
                   "status": "info" if is_disconnected else "pass",
                   "notes": "Placeholder / disconnected" if is_disconnected else None})

    usrp_dst   = usrp_net.get("DstPort",   "").strip()
    usrp_local = usrp_net.get("LocalPort", "").strip()
    ports_ok   = (usrp_dst == _M17_EXPECT_USRP_DST_PORT and usrp_local == _M17_EXPECT_USRP_LOCAL_PORT)
    checks.append({
        "title":  "USRP ports",
        "value":  f"DstPort={usrp_dst or '—'} LocalPort={usrp_local or '—'}",
        "status": "pass" if ports_ok else "fail",
        "notes":  None if ports_ok else f"Expected {_M17_EXPECT_USRP_DST_PORT}/{_M17_EXPECT_USRP_LOCAL_PORT}",
    })

    if not sections:
        checks = [{"title": "Sections", "value": "No sections found",
                   "status": "fail", "notes": None}]
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

_APPCONF_FILES: "list[Path]" = [
    Path("/etc/asl_dvs/asl_dvs.conf"),
    Path("/etc/sysmon/sysmon.conf"),
]

def _appconf_file_by_label(label: str) -> "Path | None":
    for p in _APPCONF_FILES:
        if p.name == label:
            return p
    return None

def _allmon3_file_by_label(label: str) -> "Path | None":
    for p in _ALLMON3_FILES:
        if p.name == label:
            return p
    return None

def _dvs_file_by_label(label: str) -> "Path | None":
    first_match = None
    for p in _DVSWITCH_FILES:
        if p.name == label:
            if first_match is None:
                first_match = p
            if p.is_file():
                return p
    return first_match

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
    return items

_IAX_CONF  = Path("/etc/asterisk/iax.conf")
_RPT_CONF  = Path("/etc/asterisk/rpt.conf")
_AB_CFG    = Path("/etc/dvswitch/analog_bridge.cfg")

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

def _iax_parse_sections(content: str) -> "dict[str, dict]":
    _iax_sect_re = re.compile(r'^\s*\[([^\]]+)\]\s*(?:;.*)?$')
    sections: "dict[str, dict]" = {}
    _sec = ""
    _kv:  "dict[str, str]" = {}
    for _ln in content.splitlines():
        if _RPT_COMMENT_RE.match(_ln):
            continue
        _sm = _iax_sect_re.match(_ln)
        if _sm:
            if _sec:
                sections[_sec] = _kv
            _sec, _kv = _sm.group(1).strip(), {}
            continue
        _m = _RPT_KV_RE.match(_ln)
        if _m:
            _kv[_m.group(1).lower()] = _m.group(2).strip()
    if _sec:
        sections[_sec] = _kv
    return sections

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

    sections: "dict[str, dict]" = {}
    section   = ""
    current_kv: "dict[str, str]" = {}
    skip_section = False

    for line in content.splitlines():
        if _RPT_COMMENT_RE.match(line):
            continue
        if _TEMPLATE_SECTION_RE.match(line):
            if section and not skip_section:
                sections[section] = current_kv
            section, current_kv, skip_section = "_TPL_", {}, True
            continue
        sm = _RPT_SECTION_RE.match(line)
        if sm:
            if section and not skip_section:
                sections[section] = current_kv
            section      = sm.group(1).strip()
            current_kv   = {}
            skip_section = False
            continue
        if not skip_section:
            m = _RPT_KV_RE.match(line)
            if m:
                current_kv[m.group(1).lower()] = m.group(2).strip()
    if section and not skip_section:
        sections[section] = current_kv

    node_sects = {s: kv for s, kv in sections.items()
                  if s.isdigit() and not _RPT_NON_NODE_RE.match(s)}

    callsign = ""
    for s in sorted(node_sects.keys(), key=int):
        cs = _rpt_callsign(node_sects[s])
        if cs:
            callsign = cs
            break

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
        compat += [
            _compat("propagate_dtmf",      src, "DTMF commands from DVSM",
                    n["propagate_dtmf"],
                    f"Add 'propagate_dtmf = yes' to [{nid}] in rpt.conf, restart asterisk"),
            _compat("propagate_phonedtmf", src, "Phone DTMF (HamVoIP nodes)",
                    n["propagate_phonedtmf"],
                    f"Add 'propagate_phonedtmf = yes' to [{nid}] in rpt.conf, restart asterisk"),
            _compat("remote_dtmf_allowed", src, "DTMF from remote connections",
                    n["remote_dtmf_allowed"],
                    f"Add 'remote_dtmf_allowed = 1' to [{nid}] in rpt.conf, restart asterisk"),
            _compat("phonesendlinks",      src, "DVSM Status tab — linked-node list",
                    n["phonesendlinks"],
                    f"Add 'phonesendlinks = 1' to [{nid}] in rpt.conf, restart asterisk"),
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

_STFU_BINARY        = Path("/opt/STFU/STFU")
_STFU_SERVICE_NAME  = "stfu"
_STFU_SERVICE_PATHS = [
    Path("/lib/systemd/system/stfu.service"),
    Path("/etc/systemd/system/stfu.service"),
]

_STFU_DVS_CANDIDATES = [
    Path("/opt/MMDVM_Bridge/DVSwitch.ini"),
    Path("/etc/MMDVM_Bridge/DVSwitch.ini"),
    Path("/etc/dvswitch/DVSwitch.ini"),
]

_STFU_MB_CANDIDATES = [
    Path("/opt/MMDVM_Bridge/MMDVM_Bridge.ini"),
    Path("/etc/MMDVM_Bridge/MMDVM_Bridge.ini"),
]

_STFU_AB_CANDIDATES = [
    Path("/opt/Analog_Bridge/Analog_Bridge.ini"),
    Path("/etc/Analog_Bridge/Analog_Bridge.ini"),
]

def _stfu_install_check() -> dict:

    binary_ok   = (
        _STFU_BINARY.exists()
        and os.access(str(_STFU_BINARY), os.X_OK)
    )
    binary_path = str(_STFU_BINARY) if binary_ok else ""

    svc_path = next(
        (str(p) for p in _STFU_SERVICE_PATHS if p.exists()), ""
    )
    svc_installed = bool(svc_path)

    svc_active  = False
    svc_enabled = False
    if svc_installed:
        try:
            svc_active  = _run(
                ["systemctl", "is-active",  _STFU_SERVICE_NAME], timeout=4
            ).strip() == "active"
            svc_enabled = _run(
                ["systemctl", "is-enabled", _STFU_SERVICE_NAME], timeout=4
            ).strip() == "enabled"
        except Exception as e:
            log.debug("_stfu_install_check: %s", e)
            pass

    return {
        "binary_ok":         binary_ok,
        "binary_path":       binary_path,
        "service_installed": svc_installed,
        "service_path":      svc_path,
        "service_active":    svc_active,
        "service_enabled":   svc_enabled,
    }

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

def _stfu_sample_stanza(cfg: dict) -> str:
    def _v(val: str, placeholder: str) -> str:
        return val if val else f"<{placeholder}>"

    lines = [
        "[STFU]",
        f"BMAddress={_v(cfg['bm_address'],    'BM server address')}",
        f"BMPort={cfg['bm_port'] or '62031'}",
        "BMPassword=<your BM hotspot password>",
        f"UserID={_v(cfg['dmr_id'],           'your DMR ID')}",
        f"Address={cfg['address'] or '127.0.0.1'}",
        f"RXPort={_v(cfg['rx_port'],           'rx port')}",
        f"TXPort={_v(cfg['tx_port'],           'tx port')}",
        f"StartTG={_v(cfg['start_tg'],         'starting talkgroup')}",
        f"subscriberFile={_v(cfg['subscriber_file'], '/opt/STFU/subscriber_ids.csv')}",
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

_M17_BINARY        = Path("/opt/USRP2M17/USRP2M17")
_M17_SERVICE_NAME  = "usrp2m17"
_M17_SERVICE_PATHS = [
    Path("/lib/systemd/system/usrp2m17.service"),
    Path("/etc/systemd/system/usrp2m17.service"),
]
_M17_INI_CANDIDATES = [
    Path("/opt/USRP2M17/USRP2M17.ini"),
]
_M17_EXPECT_USRP_DST_PORT   = "32008"
_M17_EXPECT_USRP_LOCAL_PORT = "34008"
_M17_PLACEHOLDER_ADDRESS    = "0.0.0.0"

def _m17_install_check() -> dict:
    binary_ok   = (
        _M17_BINARY.exists()
        and os.access(str(_M17_BINARY), os.X_OK)
    )
    binary_path = str(_M17_BINARY) if binary_ok else ""

    svc_path = next(
        (str(p) for p in _M17_SERVICE_PATHS if p.exists()), ""
    )
    svc_installed = bool(svc_path)

    svc_active  = False
    svc_enabled = False
    if svc_installed:
        try:
            svc_active  = _run(
                ["systemctl", "is-active",  _M17_SERVICE_NAME], timeout=4
            ).strip() == "active"
            svc_enabled = _run(
                ["systemctl", "is-enabled", _M17_SERVICE_NAME], timeout=4
            ).strip() == "enabled"
        except Exception as e:
            log.debug("_m17_install_check: %s", e)
            pass

    return {
        "binary_ok":         binary_ok,
        "binary_path":       binary_path,
        "service_installed": svc_installed,
        "service_path":      svc_path,
        "service_active":    svc_active,
        "service_enabled":   svc_enabled,
    }

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

def _m17_find_rpt_node(rpt: dict, node_id: str) -> "dict | None":
    for n in rpt.get("nodes", []):
        if n.get("id") == node_id:
            return n
    return None

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
    def _v(val: str, placeholder: str) -> str:
        return val if val else f"<{placeholder}>"

    lines = [
        "[M17 Network]",
        f"Callsign={_v(cfg['callsign'], 'your callsign')}",
        f"Address={_v(cfg['address'], 'reflector IP')}",
        f"Name={_v(cfg['name'], 'M17-XXX C')}",
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
    }

_ZELLO_SERVICE_NAME  = "asl-zello-bridge"
_ZELLO_SERVICE_PATHS = [
    Path("/etc/systemd/system/asl-zello-bridge.service"),
    Path("/lib/systemd/system/asl-zello-bridge.service"),
]
_ZELLO_VENV_BIN      = Path("/opt/asl-zello-bridge/venv/bin/asl-zello-bridge")
_ZELLO_SETUPPY_HINT  = Path("/opt/asl-zello-bridge")

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

    svc_path = next(
        (str(p) for p in _ZELLO_SERVICE_PATHS if p.exists()), ""
    )
    svc_installed = bool(svc_path)

    svc_active  = False
    svc_enabled = False
    if svc_installed:
        try:
            svc_active  = _run(
                ["systemctl", "is-active",  _ZELLO_SERVICE_NAME], timeout=4
            ).strip() == "active"
            svc_enabled = _run(
                ["systemctl", "is-enabled", _ZELLO_SERVICE_NAME], timeout=4
            ).strip() == "enabled"
        except Exception as e:
            log.debug("_zello_install_check: %s", e)
            pass

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
    def _v(val: str, placeholder: str) -> str:
        return val if val else f"<{placeholder}>"

    env = cfg["env"]
    lines = [
        "[Service]",
        f"Environment=USRP_BIND={env['USRP_BIND'] or '127.0.0.1'}",
        f"Environment=USRP_HOST={env['USRP_HOST'] or '127.0.0.1'}",
        f"Environment=USRP_RXPORT={env['USRP_RXPORT'] or _ZELLO_EXPECT_USRP_RXPORT}",
        f"Environment=USRP_TXPORT={env['USRP_TXPORT'] or _ZELLO_EXPECT_USRP_TXPORT}",
        "",
        f"Environment=ZELLO_USERNAME={_v(env['ZELLO_USERNAME'], 'bridge account username')}",
        f"Environment=ZELLO_PASSWORD={_v(env['ZELLO_PASSWORD'], 'bridge account password')}",
        f'Environment=ZELLO_CHANNEL="{env["ZELLO_CHANNEL"] or "<channel name>"}"',
        "",
        f"Environment=ZELLO_PRIVATE_KEY={_v(env['ZELLO_PRIVATE_KEY'], '/opt/asl-zello-bridge/zello.key')}",
        f"Environment=ZELLO_ISSUER={_v(env['ZELLO_ISSUER'], 'issuer-id from developers.zello.com')}",
        f"Environment=ZELLO_WS_ENDPOINT={env['ZELLO_WS_ENDPOINT'] or 'wss://zello.io/ws'}",
        "",
        f"Environment=USRP_GAIN_RX_DB={env['USRP_GAIN_RX_DB'] or '0'}",
        f"Environment=USRP_GAIN_TX_DB={env['USRP_GAIN_TX_DB'] or '0'}",
        f"Environment=LOG_LEVEL={env['LOG_LEVEL'] or 'INFO'}",
    ]
    return "\n".join(lines)

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

def get_firewall_backend() -> str:
    
    if shutil.which("ufw"):
        return "ufw"
    if shutil.which("firewall-cmd"):
        state = _run(["firewall-cmd", "--state"], timeout=4).strip()
        if state == "running":
            return "firewalld"
    for tool in ("nft", "iptables"):
        if shutil.which(tool):
            return tool
    return "none"

def get_ufw_status() -> str:
    raw = _run(["ufw", "status"], timeout=5)
    if "active" in raw.lower():
        return "active"
    if "inactive" in raw.lower():
        return "inactive"
    return "unknown"

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

def get_raw_ruleset(backend: str) -> str:
    if backend == "nft":
        return _run(["nft", "list", "ruleset"], timeout=6)
    if backend == "iptables":
        return _run(["iptables", "-L", "-n", "-v", "--line-numbers"], timeout=6)
    return ""

def _label_fw_rule(rule: dict, pinned: list) -> str:
    to = rule.get("to", "")
    port_part = to.split("/")[0] if "/" in to else to

    if "-" in port_part:
        
        try:
            lo_s, hi_s = port_part.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
        except ValueError:
            return _WELL_KNOWN_PORTS.get(port_part, "")
        for entry in pinned:
            if "group" in entry:
                continue
            try:
                ep = int(entry.get("port", -1))
            except (TypeError, ValueError):
                continue
            if lo <= ep <= hi:
                return entry.get("unit", "").replace(".service", "")
        return _WELL_KNOWN_PORTS.get(port_part, "")

    if not port_part.isdigit():
        return ""
    for entry in pinned:
        if "group" in entry:
            continue
        ep = entry.get("port", "-")
        if str(ep) == port_part:
            return entry.get("unit", "").replace(".service", "")
    return _WELL_KNOWN_PORTS.get(port_part, "")

_WELL_KNOWN_PORTS = {
    "22":   "SSH",
    "53":   "DNS",
    "80":   "Web (HTTP)",
    "443":  "Web (HTTPS)",
    "9090": "Cockpit",
    "5353": "mDNS",
    "123":  "NTP",
    "67":   "DHCP",
    "68":   "DHCP",
}

_NFT_COMMENT_PREFIX = "sysmon"

def _nft_rule_comment(port: str, proto: str) -> str:
    return f"{_NFT_COMMENT_PREFIX}-{port}-{proto}"

def _nft_find_input_chain() -> "tuple[str, str, str] | None":
    raw = _run(["nft", "list", "ruleset"], timeout=6)
    if not raw:
        return None

    candidates: "list[tuple[str, str, str]]" = []
    depth = 0
    cur_family = cur_table = cur_chain = None
    table_depth = chain_depth = None

    for raw_line in raw.splitlines():
        line = raw_line.strip()

        m_table = re.match(r'^table\s+(\w+)\s+(\S+)\s*\{', line)
        if m_table and table_depth is None:
            cur_family, cur_table = m_table.group(1), m_table.group(2)
            table_depth = depth
            depth += 1
            continue

        m_chain = re.match(r'^chain\s+(\S+)\s*\{', line)
        if m_chain and cur_table is not None and chain_depth is None:
            cur_chain = m_chain.group(1)
            chain_depth = depth
            depth += 1
            continue

        if cur_chain is not None and re.match(r'^type\s+\S+\s+hook\s+input\b', line):
            candidates.append((cur_family, cur_table, cur_chain))

        opens  = line.count("{")
        closes = line.count("}")
        depth += opens - closes

        if chain_depth is not None and depth <= chain_depth:
            cur_chain   = None
            chain_depth = None
        if table_depth is not None and depth <= table_depth:
            cur_table   = None
            cur_family  = None
            table_depth = None

    uniq = list(dict.fromkeys(candidates))
    return uniq[0] if len(uniq) == 1 else None

def _nft_add_rule(family: str, table: str, chain: str,
                   port: str, proto: str, verdict: str) -> "tuple[bool, str]":
    comment = _nft_rule_comment(port, proto)
    cmd = ["nft", "insert", "rule", family, table, chain,
           proto, "dport", port, verdict, "comment", f'"{comment}"']
    r  = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    ok = r.returncode == 0
    msg = (f"nft {verdict} {port}/{proto} ({family} {table} {chain}): "
           f"{'OK' if ok else r.stderr.strip() or 'failed'}")
    return ok, msg

def _nft_list_tagged_rules(family: str, table: str, chain: str) -> list:
    raw = _run(["nft", "-a", "list", "chain", family, table, chain], timeout=6)
    if not raw:
        return []

    rules = []
    pattern = re.compile(
        r'(tcp|udp)\s+dport\s+(\d+)\s+(accept|drop)\s+'
        r'comment\s+"' + re.escape(_NFT_COMMENT_PREFIX) + r'-\d+-(?:tcp|udp)"'
        r'.*?\bhandle\s+(\d+)'
    )
    for line in raw.splitlines():
        m = pattern.search(line.strip())
        if not m:
            continue
        proto, port, verdict, handle = m.groups()
        rules.append({
            "num":    int(handle),
            "to":     f"{port}/{proto}",
            "action": "ALLOW" if verdict == "accept" else "DENY",
            "from":   "Anywhere",
        })
    return rules

def _nft_delete_rule(family: str, table: str, chain: str, handle: int) -> "tuple[bool, str]":
    r = subprocess.run(
        ["nft", "delete", "rule", family, table, chain, "handle", str(handle)],
        capture_output=True, text=True, timeout=10,
    )
    ok  = r.returncode == 0
    msg = f"nft delete handle {handle}: {'OK' if ok else r.stderr.strip() or 'failed'}"
    return ok, msg

def _firewalld_zone() -> "str | None":
    raw = _run(["firewall-cmd", "--get-active-zones"], timeout=5)
    zones = [ln.strip() for ln in raw.splitlines() if ln and not ln[0].isspace()]
    if len(zones) == 1:
        return zones[0]
    if len(zones) == 0:
        dz = _run(["firewall-cmd", "--get-default-zone"], timeout=5).strip()
        return dz or None
    return None

def _firewalld_add_port(zone: str, port: str, proto: str) -> "tuple[bool, str]":
    spec = f"{port}/{proto}"
    r1 = subprocess.run(
        ["firewall-cmd", f"--zone={zone}", f"--add-port={spec}"],
        capture_output=True, text=True, timeout=10,
    )
    r2 = subprocess.run(
        ["firewall-cmd", f"--zone={zone}", f"--add-port={spec}", "--permanent"],
        capture_output=True, text=True, timeout=10,
    )
    ok  = r1.returncode == 0 and r2.returncode == 0
    detail = (r1.stderr.strip() or r2.stderr.strip()) if not ok else "OK (runtime + permanent)"
    return ok, f"firewalld allow {spec} (zone={zone}): {detail}"

def _firewalld_remove_port(zone: str, port: str, proto: str) -> "tuple[bool, str]":
    spec = f"{port}/{proto}"
    r1 = subprocess.run(
        ["firewall-cmd", f"--zone={zone}", f"--remove-port={spec}"],
        capture_output=True, text=True, timeout=10,
    )
    r2 = subprocess.run(
        ["firewall-cmd", f"--zone={zone}", f"--remove-port={spec}", "--permanent"],
        capture_output=True, text=True, timeout=10,
    )
    ok  = r1.returncode == 0 and r2.returncode == 0
    detail = (r1.stderr.strip() or r2.stderr.strip()) if not ok else "OK (runtime + permanent)"
    
    return ok, f"firewalld deny (remove-port) {spec} (zone={zone}): {detail}"

def _firewalld_list_ports(zone: str) -> list:
    raw = _run(["firewall-cmd", f"--zone={zone}", "--list-ports"], timeout=6)
    rules = []
    for spec in raw.split():
        if "/" not in spec:
            continue
        rules.append({
            "num":    spec,
            "to":     spec,
            "action": "ALLOW",
            "from":   f"zone={zone}",
        })
    return rules

_FW_TARGET_DESC = {
    "default":     "blocks anything not explicitly allowed",
    "ACCEPT":      "allows everything by default (rules here only add extra blocks)",
    "DROP":        "silently drops anything not explicitly allowed",
    "REJECT":      "rejects (with an error) anything not explicitly allowed",
    "%%REJECT%%":  "rejects (with an error) anything not explicitly allowed",
}

def _fw_target_desc(target: str) -> str:
    return _FW_TARGET_DESC.get(target, target or "unknown")

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

def _fw_state_map() -> "dict[str, str]":
    backend = get_firewall_backend()
    m: "dict[str, str]" = {}

    if backend == "ufw":
        for r in get_ufw_rules():
            to = r.get("to", "")
            if "/" not in to:
                continue
            port, proto = to.split("/", 1)
            if not port.isdigit():
                continue
            action = r.get("action", "")
            if action == "ALLOW":
                m[f"{port}/{proto}"] = "allow"
            elif action in ("DENY", "REJECT"):
                m[f"{port}/{proto}"] = "deny"

    elif backend == "nft":
        chain_ref = _nft_find_input_chain()
        if chain_ref:
            for r in _nft_list_tagged_rules(*chain_ref):
                to = r.get("to", "")
                if "/" not in to:
                    continue
                m[to] = "allow" if r.get("action") == "ALLOW" else "deny"

    elif backend == "firewalld":
        zone = _firewalld_zone()
        if zone:
            
            for r in _firewalld_list_ports(zone):
                to = r.get("to", "")
                if "/" in to:
                    m[to] = "allow"

    return m

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
}
_state_lock = threading.Lock()

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

/* ============================================================
   DESIGN TOKENS — colors, fonts (used throughout)
   ============================================================ */
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
  --mono:'Courier New',Courier,monospace;
  --sans:Arial,Helvetica,sans-serif;
}

/* ============================================================
   GLOBAL RESET & PAGE SHELL
   ============================================================ */
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--sans);
     height:100vh;height:100dvh;  
     overflow:hidden;display:flex;flex-direction:column}


/* ============================================================
   HEADER BAR
   ============================================================ */
header{background:linear-gradient(90deg,#0f1a2e,#161e2e 50%,#0f1a2e);
  border-bottom:2px solid var(--amber);padding:.75rem 1rem;
  display:flex;align-items:center;flex-shrink:0;
  box-shadow:0 2px 0 rgba(255,208,64,.25),0 6px 30px rgba(0,0,0,.7)}
.logo{font-family:var(--mono);font-size:1.21rem;color:var(--amber);
  letter-spacing:.1em;
  text-shadow:0 0 10px rgba(255,208,64,.9),0 0 30px rgba(255,208,64,.5),
              0 0 60px rgba(255,208,64,.2)}
.logo-sub{font-family:var(--mono);font-size:.715rem;letter-spacing:.22em;
  text-transform:uppercase;color:var(--amber);margin-top:.1rem;opacity:.75}
#hdr-right{margin-left:auto;display:flex;flex-direction:column;align-items:flex-end;gap:.15rem}
#hdr-uptime{font-family:var(--mono);font-size:.792rem;color:var(--amber);
  letter-spacing:.08em;text-shadow:0 0 8px rgba(255,208,64,.5);white-space:nowrap}
#hdr-version{font-family:var(--mono);font-size:.605rem;color:#6b4800;
  letter-spacing:.14em;text-transform:uppercase}


/* ============================================================
   EMERGENCY / DASHBOARD LINK BAR
   ============================================================ */
#emg-bar{background:#1a0608;border-bottom:1px solid var(--red-dim);
  padding:.28rem 1rem;display:flex;align-items:center;
  justify-content:center;gap:.7rem;flex-shrink:0;position:relative}
.lnk-dashboard{
  position:absolute;
  right:1rem;
  font-family:var(--mono);
  font-size:.66rem;
  font-weight:700;
  letter-spacing:.08em;
  text-transform:uppercase;
  text-decoration:none;
  padding:.18rem .55rem;
  border:1px solid var(--green-dim);
  border-radius:3px;
  color:var(--green);
  background:rgba(0,255,176,.05);
  white-space:nowrap;
  flex-shrink:0;
  transition:background .15s,box-shadow .15s}
.lnk-dashboard:hover{
  background:rgba(0,255,176,.12);
  box-shadow:0 0 8px rgba(0,255,176,.3)}


/* ============================================================
   STATUS STRIP (uptime/CPU/temp row under header)
   ============================================================ */
#zone-status{background:#111828;border-bottom:1px solid var(--border);
  padding:.28rem 1rem;display:flex;align-items:center;
  flex-shrink:0;font-family:var(--mono);font-size:.77rem;overflow:hidden;
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
.sl{color:#fff;font-size:.605rem;letter-spacing:.12em;text-transform:uppercase}
.sv{color:var(--text)}
.sv.ok{color:var(--green);text-shadow:0 0 6px rgba(0,255,176,.4)}
.sv.warn{color:var(--amber);text-shadow:0 0 6px rgba(255,208,64,.4)}
.sv.hot{color:var(--red);text-shadow:0 0 6px rgba(255,61,90,.4)}
.sv.cyan{color:var(--teal);text-shadow:0 0 6px rgba(0,255,229,.4)}


/* ============================================================
   TAB BAR & COMMAND ROW
   ============================================================ */
#zone-cmdbar{background:var(--surface);border-bottom:1px solid var(--border2);
  padding:.38rem .6rem;display:flex;align-items:center;
  flex-wrap:wrap;gap:.3rem;flex-shrink:0}
.tab-btn{font-family:var(--mono);font-size:.858rem;font-weight:bold;
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


/* ============================================================
   RADIO PRESET BUTTONS (Tune tab)
   ============================================================ */
.radio-btn{font-family:var(--mono);font-size:.77rem;font-weight:bold;
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
  .radio-btn{padding:.28rem .5rem;font-size:.7rem}
}
@media (max-width:900px){
  .radio-btn{padding:.24rem .4rem;font-size:.65rem}
}


/* ============================================================
   SHARED: generic buttons (.btn + color variants)
   Variants only need to stay AFTER the base .btn rule below —
   their order relative to each other does not matter.
   ============================================================ */
.btn{font-family:var(--mono);font-size:.858rem;font-weight:bold;
  letter-spacing:.05em;text-transform:uppercase;padding:.38rem .85rem;
  border-radius:4px;border:1px solid;background:transparent;cursor:pointer;
  transition:all .14s;white-space:nowrap}
.btn:hover{filter:brightness(1.6);box-shadow:0 0 12px currentColor}
.btn:active{transform:scale(.95)}
.btn:disabled{opacity:.35;cursor:not-allowed;filter:none;box-shadow:none}
.btn-sm{font-size:.77rem;padding:.22rem .5rem}
.btn-red{color:var(--red);border-color:var(--red-dim)}
.btn-amber{color:var(--amber);border-color:var(--amber-dim)}
.btn-green{color:var(--green);border-color:var(--green-dim)}
.btn-blue{color:var(--blue);border-color:var(--blue-dim)}
.btn-teal{color:var(--teal);border-color:var(--teal-dim)}
.btn-muted{color:#fff;border-color:var(--border2)}
.btn-purple{color:var(--purple);border-color:var(--purple-dim)}
.btn-orange{color:var(--orange);border-color:var(--orange-dim)}
.btn-sky{color:var(--sky);border-color:var(--sky-dim)}
/* .btn-orange and .btn-sky consolidated here from the DVSM/STFU
   sections below, where they were originally defined out of place.
   Safe to move: both are single-class rules that only ever combine
   with .btn on the same element, and both still appear after the
   base .btn rule, so cascade behavior is unchanged. */


/* ============================================================
   MAIN CONTENT AREA & TAB PANEL SWITCHING
   ============================================================ */
#zone-content{flex:1;overflow-y:auto;position:relative;
  padding:.8rem 1rem calc(1.6rem + env(safe-area-inset-bottom, 0px))}

/* ============================================================
   GLOBAL SCROLLBAR STYLING & UTILITY CLASSES
   ============================================================ */
#zone-content::-webkit-scrollbar{width:4px}
#zone-content::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}

.tab-panel{display:none}
.tab-panel.active{display:block}


/* ============================================================
   RESTART BANNER
   ============================================================ */
#restart-banner{display:none;background:#2a1400;border-bottom:1px solid var(--amber-dim);
  padding:.32rem 1rem;font-family:var(--mono);font-size:.77rem;color:var(--amber);
  text-align:center;letter-spacing:.06em;flex-shrink:0}
#restart-banner.show{display:block}


/* ============================================================
   OFFLINE INDICATOR
   ============================================================ */
#offline-bar{display:none;position:fixed;top:0;left:0;right:0;z-index:1000;
  background:#3a0a0a;border-bottom:1px solid #8b1a1a;color:#ff6b6b;
  font-family:var(--mono);font-size:.858rem;text-align:center;
  padding:.35rem 1rem;letter-spacing:.06em}
body.offline #offline-bar{display:block}


/* ============================================================
   TOAST NOTIFICATIONS
   ============================================================ */
#toast-stack{position:fixed;bottom:1.5rem;right:1.2rem;display:flex;
  flex-direction:column-reverse;gap:.45rem;z-index:1200;pointer-events:none;
  max-width:92vw}
.toast-item{background:#1a2438;border:1px solid var(--border2);border-radius:8px;
  padding:.55rem 1.2rem;font-family:var(--mono);font-size:.924rem;
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


/* ============================================================
   SHARED: empty-state stub panel (used by not-yet-loaded tabs)
   ============================================================ */
.stub-panel{display:flex;align-items:center;justify-content:center;
  min-height:200px;font-family:var(--mono);font-size:.836rem;
  color:#fff;letter-spacing:.1em;text-transform:uppercase;
  border:1px dashed var(--border);margin:.5rem 0;border-radius:5px}

::-webkit-scrollbar{width:4px}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}
.hidden{display:none}


/* ============================================================
   OVERVIEW TAB
   ============================================================ */
.ov-card{background:var(--surface);border:1px solid var(--border2);
  border-radius:5px;overflow:hidden;
  box-shadow:0 4px 20px rgba(0,0,0,.4);margin-bottom:.65rem}
.ov-card-hdr{background:#131c2d;border-bottom:1px solid var(--border);
  padding:.38rem .9rem;display:flex;align-items:center;
  justify-content:space-between}
.ov-card-title{font-family:var(--mono);font-size:.66rem;letter-spacing:.28em;
  text-transform:uppercase;color:#fff}

.ov-row{display:grid;
  grid-template-columns:10px 1fr 72px 90px 46px auto;
  align-items:center;gap:.45rem;
  padding:.42rem .9rem;
  border-top:1px solid var(--border);
  transition:background .1s}

.ov-hdr-status{width:72px}
.ov-hdr-port{width:90px}
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

.ov-name{font-family:var(--sans);font-size:.902rem;font-weight:700;
  color:var(--text-bright);overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;cursor:pointer;text-decoration:none}
.ov-name:hover{color:var(--teal);text-shadow:0 0 8px rgba(0,255,229,.5)}
.ov-name.ni{color:#fff;font-weight:normal;font-style:italic;cursor:default}
.ov-name.ni:hover{color:#fff;text-shadow:none}
.ov-state{font-family:var(--mono);font-size:.77rem;text-align:left}
.st-active{color:var(--green);text-shadow:0 0 6px rgba(0,255,176,.4)}
.st-failed{color:var(--red);  text-shadow:0 0 6px rgba(255,61,90,.4)}
.st-inactive{color:#fff}
.st-notinst{color:#fff;font-style:italic}
.st-unknown{color:var(--purple);font-style:italic}
.ov-port{font-family:var(--mono);font-size:.715rem;color:#fff;
  text-align:right;white-space:nowrap}
.ov-nr{font-family:var(--mono);font-size:.715rem;color:#fff;
  text-align:right;white-space:nowrap}
.ov-nr.nr-warn{color:var(--amber);text-shadow:0 0 6px rgba(255,208,64,.4)}

.pc-ok {font-family:var(--mono);font-size:.66rem;color:var(--green);
  text-shadow:0 0 4px rgba(0,255,176,.4);white-space:nowrap;text-align:center}
.pc-dup{font-family:var(--mono);font-size:.66rem;color:var(--red);
  text-shadow:0 0 4px rgba(255,61,90,.4);white-space:nowrap;
  text-align:center;cursor:default}

.pc-empty{display:block}

.ov-btns{display:flex;gap:.28rem;justify-content:flex-end;
  flex-shrink:0;flex-wrap:nowrap}

#ov-global-bar{position:sticky;bottom:0;background:var(--surface);
  border-top:1px solid var(--border2);padding:.45rem .9rem;
  display:flex;align-items:center;gap:.5rem}
#ov-global-lbl{font-family:var(--mono);font-size:.605rem;letter-spacing:.2em;
  text-transform:uppercase;color:#fff}

@media(max-width:600px){
  .ov-row{grid-template-columns:10px 1fr}
  .ov-state,.ov-port,.ov-nr,.pc-ok,.pc-dup,.pc-empty{display:none}
  .ov-btns{grid-column:1 / -1;justify-content:flex-start;margin-top:.3rem}
}


/* ============================================================
   SHARED: generic card component (.s3-card/-hdr/-title/-meta)
   Also reused by Tune, SD Card, M17, and Zello tabs.
   Followed below by SERVICES-tab-specific controls (.s3-controls,
   .s3-scope, .s3-filter, .s3-gen-row, .s3-state).
   ============================================================ */
.s3-card{background:var(--surface);border:1px solid var(--border2);
  border-radius:5px;overflow:hidden;
  box-shadow:0 4px 20px rgba(0,0,0,.4);margin-bottom:.65rem}
.s3-card-hdr{background:#131c2d;border-bottom:1px solid var(--border);
  padding:.38rem .9rem;display:flex;align-items:center;
  justify-content:space-between}
.s3-card-title{font-family:var(--mono);font-size:.66rem;letter-spacing:.28em;
  text-transform:uppercase;color:#fff}
.s3-card-meta{font-family:var(--mono);font-size:.66rem;color:#fff}

.s3-controls{display:flex;align-items:center;gap:.4rem;
  padding:.42rem .9rem;background:#131c2d;border-bottom:1px solid var(--border)}
.s3-scope{font-family:var(--mono);font-size:.77rem;font-weight:bold;
  letter-spacing:.05em;text-transform:uppercase;padding:.22rem .65rem;
  border-radius:3px;border:1px solid var(--border2);background:transparent;
  color:#fff;cursor:pointer;transition:all .14s}
.s3-scope.on{color:var(--teal);border-color:var(--teal);
  background:rgba(0,255,229,.07)}
.s3-scope:hover:not(.on){color:var(--text-bright);border-color:#fff}
.s3-filter{font-family:var(--mono);font-size:.858rem;padding:.25rem .55rem;
  background:var(--surface2);color:var(--text-bright);
  border:1px solid var(--border2);border-radius:3px;outline:none;
  flex:1;min-width:0;transition:border-color .15s}
.s3-filter:focus{border-color:var(--amber);box-shadow:0 0 6px rgba(255,208,64,.2)}
.s3-filter::placeholder{color:#fff}

.s3-gen-row{display:grid;grid-template-columns:10px 1fr 82px auto;
  align-items:center;gap:.55rem;padding:.38rem .9rem;
  border-top:1px solid var(--border);cursor:pointer;transition:background .1s}
.s3-gen-row:hover{background:var(--surface2)}
.s3-gen-name{font-family:var(--mono);font-size:.858rem;
  color:#fff;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.s3-state{font-family:var(--mono);font-size:.77rem}

.s3-gen-row2{display:contents}

@media(max-width:600px){
  .s3-gen-row{grid-template-columns:10px 1fr}
  .s3-gen-row2{
    display:flex; grid-column:1 / -1;
    align-items:center; justify-content:space-between;
    margin-top:.25rem;
  }
  .s3-gen-row2 > button{justify-self:start; width:max-content}
}


/* ============================================================
   SHARED: device detail side panel (dpanel — opens from Overview,
   Services, Ports, etc. to show one unit's detail/actions)
   ============================================================ */
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
  font-family:var(--mono);font-size:.77rem;color:#fff;
  cursor:pointer;padding:.1rem .45rem;
  border:1px solid var(--border2);border-radius:3px;transition:all .14s}
#dpanel-close:hover{color:var(--red);border-color:var(--red-dim)}
#dpanel-unit{font-family:var(--mono);font-size:1rem;
  color:var(--panel-accent);letter-spacing:.06em;
  margin-right:2.5rem;margin-bottom:.15rem;
  text-shadow:0 0 8px color-mix(in srgb,var(--panel-accent) 50%,transparent)}
#dpanel-desc{font-family:var(--sans);font-size:.836rem;
  color:#fff;margin-bottom:.42rem}
#dpanel-badges{display:flex;gap:.35rem;flex-wrap:wrap}
.dpbadge{font-family:var(--mono);font-size:.66rem;
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

.dpzone-lbl{font-family:var(--mono);font-size:.605rem;
  letter-spacing:.22em;text-transform:uppercase;color:#fff;
  padding:.42rem .9rem .28rem;background:#131c2d;
  border-top:1px solid var(--border)}
.dpzone-lbl:first-child{border-top:none}

.dpbtn-row{padding:.45rem .9rem;display:flex;flex-wrap:wrap;
  gap:.3rem;border-bottom:1px solid var(--border)}

#dpanel-output{margin:.55rem .9rem;background:#0a1020;
  border:1px solid var(--border);border-radius:3px;
  min-height:100px;max-height:220px;overflow-y:auto;
  padding:.5rem .7rem;font-family:var(--mono);
  font-size:.77rem;color:#fff;line-height:1.65}
#dpanel-output::-webkit-scrollbar{width:3px}
#dpanel-output::-webkit-scrollbar-thumb{background:var(--border2)}
.dp-out-ok  {color:var(--green); text-shadow:0 0 4px rgba(0,255,176,.3)}
.dp-out-fail{color:var(--red);   text-shadow:0 0 4px rgba(255,61,90,.3)}
.dp-out-warn{color:var(--amber); text-shadow:0 0 4px rgba(255,208,64,.3)}
.dp-out-dim {color:#fff}


/* ============================================================
   PORTS TAB
   ============================================================ */
.pt-controls{display:flex;align-items:center;gap:.4rem;
  padding:.42rem .9rem;background:#131c2d;border-bottom:1px solid var(--border)}
.pt-proto-btn{font-family:var(--mono);font-size:.77rem;font-weight:bold;
  letter-spacing:.05em;text-transform:uppercase;padding:.22rem .65rem;
  border-radius:3px;border:1px solid var(--border2);background:transparent;
  color:#fff;cursor:pointer;transition:all .14s}
.pt-proto-btn.on{color:var(--blue);border-color:var(--blue);
  background:rgba(34,212,255,.07)}
.pt-proto-btn:hover:not(.on){color:var(--text-bright);border-color:#fff}

.pt-legend{font-family:var(--mono);font-size:.66rem;color:#fff;
  padding:.35rem .9rem;background:#0e1622;border-bottom:1px solid var(--border)}

.dot-legend{display:flex;flex-wrap:wrap;gap:.55rem 1rem;
  font-family:var(--mono);font-size:.66rem;color:#fff;
  padding:.35rem .9rem;background:#0e1622;border-bottom:1px solid var(--border)}
.dot-legend-item{display:flex;align-items:center;gap:.32rem;white-space:nowrap}

.pt-table-hdr,.pt-row{display:grid;
  grid-template-columns:10px 70px 48px 1fr 58px 1fr auto;
  align-items:center;gap:.55rem;padding:.38rem .9rem;
  border-top:1px solid var(--border)}
.pt-table-hdr{background:#131c2d;border-top:none;
  font-family:var(--mono);font-size:.605rem;
  letter-spacing:.2em;text-transform:uppercase;color:#fff;cursor:default}
.pt-row{cursor:pointer;transition:background .1s}
.pt-row:hover{background:var(--surface2)}
.pt-port{font-family:var(--mono);font-size:.902rem;
  font-weight:bold;color:var(--text-bright)}
.pt-proto{font-family:var(--mono);font-size:.77rem}
.pt-proto.tcp{color:var(--blue)}.pt-proto.udp{color:var(--green)}
.pt-process{font-family:var(--mono);font-size:.836rem;color:var(--teal)}
.pt-pid{font-family:var(--mono);font-size:.715rem;color:#fff}
.pt-service{font-family:var(--mono);font-size:.77rem;
  color:var(--amber);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pt-service.unknown{color:#fff;font-style:italic}

@media(max-width:600px){
  .pt-table-hdr,.pt-row{grid-template-columns:10px 60px 40px 1fr}
  .pt-pid,.pt-service,.pc-ok,.pc-dup{display:none}
}


/* ============================================================
   FIREWALL TAB
   ============================================================ */
.fw-backend-bar{display:flex;align-items:center;gap:.7rem;
  padding:.38rem .9rem;background:#131c2d;
  border-bottom:1px solid var(--border);font-family:var(--mono);font-size:.836rem}
.fw-backend-lbl{color:#fff;font-size:.605rem;
  letter-spacing:.2em;text-transform:uppercase}
.fw-backend-val{color:var(--orange);font-weight:bold;
  text-shadow:0 0 6px rgba(255,170,34,.4)}
.fw-status-val{font-family:var(--mono);font-size:.715rem;color:#fff}
.fw-status-val.active{color:var(--green)}
.fw-status-val.inactive{color:var(--amber)}

.fw-table-hdr,.fw-row{display:grid;
  grid-template-columns:44px 1fr 82px 1fr 1fr 32px;
  align-items:center;gap:.5rem;
  padding:.38rem .9rem;border-top:1px solid var(--border)}
.fw-table-hdr{background:#131c2d;border-top:none;
  font-family:var(--mono);font-size:.605rem;
  letter-spacing:.2em;text-transform:uppercase;color:#fff;cursor:default}
.fw-row{cursor:pointer;transition:background .1s}
.fw-row:hover{background:var(--surface2)}
.fw-num{font-family:var(--mono);font-size:.77rem;color:#fff;text-align:right}
.fw-to{font-family:var(--mono);font-size:.836rem;color:var(--text-bright)}
.fw-action{font-family:var(--mono);font-size:.77rem;font-weight:bold;
  text-align:center;padding:.1rem .35rem;border-radius:3px;border:1px solid}
.fw-action.ALLOW{color:var(--green);border-color:var(--green-dim);
  background:rgba(0,255,176,.07)}
.fw-action.DENY,.fw-action.REJECT{color:var(--red);border-color:var(--red-dim);
  background:rgba(255,61,90,.07)}
.fw-action.LIMIT{color:var(--amber);border-color:var(--amber-dim);
  background:rgba(255,208,64,.07)}
.fw-from{font-family:var(--mono);font-size:.836rem;color:#fff}
.fw-svc{font-family:var(--mono);font-size:.77rem;color:var(--amber);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fw-svc.unknown{color:#fff;font-style:italic}
.fw-del{font-family:var(--mono);font-size:.715rem;color:#fff;
  cursor:pointer;text-align:center;padding:.1rem .3rem;
  border:1px solid var(--border);border-radius:3px;transition:all .14s}
.fw-del:hover{color:var(--red);border-color:var(--red-dim)}

.fw-add-bar{display:flex;align-items:center;gap:.4rem;flex-wrap:wrap;
  padding:.5rem .9rem;background:#131c2d;
  border-top:2px solid var(--border2)}
.fw-add-lbl{font-family:var(--mono);font-size:.605rem;
  letter-spacing:.2em;text-transform:uppercase;color:#fff;white-space:nowrap}
.fw-add-inp{font-family:var(--mono);font-size:.836rem;padding:.25rem .5rem;
  background:var(--surface2);color:var(--text-bright);
  border:1px solid var(--border2);border-radius:3px;outline:none;
  width:80px;transition:border-color .15s}
.fw-add-inp:focus{border-color:var(--amber);box-shadow:0 0 6px rgba(255,208,64,.2)}
.fw-add-inp::placeholder{color:#fff}
.fw-add-sel{font-family:var(--mono);font-size:.836rem;padding:.25rem .45rem;
  background:var(--surface2);color:var(--text-bright);
  border:1px solid var(--border2);border-radius:3px;
  cursor:pointer;outline:none}
.fw-add-sel option{background:var(--surface2)}

.fw-summary-line{padding:.5rem .9rem;background:#0e1626;
  border-bottom:1px solid var(--border);font-family:var(--mono);
  font-size:.77rem;color:#fff;display:flex;align-items:center;gap:.45rem}
.fw-summary-dot{font-size:.9rem;line-height:1}

.fw-zone-details{padding:.5rem .9rem .6rem;background:#0e1626;
  border-bottom:1px solid var(--border);font-family:var(--mono);
  font-size:.77rem;color:#fff;display:flex;flex-direction:column;gap:.25rem}
.fw-zone-row{display:flex;gap:.5rem;align-items:baseline}
.fw-zone-lbl{color:#fff;opacity:.6;min-width:110px;
  text-transform:uppercase;font-size:.605rem;letter-spacing:.15em}
.fw-zone-val{color:var(--text-bright)}

.fw-raw-toggle-hdr{display:flex;align-items:center;justify-content:space-between;
  padding:.4rem .9rem;cursor:pointer;user-select:none;
  background:#131c2d;border-top:1px solid var(--border)}
.fw-raw-toggle-hdr:hover{background:#182030}
.fw-raw-toggle-title{font-family:var(--mono);font-size:.66rem;
  letter-spacing:.15em;text-transform:uppercase;color:#fff}
.fw-raw-toggle-chevron{font-family:var(--mono);font-size:.77rem;color:#fff;
  transition:transform .2s}
.fw-raw-toggle-hdr.open .fw-raw-toggle-chevron{transform:rotate(90deg)}
.fw-raw-toggle-body{display:none}
.fw-raw-toggle-body.open{display:block}

.fw-raw-btns{display:flex;justify-content:flex-end;
  margin:.6rem .9rem -.2rem;gap:.4rem}
.fw-raw-pre{margin:.6rem .9rem;background:#0a1020;
  border:1px solid var(--border);border-radius:3px;
  padding:.6rem .8rem;font-family:var(--mono);font-size:.77rem;
  color:#fff;line-height:1.6;white-space:pre;overflow-x:auto;
  max-height:420px;overflow-y:auto}
.fw-raw-pre::-webkit-scrollbar{width:4px;height:4px}
.fw-raw-pre::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}

@media(max-width:600px){
  .fw-table-hdr,.fw-row{grid-template-columns:36px 1fr 64px 32px}
  .fw-from,.fw-svc{display:none}
  .fw-add-bar{flex-direction:column;align-items:stretch}
}


/* ============================================================
   JOURNAL TAB (service list)
   ============================================================ */
.jl-table-hdr,.jl-row{display:grid;grid-template-columns:10px 1fr 82px auto;
  align-items:center;gap:.55rem;
  padding:.42rem .9rem;border-top:1px solid var(--border)}
.jl-table-hdr{background:#131c2d;border-top:none;
  font-family:var(--mono);font-size:.605rem;
  letter-spacing:.2em;text-transform:uppercase;color:#fff;cursor:default}
.jl-row{cursor:pointer;transition:background .1s;user-select:none}
.jl-row:hover{background:var(--surface2)}
.jl-name{font-family:var(--sans);font-size:.902rem;font-weight:700;
  color:var(--text-bright);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.jl-state{font-family:var(--mono);font-size:.77rem}
.jl-btn{font-family:var(--mono);font-size:.715rem;color:var(--purple);
  border:1px solid var(--purple-dim);border-radius:3px;
  padding:.15rem .45rem;background:transparent;cursor:pointer;
  white-space:nowrap;transition:all .14s}
.jl-btn:hover{filter:brightness(1.6)}


/* ============================================================
   JOURNAL LOG POPUP / MODAL (jp — shared component: opened from the
   Journal tab directly, and from Ports/Firewall tabs via ptViewJournal())
   ============================================================ */
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
#jp-title{font-family:var(--mono);font-size:.858rem;color:var(--purple);
  letter-spacing:.08em;text-shadow:0 0 8px rgba(212,102,255,.4)}
#jp-ctrl{display:flex;align-items:center;gap:.4rem}
#jp-close{font-family:var(--mono);font-size:.858rem;color:#fff;
  cursor:pointer;padding:.15rem .55rem;border:1px solid var(--border2);
  border-radius:3px;transition:all .14s}
#jp-close:hover{color:var(--red);border-color:var(--red-dim)}

#jp-toolbar{display:flex;align-items:center;gap:.4rem;
  padding:.35rem 1rem;background:#131c2d;
  border-bottom:1px solid var(--border);flex-shrink:0}
#jp-grep{font-family:var(--mono);font-size:.836rem;padding:.25rem .5rem;
  background:var(--surface2);color:var(--text-bright);
  border:1px solid var(--border2);border-radius:3px;
  outline:none;width:180px;transition:border-color .15s}
#jp-grep:focus{border-color:var(--amber);box-shadow:0 0 6px rgba(255,208,64,.2)}
#jp-grep::placeholder{color:#fff}
.jp-lines-btn{font-family:var(--mono);font-size:.77rem;font-weight:bold;
  letter-spacing:.05em;padding:.22rem .65rem;border-radius:3px;
  border:1px solid var(--border2);background:transparent;
  color:#fff;cursor:pointer;transition:all .14s}
.jp-lines-btn.on{color:var(--teal);border-color:var(--teal);
  background:rgba(0,255,229,.07)}
.jp-lines-btn:hover:not(.on){color:var(--text-bright);border-color:#fff}

#jp-body{flex:1;overflow-y:auto;padding:.7rem 1rem;
  font-family:var(--mono);font-size:.792rem;color:#fff;
  line-height:1.75;background:#0a1020;white-space:pre-wrap;word-break:break-all}
#jp-body::-webkit-scrollbar{width:4px}
#jp-body::-webkit-scrollbar-thumb{background:var(--border2)}
.jp-err{color:var(--red)}.jp-warn{color:var(--amber)}
.jp-ok{color:var(--green)}.jp-dim{color:#fff}
.jp-ts{color:#fff}


/* ============================================================
   EDIT TAB — config fields
   ============================================================ */
.ed-section{padding:.65rem .9rem .5rem;
  border-bottom:2px solid var(--border);background:#111828}
.ed-section-title{font-family:var(--mono);font-size:.66rem;
  letter-spacing:.28em;text-transform:uppercase;color:#fff;
  margin-bottom:.45rem}
.ed-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
  gap:.5rem .9rem;margin-top:.35rem}

.ed-field{display:flex;flex-direction:column;gap:.2rem}
.ed-field:hover{background:rgba(255,255,255,.02);border-radius:3px}
.ed-lbl{font-family:var(--mono);font-size:.66rem;
  letter-spacing:.18em;text-transform:uppercase;color:#fff}
.ed-inp{font-family:var(--mono);font-size:.946rem;padding:.3rem .48rem;
  background:var(--surface2);color:var(--text-bright);
  border:1px solid var(--border2);border-radius:3px;width:100%;
  outline:none;transition:border-color .15s}
.ed-inp:focus{border-color:var(--amber);box-shadow:0 0 6px rgba(255,208,64,.2)}
.ed-inp.invalid{border-color:var(--red);box-shadow:0 0 6px rgba(255,61,90,.2)}
.ed-err{font-family:var(--mono);font-size:.66rem;color:var(--red);
  margin-top:.15rem;display:none}
.ed-err.show{display:block}

.ed-textarea{font-family:var(--mono);font-size:.792rem;
  padding:.45rem .55rem;background:var(--surface2);
  color:var(--text-bright);border:1px solid var(--border2);
  border-radius:3px;width:100%;min-height:220px;resize:vertical;
  outline:none;line-height:1.6;transition:border-color .15s}
.ed-textarea:focus{border-color:var(--amber);
  box-shadow:0 0 6px rgba(255,208,64,.2)}
.ed-count{font-family:var(--mono);font-size:.836rem;
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


/* ============================================================
   EDIT TAB — full config file viewer modal (allconf)
   ============================================================ */
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
#allconf-title{font-family:var(--mono);font-size:.858rem;
  color:var(--teal);letter-spacing:.08em;
  text-shadow:0 0 8px rgba(0,255,229,.4)}
#allconf-info{font-family:var(--mono);font-size:.715rem;color:#fff;
  padding:.38rem 1rem;background:#131c2d;
  border-bottom:1px solid var(--border);flex-shrink:0;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#allconf-close{font-family:var(--mono);font-size:.858rem;color:#fff;
  cursor:pointer;padding:.15rem .55rem;border:1px solid var(--border2);
  border-radius:3px;transition:all .14s}
#allconf-close:hover{color:var(--red);border-color:var(--red-dim)}
#allconf-textarea{flex:1;background:#0a1020;color:#c8d8e8;
  font-family:var(--mono);font-size:.836rem;line-height:1.65;
  border:none;outline:none;padding:.8rem 1rem;
  resize:none;tab-size:4;white-space:pre;overflow:auto;
  min-height:300px}
#allconf-textarea::-webkit-scrollbar{width:4px;height:4px}
#allconf-textarea::-webkit-scrollbar-thumb{background:var(--border2)}


/* ---- Edit tab: collapsible sections (e.g. Pinned Services) ---- */
.ed-collapsible-hdr{display:flex;align-items:center;justify-content:space-between;
  cursor:pointer;padding:.65rem .9rem .5rem;
  background:#111828;border-bottom:2px solid var(--border);
  user-select:none;transition:background .14s}
.ed-collapsible-hdr:hover{background:#182030}
.ed-collapsible-title{font-family:var(--mono);font-size:.66rem;
  letter-spacing:.28em;text-transform:uppercase;color:#fff}
.ed-collapsible-chevron{font-family:var(--mono);font-size:.836rem;
  color:#fff;transition:transform .2s}
.ed-collapsible-hdr.open .ed-collapsible-chevron{transform:rotate(90deg)}
.ed-collapsible-body{overflow:hidden;transition:max-height .25s ease}
.ed-collapsible-body.collapsed{max-height:0 !important}


/* ---- Edit tab: per-tab visibility checkboxes ---- */
.tab-vis-row{display:flex;flex-wrap:wrap;gap:.35rem .9rem;padding:.3rem 0 .15rem}
.tab-vis-lbl{font-family:var(--mono);font-size:.78rem;color:#fff;
  display:inline-flex;align-items:center;gap:.32rem;cursor:pointer;
  user-select:none;white-space:nowrap}
.tab-vis-lbl input[type=checkbox]{accent-color:var(--amber);
  width:14px;height:14px;cursor:pointer}
.tab-vis-lbl.locked{opacity:.55;cursor:default}
.tab-vis-lbl.locked input[type=checkbox]{cursor:default}
.ed-hint{font-family:var(--mono);font-size:.66rem;
  color:#fff;line-height:1.5;margin-top:.15rem}
.ed-hint.live{color:#fff}  

@media(max-width:600px){
  .ed-grid{grid-template-columns:1fr}
}


/* ============================================================
   SHARED: generic confirm/alert modal
   ============================================================ */
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


/* ============================================================
   ASL-DVS TAB
   ============================================================ */
.ast-row{display:grid;grid-template-columns:1fr auto;
  align-items:center;gap:.55rem;padding:.42rem .9rem;
  border-top:1px solid var(--border);
  cursor:pointer;transition:background .1s;user-select:none}
.ast-row:hover{background:var(--surface2)}
.ast-name{font-family:var(--mono);font-size:.902rem;
  color:var(--teal);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

.ast-port-line{font-family:var(--mono);font-size:.715rem;
  color:#fff;padding:.1rem .9rem .1rem 2.2rem;
  border-top:1px solid rgba(255,255,255,.03);
  white-space:pre;overflow:hidden;text-overflow:ellipsis;flex:1}
.ast-port-line:first-child{border-top:none}
.ast-port-lines{border-top:1px solid var(--border);background:#0d1520}
.ast-section-lbl{font-family:var(--mono);font-size:.605rem;
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
.ast-check-title{font-family:var(--mono);font-size:.715rem;color:#fff}
.ast-check-value{font-family:var(--mono);font-size:.77rem;
  color:var(--text-bright);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ast-check-pass{font-family:var(--mono);font-size:.66rem;
  color:var(--green);text-align:center;
  text-shadow:0 0 4px rgba(0,255,176,.4)}
.ast-check-fail{font-family:var(--mono);font-size:.66rem;
  color:var(--red);text-align:center;
  text-shadow:0 0 4px rgba(255,61,90,.4)}
.ast-check-none{font-family:var(--mono);font-size:.66rem;
  color:var(--amber);text-align:center;
  text-shadow:0 0 4px rgba(255,208,64,.3)}
.ast-check-info{font-family:var(--mono);font-size:.66rem;
  color:#fff;text-align:center}
.ast-check-warn{font-family:var(--mono);font-size:.66rem;
  color:var(--orange);text-align:center;
  text-shadow:0 0 4px rgba(255,170,34,.35)}

.ast-toggle{font-family:var(--mono);font-size:.605rem;
  background:none;border:1px solid var(--border2);border-radius:3px;
  color:#fff;padding:.1rem .35rem;cursor:pointer;
  transition:all .14s;flex-shrink:0}
.ast-toggle:hover{color:var(--text-bright);border-color:#fff}

.ast-check-note{font-family:var(--mono);font-size:.66rem;
  color:#fff;padding:.08rem .9rem .14rem 2.2rem}
.ast-check-link{color:var(--teal);text-decoration:none}
.ast-check-link:hover{text-decoration:underline}


/* ============================================================
   HARDWARE TAB
   ============================================================ */
.hw-dev-row-hdr{display:flex;align-items:center;gap:.55rem;
  padding:.45rem .9rem;border-top:1px solid var(--border);
  background:var(--surface)}

.hw-section-lbl{font-family:var(--mono);font-size:.605rem;
  letter-spacing:.22em;text-transform:uppercase;color:#fff;
  padding:.35rem .9rem .28rem;background:#131c2d;
  border-top:1px solid var(--border);border-bottom:1px solid var(--border)}

.hw-dev-info{padding:.55rem .9rem;border-bottom:1px solid var(--border);
  font-family:var(--mono);font-size:.836rem;line-height:2;background:#0f1825}
.hw-dev-row{display:flex;align-items:baseline;gap:.6rem}
.hw-dev-label{color:#fff;font-size:.605rem;letter-spacing:.15em;
  text-transform:uppercase;min-width:80px;flex-shrink:0}
.hw-dev-val{color:var(--teal)}
.hw-dev-val.sym{color:var(--green)}
.hw-dev-val.dim{color:#fff}

.hw-check-row{display:grid;grid-template-columns:28px 1fr auto;
  align-items:center;gap:.5rem;
  padding:.38rem .9rem;border-top:1px solid var(--border);
  font-family:var(--mono);font-size:.836rem}
.hw-check-row:first-of-type{border-top:none}
.hw-check-icon{font-size:1rem;text-align:center;width:20px;flex-shrink:0}
.hw-check-icon.ok{color:var(--green);text-shadow:0 0 6px rgba(0,255,176,.5)}
.hw-check-icon.fail{color:var(--red);text-shadow:0 0 6px rgba(255,61,90,.5)}
.hw-check-icon.warn{color:var(--amber);text-shadow:0 0 6px rgba(255,208,64,.5)}
.hw-check-icon.pend{color:#fff}
.hw-check-label{color:var(--text-bright);font-size:.836rem}
.hw-check-detail{font-size:.715rem;color:#fff;
  text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hw-check-detail.ok{color:#007a50}
.hw-check-detail.warn{color:#7a5800}
.hw-check-detail.fail{color:#7a2030}

.hw-compat-section{padding:.45rem .9rem;background:#0b1420;
  border-top:1px solid var(--border)}
.hw-compat-row{display:flex;align-items:center;gap:.7rem;
  padding:.28rem 0;font-family:var(--mono);font-size:.836rem}
.hw-compat-label{color:#fff;font-size:.715rem;letter-spacing:.12em;
  text-transform:uppercase;min-width:90px;flex-shrink:0}
.hw-compat-ok{color:var(--green);text-shadow:0 0 6px rgba(0,255,176,.4)}
.hw-compat-fail{color:var(--red);font-size:.77rem}
.hw-compat-warn{color:var(--amber);font-size:.77rem}
.hw-compat-reason{color:#fff;font-size:.715rem;margin-left:.3rem}

.hw-card-footer{display:flex;align-items:center;gap:.5rem;
  padding:.4rem .9rem;background:#111828;
  border-top:2px solid var(--border2)}

.hw-multi-warn{display:flex;align-items:center;gap:.55rem;
  padding:.35rem .9rem;background:#1a1200;
  border-bottom:1px solid var(--amber-dim);
  font-family:var(--mono);font-size:.77rem;color:var(--amber)}

.hw-gear-btn{font-family:var(--mono);font-size:.77rem;color:#fff;
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
.hw-action-sub-title{font-family:var(--mono);font-size:.605rem;
  letter-spacing:.2em;text-transform:uppercase;
  color:#fff;margin-bottom:.4rem}
.hw-action-row{display:flex;align-items:center;gap:.4rem;
  flex-wrap:wrap;margin-top:.35rem}
.hw-action-inp{font-family:var(--mono);font-size:.836rem;
  padding:.25rem .5rem;background:var(--surface2);
  color:var(--text-bright);border:1px solid var(--border2);
  border-radius:3px;outline:none;width:160px;transition:border-color .15s}
.hw-action-inp:focus{border-color:var(--teal);
  box-shadow:0 0 6px rgba(0,255,229,.2)}
.hw-action-inp::placeholder{color:#fff}
.hw-action-sel{font-family:var(--mono);font-size:.836rem;
  padding:.25rem .45rem;background:var(--surface2);
  color:var(--text-bright);border:1px solid var(--border2);
  border-radius:3px;cursor:pointer;outline:none}
.hw-action-sel option{background:var(--surface2)}
.hw-action-note{font-family:var(--mono);font-size:.66rem;
  color:#fff;margin-top:.4rem;line-height:1.6}
.hw-symlink-hint{font-family:var(--mono);font-size:.66rem;
  color:#fff;margin-top:.25rem}
.hw-symlink-hint span{color:var(--teal)}

.hw-ping-result{font-family:var(--mono);font-size:.77rem;
  margin-left:.5rem;padding:.2rem .5rem;border-radius:3px;
  border:1px solid var(--border2);color:#fff;display:none}
.hw-ping-result.ok{color:var(--green);border-color:var(--green-dim);
  background:rgba(0,255,176,.06);display:inline-block}
.hw-ping-result.fail{color:var(--red);border-color:var(--red-dim);
  background:rgba(255,61,90,.06);display:inline-block}

.hw-reset-chip-btn{
  font-family:var(--mono);font-size:.8rem;font-weight:700;
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

.hw-reset-status{font-family:var(--mono);font-size:.72rem;
  margin-left:.55rem;padding:.2rem .5rem;border-radius:3px;
  border:1px solid var(--border2);color:#fff;display:none}
.hw-reset-status.ok{color:var(--green);border-color:var(--green-dim);
  background:rgba(0,255,176,.06);display:inline-block}
.hw-reset-status.warn{color:var(--amber);border-color:var(--amber-dim);
  background:rgba(255,208,64,.06);display:inline-block}
.hw-reset-status.fail{color:var(--red);border-color:var(--red-dim);
  background:rgba(255,61,90,.06);display:inline-block}

.hw-badge{font-family:var(--mono);font-size:.605rem;letter-spacing:.1em;
  padding:.1rem .45rem;border-radius:3px;border:1px solid;
  flex-shrink:0;white-space:nowrap}
.hw-badge-ambe{color:var(--teal);border-color:var(--teal-dim);
  background:rgba(0,255,229,.07)}
.hw-badge-serial{color:var(--amber);border-color:var(--amber-dim);
  background:rgba(255,208,64,.07)}
.hw-badge-audio{color:var(--blue);border-color:var(--blue-dim);
  background:rgba(34,212,255,.07)}
.hw-badge-watchdog{color:#fff;border-color:var(--border2)}

.hw-compat-note{font-family:var(--mono);font-size:.66rem;color:#fff;
  padding:.25rem 0;border-top:1px solid var(--border);margin-top:.3rem}

.hw-remove-btn{display:none}
.hw-remove-btn.visible{display:inline-block}

.hw-source-tag{font-family:var(--mono);font-size:.605rem;
  color:#fff;letter-spacing:.1em}
@media(max-width:600px){
  .hw-dev-label{min-width:60px}
  .hw-compat-label{min-width:70px}
  .hw-check-detail{display:none}
  .hw-action-inp{width:130px}
}


/* ============================================================
   SHARED: universal file editor modal (uf). Opened via
   openUnitFileEditor() from Overview and Services (systemd unit
   files), and populated directly -- bypassing openUnitFileEditor()
   entirely, same pattern as Ports/Firewall do with the dpanel -- by
   ASL-DVS's four config-file editors (openDvsEditor/
   openAppConfEditor/openAllmon3Editor/openAstEditor) for its
   Asterisk/DVSwitch/Allmon3/app-config files. Save is dispatched via
   ufSave(), which delegates to the original _ufSaveOrig() for plain
   unit files -- see the JS boundary comments for where each piece
   actually lives (this component is split across several widely
   separated locations in the script).
   ============================================================ */
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
#uf-title{font-family:var(--mono);font-size:.858rem;
  color:var(--teal);letter-spacing:.08em;
  text-shadow:0 0 8px rgba(0,255,229,.4)}
#uf-hdr-right{display:flex;align-items:center;gap:.4rem}
#uf-close{font-family:var(--mono);font-size:.858rem;color:#fff;
  cursor:pointer;padding:.15rem .55rem;border:1px solid var(--border2);
  border-radius:3px;transition:all .14s}
#uf-close:hover{color:var(--red);border-color:var(--red-dim)}

#uf-promoted-bar{display:none;background:rgba(255,208,64,.08);
  border-bottom:1px solid var(--amber-dim);
  padding:.35rem 1rem;font-family:var(--mono);font-size:.715rem;
  color:var(--amber);flex-shrink:0;position:sticky;top:2.5rem;z-index:500}
#uf-promoted-bar.show{display:block}

#uf-toolbar{display:flex;align-items:center;gap:.4rem;
  padding:.38rem 1rem;background:#131c2d;
  border-bottom:1px solid var(--border);flex-shrink:0;
  position:sticky;top:2.5rem;z-index:500}
#uf-path{font-family:var(--mono);font-size:.715rem;
  color:#fff;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#uf-status{font-family:var(--mono);font-size:.77rem;color:#fff}

#uf-textarea{flex:1;background:#0a1020;color:#c8d8e8;
  font-family:var(--mono);font-size:.836rem;line-height:1.65;
  border:none;outline:none;padding:3.5rem 1rem .8rem 1rem;
  resize:none;tab-size:4;white-space:pre;overflow:auto;
  min-height:0}
#uf-textarea::-webkit-scrollbar{width:4px;height:4px}
#uf-textarea::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}


/* ============================================================
   DVSM TAB
   (.dvsm-accent/.dvsm-card-title/.dvsm-card-sub also reused by
   the STFU, M17, and Zello tabs for their card headers)
   ============================================================ */
.dvsm-tab-hdr{display:flex;align-items:center;justify-content:space-between;
  margin-bottom:.75rem;padding:.1rem 0}
.dvsm-tab-title{font-family:var(--mono);font-size:.77rem;letter-spacing:.22em;
  text-transform:uppercase;color:#fff}
.dvsm-tab-hdr-right{display:flex;align-items:center;gap:.55rem}
.dvsm-node-ip-lbl{font-family:var(--mono);font-size:.66rem;color:#fff}

.dvsm-grid{display:grid;grid-template-columns:1fr 1fr;gap:.65rem;margin-bottom:.65rem}
@media(max-width:800px){.dvsm-grid{grid-template-columns:1fr}}

.dvsm-accent{width:3px;height:1.15rem;border-radius:2px;flex-shrink:0}

.dvsm-card-title{font-family:var(--mono);font-size:.836rem;font-weight:bold;
  letter-spacing:.06em;text-transform:uppercase}
.dvsm-card-sub{font-family:var(--mono);font-size:.66rem;color:#fff;
  letter-spacing:.1em;margin-top:.06rem}

.dvsm-fields{width:100%;border-collapse:collapse}
.dvsm-fields tr{border-top:1px solid rgba(255,255,255,.04)}
.dvsm-fields tr:first-child{border-top:none}
.dvsm-fields td{padding:.28rem .9rem;vertical-align:middle}
.dvsm-lbl{font-family:var(--mono);font-size:.715rem;color:#fff;
  letter-spacing:.1em;text-transform:uppercase;width:110px;white-space:nowrap}

.dvsm-val-cell{word-break:break-word;min-width:0}
.dvsm-val{font-family:var(--mono);font-size:.858rem;color:var(--text-bright)}
.dvsm-val.masked{letter-spacing:.14em;color:#fff}
.dvsm-val.placeholder{color:#fff;font-style:italic}
.dvsm-actions{text-align:right;width:58px;white-space:nowrap}

.dvsm-copy,.dvsm-eye{font-family:var(--mono);font-size:.66rem;
  padding:.1rem .35rem;border-radius:2px;
  border:1px solid var(--border);background:transparent;
  color:#fff;cursor:pointer;transition:all .12s;margin-left:2px}
.dvsm-copy:hover{color:var(--teal);border-color:var(--teal-dim)}
.dvsm-eye:hover{color:var(--amber);border-color:var(--amber-dim)}
.dvsm-copy.copied{color:var(--green);border-color:var(--green-dim)}
.dvsm-eye.revealed{color:var(--amber);border-color:var(--amber-dim)}

.dvsm-note{background:#0a1220;border-top:1px solid rgba(255,208,64,.14);
  padding:.32rem .9rem;font-family:var(--mono);font-size:.715rem;line-height:1.5}
.dvsm-note.warn{color:var(--amber);border-top-color:rgba(255,208,64,.14)}
.dvsm-note.info{color:var(--teal);border-top-color:rgba(0,255,229,.12)}
.dvsm-note.err{color:var(--red);border-top-color:rgba(255,61,90,.12)}
.dvsm-note.src{color:#fff;font-size:.66rem;
  border-top-color:rgba(255,255,255,.05)}

.dvsm-sec-lbl{display:block;font-family:var(--mono);font-size:.605rem;
  letter-spacing:.2em;text-transform:uppercase;color:#fff;
  padding:.3rem .9rem .18rem;background:#0a1220;
  border-top:1px solid var(--border)}
.dvsm-sec-lbl:first-child{border-top:none}

.dvsm-compat-tbl{width:100%;border-collapse:collapse}
.dvsm-compat-tbl tr{border-top:1px solid rgba(255,255,255,.04)}
.dvsm-compat-tbl tr:first-child{border-top:none}
.dvsm-compat-tbl td{padding:.3rem .9rem;vertical-align:middle;
  font-family:var(--mono);font-size:.792rem}
.dvsm-ct-key{color:var(--blue);width:230px}

.dvsm-ct-enables{color:#fff}
.dvsm-ct-badge{text-align:right;width:58px}

.dvsm-ct-fix-row{border-top:none}
.dvsm-ct-fix{color:#fff;font-size:.66rem;
  padding:.05rem .9rem .3rem 2.5rem;border-top:none!important}


/* ============================================================
   STFU TAB
   (.stfu-editor-wrap, .stfu-sample-*, .stfu-code also reused by
   the M17 and Zello tabs for their bridge-config editor blocks)
   ============================================================ */
.stfu-tab-hdr{display:flex;align-items:center;justify-content:space-between;
  margin-bottom:.75rem;padding:.1rem 0}
.stfu-tab-title{font-family:var(--mono);font-size:.77rem;letter-spacing:.22em;
  text-transform:uppercase;color:#fff}

.stfu-bm-bar{display:flex;align-items:center;justify-content:space-between;
  padding:.42rem .9rem;
  background:linear-gradient(90deg,rgba(0,191,255,.06),rgba(0,191,255,.03));
  border-bottom:1px solid rgba(0,191,255,.15)}
.stfu-bm-bar-left{display:flex;align-items:center;gap:.55rem}
.stfu-bm-label{font-family:var(--mono);font-size:.77rem;
  color:#fff;letter-spacing:.06em}
.stfu-bm-link{font-family:var(--mono);font-size:.792rem;color:var(--sky);
  text-decoration:none;letter-spacing:.04em;
  text-shadow:0 0 8px rgba(0,191,255,.4);transition:all .15s}
.stfu-bm-link:hover{color:#fff;text-shadow:0 0 14px rgba(0,191,255,.9)}
.stfu-bm-pill{font-family:var(--mono);font-size:.605rem;letter-spacing:.14em;
  text-transform:uppercase;padding:.1rem .42rem;border-radius:2px;
  border:1px solid var(--sky-dim);color:var(--sky);
  background:rgba(0,191,255,.07)}

.stfu-sample-hdr{padding:.38rem .9rem;display:flex;align-items:center;
  justify-content:space-between;border-bottom:1px solid var(--border);
  background:#131c2d}
.stfu-sample-title{font-family:var(--mono);font-size:.77rem;color:#fff;
  letter-spacing:.12em;text-transform:uppercase}
.stfu-sample-btns{display:flex;gap:.4rem;align-items:center}

.stfu-code{font-family:var(--mono);font-size:.836rem;line-height:1.7;
  color:#c8d8e8;padding:.7rem .9rem;background:#080e18;
  margin:0;white-space:pre;overflow-x:auto;display:block}
.stfu-ini-section{color:var(--sky)}
.stfu-ini-key{color:var(--teal)}
.stfu-ini-ph{color:#fff;font-style:italic}   

.stfu-editor-wrap{overflow:hidden;transition:max-height .3s ease;max-height:0}
.stfu-editor-wrap.open{max-height:600px}
#stfu-textarea{width:100%;background:#0a1020;color:#c8d8e8;
  font-family:var(--mono);font-size:.836rem;line-height:1.65;
  border:none;outline:none;padding:.8rem 1rem;
  resize:none;tab-size:4;white-space:pre;overflow:auto;
  min-height:260px;display:block}
.stfu-editor-bar{display:flex;align-items:center;gap:.4rem;
  padding:.38rem .9rem;background:#131c2d;border-top:1px solid var(--border)}


/* ============================================================
   HARDWARE TAB (continued — power/diagnostics section; see also
   the main Hardware section earlier in this file)
   ============================================================ */
.hw-pwr-tbl{width:100%;border-collapse:collapse}
.hw-pwr-tbl tr{border-top:1px solid rgba(255,255,255,.04)}
.hw-pwr-tbl tr:first-child{border-top:none}
.hw-pwr-tbl td{padding:.28rem .9rem;vertical-align:middle;
  font-family:var(--mono);font-size:.836rem}
.hw-pwr-lbl{color:#fff;font-size:.715rem;letter-spacing:.1em;
  text-transform:uppercase;width:140px;white-space:nowrap}
.hw-pwr-val{color:var(--text-bright)}
.hw-pwr-val.ok{color:var(--green);text-shadow:0 0 6px rgba(0,255,176,.35)}
.hw-pwr-val.warn{color:var(--amber)}
.hw-pwr-val.hot{color:var(--red);text-shadow:0 0 6px rgba(255,61,90,.35)}
.hw-pwr-val.dim{color:#fff;font-style:italic}
.hw-pwr-note{font-size:.66rem;color:#fff;
  display:block;margin-top:.08rem;line-height:1.4}

.hw-pwr-flags{display:flex;flex-wrap:wrap;gap:.25rem .5rem;
  padding:.32rem .9rem .42rem;background:#080e18;
  border-top:1px solid var(--border)}
.hw-pwr-flag{font-family:var(--mono);font-size:.66rem;
  padding:.08rem .38rem;border-radius:2px;border:1px solid;white-space:nowrap}
.hw-pwr-flag.set-now{color:var(--red);border-color:var(--red-dim);
  background:rgba(255,61,90,.08)}
.hw-pwr-flag.set-ever{color:var(--amber);border-color:var(--amber-dim);
  background:rgba(255,208,64,.06)}
.hw-pwr-flag.clear{color:#2a4060;border-color:#1a2a40}

.hw-diag-pre{font-family:var(--mono);font-size:.715rem;line-height:1.5;
  color:var(--text);background:#080e18;padding:.6rem .9rem;margin:0;
  overflow-x:auto;white-space:pre;border-top:1px solid var(--border);
  max-height:340px;overflow-y:auto}
.hw-diag-toggle{padding:.18rem .5rem;font-size:.66rem;letter-spacing:.06em}
.hw-diag-toggle.active{color:var(--teal);border-color:var(--teal);
  background:rgba(0,255,229,.08)}
.hw-diag-note{font-family:var(--sans);font-size:.715rem;color:#fff;
  padding:.35rem .9rem;border-top:1px solid var(--border);line-height:1.5}
.hw-usb-badge{font-family:var(--mono);font-size:.605rem;padding:.04rem .32rem;
  border-radius:2px;border:1px solid;margin-left:.4rem;white-space:nowrap;
  vertical-align:middle}
.hw-usb-badge.ambe{color:var(--green);border-color:var(--green-dim)}
.hw-usb-badge.ftdi{color:var(--amber);border-color:var(--amber-dim)}

</style>
</head>
<body>

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

<!-- Global emergency bar (visible on every tab). Its button, plus
     the Reboot/Shutdown buttons in the command bar further down,
     call postAction() -- a small shared POST+confirm+toast wrapper
     physically homed at the tail of the Edit tab's script section
     despite having nothing to do with Edit itself. -->
<div id="emg-bar">
  <button class="btn btn-red btn-sm" id="btn-emg"
    onclick="postAction('/api/svc','emergency_restart',this,'⚡ Emergency Restart — stop and restart ALL managed services?')"
    title="Stops and restarts all ASL-DVS managed services immediately">
    ⚡ Emergency Restart
  </button>
  <a id="lnk-dashboard" class="lnk-dashboard" href="http://localhost:8989/" 
     title="Return to ASL-DVS Dashboard" target="_self" onclick="pauseAllPolling()">↺ Node Control</a>
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
  <button class="tab-btn"        id="tbtn-firewall"
    onclick="switchTab('firewall','255,170,34')">Firewall</button>
  <button class="tab-btn"        id="tbtn-journal"
    onclick="switchTab('journal','212,102,255')">Journal</button>
  <button class="tab-btn"        id="tbtn-asldvs"
    onclick="switchTab('asldvs','255,61,90')">ASL-DVS</button>
  <button class="tab-btn"        id="tbtn-reg"
    onclick="switchTab('reg','120,180,255')">Reg</button>
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
  <button class="tab-btn"        id="tbtn-edit"
    onclick="switchTab('edit','255,208,64')">Edit</button>
  <div class="cmdbar-spacer"></div>
  
  
  <div style="flex-basis:100%;height:0"></div>
  
  
  <!-- Global radio-preset quick-apply buttons -- visible in the
       persistent command bar on every tab, not just Tune, even
       though applyRadioPreset() below is defined in the Tune tab's
       own script section. -->
  <span style="font-size:.8rem;color:#fff;font-weight:500;margin-right:.4rem">Radio:</span>
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
</div>

<div id="zone-content">

  
  <!-- Overview tab. Reaches into more shared components than any
       other tab's panel: clicking a service name here doesn't open
       the dpanel in place -- it switches to the Services tab first
       (setting _dpOriginTab = "overview" so closing the panel returns
       here), then calls the shared openServicePanel(). Each row's
       Edit button calls the shared openUnitFileEditor() directly.
       Status badges use the shared portBadge(). The .dot-legend here
       is also shared with the Services and Ports tabs. -->
  <div id="panel-overview" class="tab-panel active">
    <div class="dot-legend">
      <span class="dot-legend-item"><span class="dot dot-on"></span>Active</span>
      <span class="dot-legend-item"><span class="dot dot-warn"></span>Stopped</span>
      <span class="dot-legend-item"><span class="dot dot-fail"></span>Failed / Masked</span>
      <span class="dot-legend-item"><span class="dot dot-unknown"></span>Unknown</span>
      <span class="dot-legend-item"><span class="dot dot-off"></span>Not Installed</span>
    </div>
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

  
  <!-- Services tab. Own implementation (loadGeneralList/
       renderGeneralList/s3SetScope/s3FilterChanged/
       openServicePanel). Clicking a row opens the SHARED dpanel
       (device detail panel) -- openServicePanel() below is a thin
       wrapper around the shared openPanel(), which is also the entry
       point Overview and Zello use for their own rows. Ports and
       Firewall populate the same shared dpanel directly via their own
       openPortPanel()/openFwPanel() instead of calling openPanel().
       See the boundary comment in the script section below for the
       full shared-dpanel function list. -->
  <div id="panel-services" class="tab-panel">

    
    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Services</span>
      </div>
      <div class="dot-legend">
        <span class="dot-legend-item"><span class="dot dot-on"></span>Active</span>
        <span class="dot-legend-item"><span class="dot dot-warn"></span>Stopped</span>
        <span class="dot-legend-item"><span class="dot dot-fail"></span>Failed / Masked</span>
        <span class="dot-legend-item"><span class="dot dot-unknown"></span>Unknown</span>
        <span class="dot-legend-item"><span class="dot dot-off"></span>Not Installed</span>
      </div>
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

  
  <!-- Ports tab: self-contained (own load/render/probe functions).
       Its detail-panel actions (restart/stop service, view journal,
       add firewall rule) call into a small SHARED block also used by
       the Firewall tab -- see the boundary comment in the script
       section below (ptSvcAction/ptViewJournal/ptFwAllow/ptFwDeny). -->
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

  
  <!-- Firewall tab. Own implementation (loadFirewall/renderFwRules/
       openFwPanel/fwAddRule/fwDeleteRule/fwUfwEnable/fwUfwDisable/
       fwRawCopy), plus calls into the SHARED Ports+Firewall action
       cluster (ptSvcAction/ptViewJournal, via openFwPanel's rule detail
       view) and the shared jp-popup (via ptViewJournal). Neither of
       those is owned by this tab -- see the boundary comments in the
       script section below. -->
  <div id="panel-firewall" class="tab-panel">
    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Firewall Rules</span>
        <span class="s3-card-meta">click row → details &amp; actions</span>
      </div>
      
      <div id="fw-backend-bar" class="fw-backend-bar">
        <span class="fw-backend-lbl">Backend</span>
        <span class="fw-backend-val" id="fw-backend-val">detecting…</span>
        <span class="fw-status-val"  id="fw-status-val"></span>
        <div style="margin-left:auto;display:flex;gap:.35rem" id="fw-ufw-btns">
          <button class="btn btn-muted btn-sm"
            onclick="loadFirewall()">↻ Refresh</button>
          <button class="btn btn-green btn-sm"
            onclick="fwUfwEnable()">✓ Enable ufw</button>
          <button class="btn btn-red btn-sm"
            onclick="fwUfwDisable()">✕ Disable ufw</button>
        </div>
      </div>
      
      <div id="fw-summary-line" class="fw-summary-line hidden"></div>

      <div id="fw-zone-details" class="fw-zone-details hidden"></div>

      <div id="fw-ufw-section">
        <div class="fw-table-hdr">
          <span>#</span><span>To / Port</span><span>Action</span>
          <span>From</span><span>Known Service</span><span></span>
        </div>
        <div id="fw-rule-body">
          <div class="stub-panel" style="min-height:60px">Loading…</div>
        </div>
        
        <div class="fw-add-bar">
          <span class="fw-add-lbl">Add Rule</span>
          <input  class="fw-add-inp" id="fw-add-port"
            type="text" placeholder="Port…" maxlength="6">
          <select class="fw-add-sel" id="fw-add-proto">
            <option value="tcp">tcp</option>
            <option value="udp">udp</option>
            <option value="any">any</option>
          </select>
          <select class="fw-add-sel" id="fw-add-action">
            <option value="allow">ALLOW</option>
            <option value="deny">DENY</option>
            <option value="limit">LIMIT</option>
          </select>
          <input  class="fw-add-inp" id="fw-add-from"
            type="text" placeholder="From (Anywhere)"
            style="width:130px">
          <button class="btn btn-green btn-sm"
            onclick="fwAddRule()">+ Add</button>
        </div>
      </div>
      
      <div id="fw-raw-section" class="hidden">
        <div class="fw-raw-toggle-hdr" id="fw-raw-toggle-hdr" onclick="fwToggleRaw()">
          <span class="fw-raw-toggle-title">Raw firewall output</span>
          <span class="fw-raw-toggle-chevron" id="fw-raw-toggle-chevron">▶</span>
        </div>
        <div class="fw-raw-toggle-body" id="fw-raw-toggle-body">
          <div class="fw-raw-btns">
            <button class="btn btn-muted btn-sm" onclick="fwRawCopy()">⎘ Copy</button>
          </div>
          <pre id="fw-raw-pre" class="fw-raw-pre">Loading…</pre>
        </div>
      </div>
      
      <div id="fw-none-section" class="hidden">
        <div class="stub-panel" style="min-height:80px">
          No supported firewall detected (ufw / nft / iptables)
        </div>
      </div>
    </div>
  </div>

  
  <!-- Journal tab: self-contained service list. Clicking a row (or its
       "Journal" button) opens the shared jp-popup modal defined near the
       end of <body> and driven by the JS functions in the shared jp-popup
       block (see script section below) -- that modal is also opened from
       the Ports and Firewall tabs via ptViewJournal(). -->
  <div id="panel-journal" class="tab-panel">
    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Running Services — click to view journal</span>
        <span class="s3-card-meta">pinned + active</span>
      </div>
      <div class="dot-legend">
        <span class="dot-legend-item"><span class="dot dot-on"></span>Active</span>
        <span class="dot-legend-item"><span class="dot dot-warn"></span>Stopped</span>
        <span class="dot-legend-item"><span class="dot dot-fail"></span>Failed / Masked</span>
        <span class="dot-legend-item"><span class="dot dot-unknown"></span>Unknown</span>
        <span class="dot-legend-item"><span class="dot dot-off"></span>Not Installed</span>
      </div>
      <div class="jl-table-hdr">
        <span></span><span>Service</span><span>Active</span><span></span>
      </div>
      <div id="jl-body">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>
  </div>

  
  <!-- ASL-DVS tab: three config-file lists (Asterisk/Allmon3/
       DVSwitch), each opening the SHARED uf-editor modal via its own
       category-specific open*Editor() function. Unusually for this
       file, this tab's own JS is NOT contiguous -- it's split into
       three separate locations, with the entire Tune tab's
       implementation sitting in between two of them. Search this
       file for "ASL-DVS tab, part" to find all three pieces; see the
       first one's comment for why this wasn't consolidated in this
       stage. -->
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

  </div>

  
  <!-- Reg tab. Stage 1 scaffold only -- get_reg_status() backend currently
       returns a single placeholder "info" card; real checks (dual-reg,
       statpost, credential drift, live "rpt show registrations") land in
       Stage 2+. Uses its own small renderRegChecks() rather than the
       ast-check-row pattern used by the ASL-DVS/Allmon3/DVS file browsers
       above, because those three don't have a "warn" badge case and the
       statpost check (Stage 2) needs one -- see planning notes. -->
  <div id="panel-reg" class="tab-panel">

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">AllStarLink Registration</span>
        <span class="s3-card-meta" id="reg-meta">—</span>
        <div style="display:flex;gap:.3rem;margin-left:auto">
          <button class="btn btn-muted btn-sm" id="reg-refresh"
                  onclick="loadTab_reg()">↻ Re-check</button>
        </div>
      </div>
      <div id="reg-body">
        <div class="stub-panel" style="min-height:60px">Loading…</div>
      </div>
    </div>

  </div>

  
  <!-- Tune tab. Fully self-contained -- own hook (relocated here
       from the old hooks-registry cluster, see note there), own
       implementation, no calls into any shared component (dpanel,
       jp-popup, uf-editor, diagnostic-test engine). NOTE: the five
       "Radio N" quick-apply buttons that call this tab's own
       applyRadioPreset() are NOT in this panel -- they live in the
       persistent command bar above the tab content (search for
       "radio-btn-1"), visible from every tab, not just this one. -->
  <div id="panel-tune" class="tab-panel">

    
    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">SimpleUSB — Tune Settings</span>
        <div style="display:flex;align-items:center;gap:.5rem">
          <span class="s3-card-meta" id="su-tune-status">—</span>
          <button class="ast-toggle" id="su-tune-toggle" aria-expanded="true"
            onclick="toggleTuneCard('su')" title="Show / hide this card">Hide</button>
        </div>
      </div>
      <div id="su-tune-body">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>

    
    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">Radio Presets — Quick Apply</span>
        <div style="display:flex;align-items:center;gap:.5rem">
          <span class="s3-card-meta" id="rp-status">5 slots</span>
          <button class="ast-toggle" id="rp-tune-toggle" aria-expanded="false"
            onclick="toggleTuneCard('rp')" title="Show / hide this card">Show</button>
        </div>
      </div>
      <div id="rp-tune-body" class="hidden">
        <table style="width:100%;border-collapse:collapse;font-size:.9rem">
          <thead>
            <tr style="border-bottom:1px solid var(--border2)">
              <th style="text-align:left;padding:.4rem;width:24%">Slot</th>
              <th style="text-align:center;padding:.4rem;width:16%">Type</th>
              <th style="text-align:left;padding:.4rem">Values</th>
              <th style="text-align:center;padding:.4rem;width:30%">Actions</th>
            </tr>
          </thead>
          <tbody id="rp-rows">
            <tr><td colspan="4" style="padding:1rem;text-align:center">Loading…</td></tr>
          </tbody>
        </table>
        <div style="font-size:.8rem;color:#5a7898;padding:.6rem .4rem 0;line-height:1.4">
          <strong>Save live</strong> captures the active driver's current tune card values into a slot.
          <strong>Apply</strong> pushes a slot to the active driver and restarts Asterisk.
        </div>
      </div>
    </div>

    <div class="s3-card">
      <div class="s3-card-hdr">
        <span class="s3-card-title">USBRadio — Tune Settings</span>
        <div style="display:flex;align-items:center;gap:.5rem">
          <span class="s3-card-meta" id="ur-tune-status">—</span>
          <button class="ast-toggle" id="ur-tune-toggle" aria-expanded="true"
            onclick="toggleTuneCard('ur')" title="Show / hide this card">Hide</button>
        </div>
      </div>
      <div id="ur-tune-body">
        <div class="stub-panel" style="min-height:80px">Loading…</div>
      </div>
    </div>

  </div>

  
  <!-- Hardware tab. Fully self-contained -- own hook, own
       implementation, no calls into any shared component (dpanel,
       jp-popup, uf-editor, diagnostic-test engine). The only thing to
       note: _esc() at the tail of this tab's script section (see
       boundary comment there) is a SHARED escaping helper despite
       being defined here -- also used by DVSM and STFU. -->
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

  
  <!-- DVSM tab. Fully self-contained -- own hook, own
       implementation, no calls into any shared component (dpanel,
       jp-popup, uf-editor, diagnostic-test engine). Uses the SHARED
       _esc() helper (labeled at the tail of the Hardware tab's
       section) and the shared portBadge()/dotClass()-style pattern
       for its own status badges, same as every other tab. -->
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
  
  <!-- STFU tab. Own implementation, but textually interleaved with
       M17's own implementation -- the two tabs' functions ping-pong
       back and forth across several hundred lines of script (search
       for "STFU tab, part" to find all three STFU pieces). Neither
       tab shares render functions with the other, unlike Zello, which
       reuses DVSM's _dvsmRenderAccount()/_dvsmRenderCompat() directly
       (see the pre-existing comment at the start of Zello's own
       section). Card headers use the shared .dvsm-accent/
       .dvsm-card-title/.dvsm-card-sub classes (see CSS section). -->
  <div id="panel-stfu" class="tab-panel">

    
    <div class="stfu-tab-hdr">
      <span class="stfu-tab-title">STFU — DVSwitch BrandMeister Terminal</span>
      <button class="btn btn-sky btn-sm" onclick="loadStfu()">↻ Refresh</button>
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
          <div class="dvsm-accent" style="background:var(--sky)"></div>
          <div>
            <div class="dvsm-card-title" style="color:var(--sky)">Configuration</div>
            <div class="dvsm-card-sub" id="stfu-config-path">/opt/MMDVM_Bridge/DVSwitch.ini [STFU]</div>
          </div>
        </div>
        <span class="dpbadge" id="stfu-badge-config">—</span>
      </div>
      
      <div class="stfu-bm-bar">
        <div class="stfu-bm-bar-left">
          <span style="font-size:.858rem;opacity:.7">🔗</span>
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
          <button class="btn btn-sky btn-sm"
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
          <button class="btn btn-sky btn-sm"
            onclick="stfuSave()">💾 Save</button>
          <button class="btn btn-muted btn-sm"
            onclick="stfuCopy()">⎘ Copy</button>
          <button class="btn btn-muted btn-sm"
            onclick="stfuDiscardEdit()">✕ Close</button>
          <span style="font-family:var(--mono);font-size:.66rem;
            color:#fff;margin-left:auto">
            Save then Restart to apply changes</span>
        </div>
      </div>
    </div>

  </div>

  
  <!-- M17 tab. Own implementation, textually interleaved with STFU's
       (see the boundary comments in the script section -- search for
       "M17 tab, part"). Uses the shared badge/copy/reveal helpers
       homed in the DVSM tab's section (_dvsmSetBadge/dvsmCopy/etc --
       see that boundary comment) and the shared .dvsm-accent/
       .stfu-editor-wrap CSS classes. The editor's warning banner about
       being overwritten by the ASL-DVS-M17 dashboard on every
       connect/disconnect reflects a real operational constraint, not
       a bug -- see project history for the USRP2M17.ini write-on-tune
       behavior. -->
  <div id="panel-m17" class="tab-panel">

    
    <div class="stfu-tab-hdr">
      <span class="stfu-tab-title">M17 — USRP2M17 Bridge</span>
      <button class="btn btn-sky btn-sm" onclick="loadM17()">↻ Refresh</button>
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
          <div class="dvsm-accent" style="background:var(--sky)"></div>
          <div>
            <div class="dvsm-card-title" style="color:var(--sky)">Configuration</div>
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
        <div style="padding:.5rem .6rem;font-family:var(--mono);font-size:.7rem;
          color:var(--amber);border-bottom:1px solid rgba(255,255,255,.06)">
          ⚠ Overwritten in full by the ASL-DVS-M17 dashboard on every M17
          connect/disconnect — edits here won't survive the next tune.
        </div>
        <textarea id="m17-textarea" spellcheck="false"></textarea>
        <div class="stfu-editor-bar">
          <button class="btn btn-sky btn-sm"
            onclick="m17Save()">💾 Save</button>
          <button class="btn btn-muted btn-sm"
            onclick="m17Copy()">⎘ Copy</button>
          <button class="btn btn-muted btn-sm"
            onclick="m17DiscardEdit()">✕ Close</button>
          <span style="font-family:var(--mono);font-size:.66rem;
            color:#fff;margin-left:auto">
            Restart from the Installation card above to apply changes
          </span>
        </div>
      </div>
    </div>

  </div>

  
  <!-- Zello tab. Own implementation, fully contiguous (unlike
       STFU/M17's interleaving) -- see the pre-existing developer
       comment at the start of its script section for why Config/
       Compat reuse DVSM's renderers directly while Install/Sample/
       Editor don't. Also uses the shared badge/copy helpers homed in
       the DVSM tab's section (_dvsmSetBadge/_dvsmBadgeClass/dvsmCopy)
       and the shared .dvsm-accent/.stfu-editor-wrap CSS classes, same
       as STFU and M17. The Live Status card's "Full Journal" button
       calls the SHARED openServicePanel() (see the Services tab's
       boundary comment) -- not something owned by this tab either. -->
  <div id="panel-zello" class="tab-panel">

    
    <div class="stfu-tab-hdr">
      <span class="stfu-tab-title">Zello — asl-zello-bridge</span>
      <button class="btn btn-sky btn-sm" onclick="loadZello()">↻ Refresh</button>
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
          <div class="dvsm-accent" style="background:var(--sky)"></div>
          <div>
            <div class="dvsm-card-title" style="color:var(--sky)">Configuration</div>
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
          <button class="btn btn-sky btn-sm"
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
        <div style="padding:.5rem .6rem;font-family:var(--mono);font-size:.7rem;
          color:var(--amber);border-bottom:1px solid rgba(255,255,255,.06)">
          ⚠ This is the real, active systemd override — including the plaintext
          password. Save writes it to disk immediately; changes don't take effect
          until you Restart below.
        </div>
        <textarea id="zello-textarea" spellcheck="false"></textarea>
        <div class="stfu-editor-bar">
          <button class="btn btn-sm" style="color:var(--sky);border-color:var(--sky-dim,var(--sky))"
            onclick="zelloAction('start')">▶ Start</button>
          <button class="btn btn-sm" style="color:var(--red);border-color:var(--red-dim,var(--red))"
            onclick="zelloAction('stop')">⏹ Stop</button>
          <button class="btn btn-sm" style="color:var(--green);border-color:var(--green-dim)"
            onclick="zelloAction('restart')">↺ Restart</button>
          <button class="btn btn-sky btn-sm"
            onclick="zelloSave()">💾 Save</button>
          <button class="btn btn-muted btn-sm"
            onclick="zelloCopy()">⎘ Copy</button>
          <button class="btn btn-muted btn-sm"
            onclick="zelloDiscardEdit()">✕ Close</button>
          <span style="font-family:var(--mono);font-size:.66rem;
            color:#fff;margin-left:auto">
            Save then Restart to apply changes
          </span>
        </div>
      </div>
    </div>

  </div>

  
  <!-- SD Card tab. Fully self-contained -- own hook, own
       implementation, no calls into any shared component (dpanel,
       jp-popup, uf-editor, diagnostic-test engine). Its own
       background test uses _sdTestTimer, one of the four cross-tab
       polling timers relocated to the shared core section back in
       Stage 2 -- not a component shared with any other tab's own
       code, just infrastructure this tab's timer happens to use. -->
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

  <!-- Edit tab. The most cross-cutting panel in the file:
       - Visible Tabs section drives _savedEnabledTabs/_enabledTabSet,
         the shared tab-visibility state from the Stage 2 core section.
       - Thresholds section sets _cfg_nr_warn/_cfg_nr_crit, read by the
         shared dpanel's badge rendering (see the Services tab's
         boundary comment, Stage 3d).
       - ASL-DVS Config Files opens the shared uf-editor via
         openAppConfEditor() (see the ASL-DVS tab's boundary comment,
         Stage 3e).
       - AllConf buttons open the allconf-overlay modal, which IS
         exclusive to this tab (no other tab uses it).
       See the script section's boundary comments for what's actually
       Edit's own implementation vs. shared machinery homed here. -->
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
          <input type="checkbox" id="tabchk-firewall" value="firewall" onchange="edTabVisChanged()">Firewall</label>
        <label class="tab-vis-lbl">
          <input type="checkbox" id="tabchk-journal" value="journal" onchange="edTabVisChanged()">Journal</label>
        <label class="tab-vis-lbl">
          <input type="checkbox" id="tabchk-asldvs" value="asldvs" onchange="edTabVisChanged()">ASL-DVS</label>
        <label class="tab-vis-lbl">
          <input type="checkbox" id="tabchk-reg" value="reg" onchange="edTabVisChanged()">Reg</label>
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
        <div style="font-family:var(--mono);font-size:.66rem;
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
  <span id="ed-status" style="font-family:var(--mono);
    font-size:.77rem;color:#fff;margin-left:.5rem"></span>
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
      <span style="font-family:var(--mono);font-size:.605rem;
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
        <label style="display:block;font-size:0.85rem;color:#fff;margin-bottom:0.3rem">Save as preset</label>
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
        <label style="display:flex;align-items:center;gap:0.5rem;font-size:0.85rem;color:#fff;cursor:pointer">
          <input type="checkbox" id="radio-dialog-reload-toggle" onchange="tuneDialogReloadChanged()">
          Restart Asterisk after saving
        </label>
        <div id="radio-dialog-reload-warn" style="display:none;font-size:0.8rem;color:var(--amber);margin-top:0.4rem">
          ⚠ Will restart Asterisk — brief audio interruption
        </div>
      </div>

      <div id="radio-dialog-error" style="display:none;font-size:0.85rem;color:#f88;margin-bottom:0.7rem"></div>

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
      <div id="radio-dialog-restart-msg" style="font-size:0.85rem;color:#f88;display:none;margin-bottom:0.8rem"></div>
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

<script>
"use strict";

// ============================================================
// SHARED CORE -- tab state, tab switching/visibility, polling
// control, toast(), api(), and the status poll loop.
// Every tab's window.loadTab_<name>() hook (defined further down,
// one per tab) depends on this section. Treat changes here as
// higher-risk than changes inside a single tab's own section.
// ============================================================

const TABS = ["overview","services","ports","firewall","journal","asldvs","reg","tune","hardware","dvsm","stfu","m17","zello","sdcard","edit"];

let _enabledTabSet = new Set(TABS);

// Zello's tab is toggleable like any other via the Edit-tab checkboxes, but
// is additionally gated on install status: `_savedEnabledTabs` holds the
// person's actual saved preference untouched, and `_zelloInstalled` (from
// the regular /api/status poll — no extra request) determines whether
// "zello" gets filtered out of it before every call to the existing
// applyTabVisibility(). This never adds "zello" back in if the person
// manually unchecked it while installed — the filter only ever removes.
let _savedEnabledTabs = TABS.slice();
let _zelloInstalled   = false;

// Cross-tab polling timer handles. Each is armed/disarmed by its own
// tab's loadTab_* function (Ports, Services, SD Card) further down in
// this file, but declared here alongside stopTabPolling()/
// startStatusPolling() below since those are the shared functions that
// read and clear them. All references to these four are inside
// function bodies (never top-level script code), so this forward
// declaration relative to where each timer is armed is safe -- by the
// time any of those functions can run (tab click, interval tick,
// DOMContentLoaded), this whole script has already finished its
// initial top-to-bottom pass and every let below has initialized.
let _ptRefreshTimer  = null;
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
  set.add("overview"); set.add("edit");   // locked — mirror of backend sanitizer
  _enabledTabSet = set;                   // gate for all loadTab_* hooks
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

let _uptimeBase = null;   // monotonic seconds at first poll, for client ticking

async function pollStatus() {
  const d = await api("/api/status");
  if (!d) return;

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

// ============================================================
// END SHARED CORE -- everything below this point is tab-specific,
// starting with the Overview tab. Every tab section below calls back
// into api(), toast(), switchTab(), applyTabVisibility(), and the
// stopTabPolling()/startStatusPolling() pair defined above.
// ============================================================

// ============================================================
// OVERVIEW TAB -- implementation (loadOverview/renderOverview/
// renderOvRow/ovBtns/_svcPollAfterRestart/svcAction/svcGlobal, plus
// dotEl() further down, interleaved with shared helpers -- see
// below). Calls into the shared dpanel (via switchTab("services")
// + openServicePanel(), not by opening the panel in place), the
// shared uf-editor (openUnitFileEditor(), from each row's Edit
// button), and the shared portBadge(). Ends with three SHARED
// utility functions physically homed here rather than in the Stage 2
// core section further up -- see the notes at each.
// ============================================================
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
    hdr.className = "ov-card-hdr";
    hdr.innerHTML =
      `<span class="ov-card-title">${esc(grp.group)}</span>` +
      `<span style="display:flex;gap:0;margin-left:auto;` +
      `font-family:var(--mono);font-size:.605rem;letter-spacing:.14em;` +
      `text-transform:uppercase;color:#fff">` +
      `<span class="ov-hdr-status" style="text-align:left">Status</span>` +
      `<span class="ov-hdr-port" style="text-align:left">Port</span>` +
      `</span>`;
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
  row.appendChild(state);
  row.appendChild(portEl);
  row.appendChild(badgeEl);
  row.appendChild(btns);
  card.appendChild(row);
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

async function svcGlobal(action, btn) {
  if (btn) btn.disabled = true;
  const d = await api("/api/svc", "POST", {action: action});
  if (btn) btn.disabled = false;
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "OK" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) setTimeout(loadOverview, 1200);
}

// ---- END Overview tab's own action functions. ----
//
// SHARED: dotColorClass() below is the real implementation behind
// dotClass() (the Ports tab's wrapper, labeled back in Stage 3b as
// "also used by Overview and Journal" -- this is where that shared
// logic actually lives). ----
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

// ---- back to Overview tab's own code: dotEl() is only used by
// this tab's renderOvRow() above. ----
function dotEl(state, enabled) {
  const d = document.createElement("span");
  d.className = "dot " + dotColorClass(state, enabled);
  return d;
}

// ---- SHARED again: stateClass()/esc() below close out the
// Overview tab's section -- both already labeled shared in the
// comment right after esc() (left from Stage 3d). Worth noting here:
// esc() is the single most widely-used utility in this file, called
// from nearly every tab, yet it's physically homed at this tail
// rather than in the Stage 2 shared core block further up. Not to be
// confused with _esc(), a separate, near-duplicate function homed in
// the Hardware tab's section and used by DVSM/STFU (Stage 3f). END
// of the Overview tab section -- Services' own section begins right
// after esc(). ----
function stateClass(state) {
  return {"active":"st-active","failed":"st-failed",
          "inactive":"st-inactive","not-inst":"st-notinst",
          "unknown":"st-unknown"}[state] || "st-unknown";
}

function esc(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

// stateClass() and esc() above are shared helpers (stateClass is also
// used by Overview and Journal; esc is used throughout the file) --
// not part of the Services tab. Left in place; not moved as part of
// this tab-scoped stage, matching how the Ports tab's stage handled
// dotClass().
//
// ============================================================
// SERVICES TAB -- implementation (loadGeneralList/renderGeneralList/
// s3SetScope/s3FilterChanged/openServicePanel).
// window.loadTab_services is relocated to just after this block
// (see note further down) --
// it used to sit far away, paired with window.loadTab_ports before
// that was relocated in the Ports tab's own stage.
// ============================================================
let _s3Scope  = "active";
let _s3Filter = "";
let _s3FilterTimer = null;  // debounce handle

async function loadGeneralList() {
  const qs = `?scope=${_s3Scope}&filter=${encodeURIComponent(_s3Filter)}&all=1`;
  const d  = await api("/api/services" + qs);
  if (!d) return;
  renderGeneralList(d);
}

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

function openServicePanel(unit, desc) {
  openPanel(unit, desc || "");
}

window.loadTab_services = function() {
  if (!_enabledTabSet.has("services")) return;
  clearInterval(_s3RefreshTimer);
  loadGeneralList();
  _s3RefreshTimer = setInterval(loadGeneralList, 30_000);
}

// ============================================================
// SHARED: dpanel controller (device/service detail side panel).
// _cfg_nr_warn/_cfg_nr_crit/_dpUnit/_dpActiveView/_dpOriginTab/
// TAB_RGB/dpUnit()/openPanel()/closePanel()/dpRefreshHeader()/
// dpSetReload()/dpRenderPinZone()/dpPinService()/dpUnpinService()/
// dpSvcAction()/dpLoadStatus() below are NOT Services-tab-exclusive,
// despite sitting right after the Services tab's own code. This is
// the same shared #dpanel-overlay/#dpanel component labeled as
// shared back in the CSS reorganization stage -- Overview opens it
// via this same openPanel(), and Ports/Firewall populate the same
// #dpanel DOM elements directly from their own openPortPanel()/
// openFwPanel() without calling into this code. _cfg_nr_warn/
// _cfg_nr_crit are set from the Edit tab's saved config and read here
// for badge coloring -- also not owned by any single tab.
// Ends where the (already-labeled) dotClass()/Ports tab section
// begins, just below.
// ============================================================

let _cfg_nr_warn = "3";
let _cfg_nr_crit = "10";

let _dpUnit       = "";   // unit currently shown in panel
let _dpActiveView = "";   // "status" | "journal"
let _dpOriginTab  = "";   // tab to restore to on close, if opening navigated away
const TAB_RGB = {
  overview:"0,255,229", services:"0,255,229", ports:"34,212,255",
  firewall:"255,170,34", journal:"212,102,255", asldvs:"255,61,90",
  reg:"120,180,255",
  tune:"255,68,204", hardware:"0,200,120", dvsm:"255,170,34",
  stfu:"0,191,255", zello:"255,140,0", sdcard:"180,140,255", edit:"255,208,64"
};

function dpUnit() { return _dpUnit; }

async function openPanel(unit, desc) {
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

  dpSetReload(!!d.can_reload);

  dpRenderPinZone(_dpUnit);
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
  row.innerHTML = '<span style="font-family:var(--mono);font-size:.77rem;color:#fff">…</span>';

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
    note.style.cssText = "font-family:var(--mono);font-size:.715rem;color:#fff;margin-left:.4rem";
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

// dotClass() below is a shared helper (also used by Overview and
// Journal) -- not part of the Ports tab. Left in place; not moved as
// part of this tab-scoped stage.
function dotClass(state, enabled) {
  return dotColorClass(state, enabled);
}

let _ptProto      = "both";


// ---- Ports tab (exclusive): window.loadTab_ports / loadPorts /
// renderPorts / ptSetProto / openPortPanel / ptProbeHttp / ptProbeTcp /
// ptProbeUdp. Relocated window.loadTab_ports here (it was previously
// declared far below, next to window.loadTab_services, apparently
// added later as a pair when the 15s/30s auto-refresh timers were
// built) so this tab's entry point sits with the rest of its own code,
// matching every other already-labeled tab. Safe to move: it's a
// `window.x = function(){}` assignment, not a hoisted declaration, but
// like every other loadTab_* hook it's only ever called from
// switchTab() after a user click or from the DOMContentLoaded
// bootstrap -- both fire only after this whole script has finished
// its initial top-to-bottom run, so its position within that run
// doesn't matter, only that it happens before those events can fire. ----
window.loadTab_ports = function() {
  if (!_enabledTabSet.has("ports")) return;
  clearInterval(_ptRefreshTimer);
  loadPorts();
  _ptRefreshTimer = setInterval(loadPorts, 15_000);
};

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

function ptSetProto(proto) {
  _ptProto = proto;
  ["both","tcp","udp"].forEach(p => {
    const btn = document.getElementById("pt-btn-" + p);
    if (btn) btn.classList.toggle("on", p === proto);
  });
  loadPorts();
}

function openPortPanel(p) {
  
  _dpUnit = "";   // ports panel doesn't have a unit reference in dpUnit

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
  body.innerHTML = `
    <div class="dpzone-lbl">Port Details</div>
    <div style="padding:.55rem .9rem;font-family:var(--mono);font-size:.77rem;
      border-bottom:1px solid var(--border);line-height:1.9">
      <div><span style="color:#fff;letter-spacing:.12em;text-transform:uppercase;
        font-size:.605rem">Port&nbsp;&nbsp;&nbsp;</span>
        <span style="color:var(--blue)">${esc(p.port)}</span></div>
      <div><span style="color:#fff;letter-spacing:.12em;text-transform:uppercase;
        font-size:.605rem">Proto&nbsp;&nbsp;</span>
        <span style="color:${p.proto==="tcp"?"var(--blue)":"var(--green)"}">
        ${esc(p.proto.toUpperCase())}</span></div>
      <div><span style="color:#fff;letter-spacing:.12em;text-transform:uppercase;
        font-size:.605rem">Process</span>
        <span style="color:var(--teal)">${esc(p.process || "—")}</span></div>
      <div><span style="color:#fff;letter-spacing:.12em;text-transform:uppercase;
        font-size:.605rem">PID&nbsp;&nbsp;&nbsp;&nbsp;</span>
        <span>${p.pid || "—"}</span></div>
      <div><span style="color:#fff;letter-spacing:.12em;text-transform:uppercase;
        font-size:.605rem">Listen&nbsp;&nbsp;</span>
        <span>${esc(p.addr || "0.0.0.0")}:${esc(p.port)}</span></div>
      ${p.service ? `<div><span style="color:#fff;letter-spacing:.12em;
        text-transform:uppercase;font-size:.605rem">Service</span>
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
    <div class="dpzone-lbl">Firewall</div>
    ${p.fw_state ? `<div style="padding:.25rem .9rem .35rem;font-family:var(--mono);
      font-size:.72rem"><span style="color:#fff">Currently</span>&nbsp;
      <span style="color:${p.fw_state==="allow"?"var(--green)":"var(--red)"}">
      ${p.fw_state==="allow"?"ALLOWED":"DENIED"}</span></div>` : ""}
    <div class="dpbtn-row">
      <button class="btn btn-green btn-sm"
        onclick="ptFwAllow('${p.port}','${p.proto}')">+ Allow ${p.port}/${p.proto}</button>
      <button class="btn btn-red btn-sm"
        onclick="ptFwDeny('${p.port}','${p.proto}')">✕ Deny ${p.port}/${p.proto}</button>
    </div>
    <div id="dpanel-output" style="margin:.55rem .9rem;background:#0a1020;
      border:1px solid var(--border);border-radius:3px;min-height:60px;
      max-height:180px;overflow-y:auto;padding:.5rem .7rem;
      font-family:var(--mono);font-size:.77rem;color:#fff;line-height:1.65">
      <span class="dp-out-dim">Probe results appear here</span>
    </div>`;

  document.getElementById("dpanel-overlay").classList.add("open");
  document.getElementById("dpanel").classList.add("open");
}

async function ptProbeHttp(port) {
  const out = document.getElementById("dpanel-output");
  out.innerHTML = '<span class="dp-out-dim">Probing HTTP…</span>';
  const d = await api(`/api/ports/probe?type=http&port=${port}`);
  if (!d) { out.innerHTML = '<span class="dp-out-fail">Request failed</span>'; return; }
  const cls = d.ok ? "dp-out-ok" : "dp-out-fail";
  out.innerHTML = `<span class="${cls}">${esc(d.message || "done")}</span>`;
}

async function ptProbeTcp(port) {
  const out = document.getElementById("dpanel-output");
  out.innerHTML = '<span class="dp-out-dim">Probing TCP…</span>';
  const d = await api(`/api/ports/probe?type=tcp&port=${port}`);
  if (!d) { out.innerHTML = '<span class="dp-out-fail">Request failed</span>'; return; }
  const cls = d.ok ? "dp-out-ok" : "dp-out-fail";
  out.innerHTML = `<span class="${cls}">${esc(d.message || "done")}</span>`;
}

async function ptProbeUdp(port) {
  const out = document.getElementById("dpanel-output");
  out.innerHTML = '<span class="dp-out-dim">Probing UDP…</span>';
  const d = await api(`/api/ports/probe?type=udp&port=${port}`);
  if (!d) { out.innerHTML = '<span class="dp-out-fail">Request failed</span>'; return; }
  const cls = d.ok ? "dp-out-ok" : "dp-out-fail";
  out.innerHTML = `<span class="${cls}">${esc(d.message || "done")}</span>`;
}

// ---- SHARED: Ports + Firewall. ptSvcAction/ptViewJournal/ptFwAllow/
// ptFwDeny below are called from both this tab's detail panel
// (openPortPanel above) and the Firewall tab's rule detail panel
// (openFwPanel, further down). Do not assume these are Ports-tab-only
// when Firewall gets its own refactor pass. ----
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

async function ptFwAllow(port, proto) {
  const d = await api("/api/firewall", "POST",
    {action: "allow", port, proto, src: "Anywhere"});
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "Rule added" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) loadPorts();
}

async function ptFwDeny(port, proto) {
  const d = await api("/api/firewall", "POST",
    {action: "deny", port, proto, src: "Anywhere"});
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "Rule added" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) loadPorts();
}

// ============================================================
// FIREWALL TAB -- implementation (loadFirewall/renderFwRules/
// openFwPanel/fwAddRule/fwDeleteRule/fwUfwEnable/fwUfwDisable/
// fwRawCopy). window.loadTab_firewall sits inline here (unlike Ports,
// this tab was not part of the hooks-registry cluster). openFwPanel
// below calls into the SHARED Ports+Firewall cluster just above this
// block (ptSvcAction/ptViewJournal) -- not owned by this tab, just
// called from it, same as Ports does.
// ============================================================
let _fwBackend = "none";   // current detected backend
let _fwCockpitInstalled = false;   // whether cockpit.service is on this box
let _fwRawOpen = false;    // raw-output disclosure state (collapsed by default)

window.loadTab_firewall = function() { loadFirewall(); };

async function loadFirewall() {
  const d = await api("/api/firewall");
  if (!d) return;
  _fwBackend = d.backend || "none";
  _fwCockpitInstalled = !!d.cockpit_installed;

  const bv = document.getElementById("fw-backend-val");
  const sv = document.getElementById("fw-status-val");
  if (bv) bv.textContent = _fwBackend;
  if (sv) {
    sv.textContent = d.status || "";
    sv.className   = "fw-status-val " + (d.status || "");
  }

  const ufwSec   = document.getElementById("fw-ufw-section");
  const rawSec   = document.getElementById("fw-raw-section");
  const noneSec  = document.getElementById("fw-none-section");
  const ufwBtns  = document.getElementById("fw-ufw-btns");
  const sumLine  = document.getElementById("fw-summary-line");
  const zoneCard = document.getElementById("fw-zone-details");

  ufwSec .classList.toggle("hidden", !["ufw","nft","firewalld"].includes(_fwBackend));
  rawSec .classList.toggle("hidden", !["nft","iptables","firewalld"].includes(_fwBackend));
  noneSec.classList.toggle("hidden", _fwBackend !== "none");
  if (ufwBtns) ufwBtns.style.display = _fwBackend === "ufw" ? "flex" : "none";

  const rules = d.rules || [];
  if (["ufw","nft","firewalld"].includes(_fwBackend)) {
    renderFwRules(rules);
  }

  renderFwSummary(sumLine, d, rules);
  renderFwZoneDetails(zoneCard, d);

  if (rawSec && !rawSec.classList.contains("hidden")) {
    const pre = document.getElementById("fw-raw-pre");
    if (pre) pre.textContent = d.raw || "(empty ruleset)";
  }
}

function renderFwSummary(el, d, rules) {
  if (!el) return;
  if (_fwBackend === "none") { el.classList.add("hidden"); el.innerHTML = ""; return; }
  el.classList.remove("hidden");

  const dot = d.status === "active" ? "🟢"
            : d.status === "inactive" ? "⚪" : "🟡";

  let where = "";
  if (_fwBackend === "firewalld" && d.zone_info) {
    const ifaces = (d.zone_info.interfaces || []).join(", ") || "no interface bound";
    where = ` — zone "${esc(d.zone_info.zone)}" on ${esc(ifaces)}`;
  } else if (_fwBackend === "nft" && d.chain_info) {
    where = ` — ${esc(d.chain_info.family)} ${esc(d.chain_info.table)} ${esc(d.chain_info.chain)}`;
  }

  const total   = rules.length;
  const labeled = rules.filter(r => r.service).length;
  const countTxt = total
    ? `${total} port${total === 1 ? "" : "s"} allowed` +
      (labeled ? ` (${labeled} tied to known services)` : "")
    : "no ports currently allowed through this tool";

  el.innerHTML =
    `<span class="fw-summary-dot">${dot}</span>` +
    `<span>${esc(_fwBackend)}${where} — ${countTxt}</span>`;
}

function renderFwZoneDetails(el, d) {
  if (!el) return;
  if (_fwBackend !== "firewalld" || !d.zone_info) {
    el.classList.add("hidden");
    el.innerHTML = "";
    return;
  }
  el.classList.remove("hidden");
  const zi = d.zone_info;
  const rows = [["Zone", zi.zone]];
  if ((zi.interfaces || []).length) rows.push(["Interface", zi.interfaces.join(", ")]);
  rows.push(["Policy", zi.target_desc || zi.target || "unknown"]);
  if (zi.rich_rule_count) {
    rows.push(["Rich rules", `${zi.rich_rule_count} (see raw output below)`]);
  }
  el.innerHTML = rows.map(([lbl, val]) =>
    `<div class="fw-zone-row"><span class="fw-zone-lbl">${esc(lbl)}</span>` +
    `<span class="fw-zone-val">${esc(String(val))}</span></div>`
  ).join("");
}

function fwToggleRaw() {
  _fwRawOpen = !_fwRawOpen;
  document.getElementById("fw-raw-toggle-hdr") ?.classList.toggle("open", _fwRawOpen);
  document.getElementById("fw-raw-toggle-body")?.classList.toggle("open", _fwRawOpen);
}

async function fwRawCopy() {
  const pre = document.getElementById("fw-raw-pre");
  if (!pre || !pre.textContent) { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(pre.textContent);
}

function renderFwRules(rules) {
  const body = document.getElementById("fw-rule-body");
  if (!body) return;
  body.innerHTML = "";

  if (!rules.length) {
    body.innerHTML =
      '<div class="stub-panel" style="min-height:50px">No rules configured.</div>';
    return;
  }

  rules.forEach(r => {
    const row = document.createElement("div");
    row.className = "fw-row";
    row.onclick   = e => {
      if (e.target.classList.contains("fw-del")) return;
      openFwPanel(r);
    };

    const svcTxt = r.service || "—";
    const svcCls = r.service ? "fw-svc" : "fw-svc unknown";

    row.innerHTML =
      `<span class="fw-num">${r.num}</span>` +
      `<span class="fw-to">${esc(r.to)}</span>` +
      `<span class="fw-action ${esc(r.action)}">${esc(r.action)}</span>` +
      `<span class="fw-from">${esc(r.from)}</span>` +
      `<span class="${svcCls}">${esc(svcTxt)}</span>` +
      `<span class="fw-del" onclick="fwDeleteRule('${esc(String(r.num))}',this)">✕</span>`;
    body.appendChild(row);
  });
}

function openFwPanel(rule) {
  document.getElementById("dpanel").style.setProperty(
    "--panel-accent", "var(--orange)");

  document.getElementById("dpanel-unit").textContent =
    `Rule #${rule.num} — ${rule.to}`;
  document.getElementById("dpanel-desc").textContent =
    `${rule.action}  ${rule.from}${rule.service ? "  →  " + rule.service : ""}`;
  document.getElementById("dpanel-badges").innerHTML = "";
  document.getElementById("dpanel-output").innerHTML =
    '<span class="dp-out-dim">Select an action below</span>';

  const body = document.getElementById("dpanel-body");
  const svcHtml = rule.service ? `
    <div class="dpzone-lbl">Service Actions</div>
    <div class="dpbtn-row">
      <button class="btn btn-blue  btn-sm"
        onclick="ptSvcAction('restart','${esc(rule.service)}.service')">↺ Restart</button>
      <button class="btn btn-amber btn-sm"
        onclick="ptSvcAction('stop','${esc(rule.service)}.service')">■ Stop</button>
      <button class="btn btn-purple btn-sm"
        onclick="ptViewJournal('${esc(rule.service)}.service')">▤ Journal</button>
    </div>` : "";

  body.innerHTML = `
    <div class="dpzone-lbl">Rule Details</div>
    <div style="padding:.55rem .9rem;font-family:var(--mono);font-size:.77rem;
      border-bottom:1px solid var(--border);line-height:1.9">
      <div><span style="color:#fff;font-size:.605rem;letter-spacing:.12em;
        text-transform:uppercase">Rule #&nbsp;</span>
        <span style="color:var(--orange)">${rule.num}</span></div>
      <div><span style="color:#fff;font-size:.605rem;letter-spacing:.12em;
        text-transform:uppercase">Port&nbsp;&nbsp;&nbsp;</span>
        <span style="color:var(--text-bright)">${esc(rule.to)}</span></div>
      <div><span style="color:#fff;font-size:.605rem;letter-spacing:.12em;
        text-transform:uppercase">Action&nbsp;</span>
        <span class="fw-action ${esc(rule.action)}" style="display:inline">
        ${esc(rule.action)}</span></div>
      <div><span style="color:#fff;font-size:.605rem;letter-spacing:.12em;
        text-transform:uppercase">From&nbsp;&nbsp;&nbsp;</span>
        <span>${esc(rule.from)}</span></div>
      ${rule.service ? `<div><span style="color:#fff;font-size:.605rem;
        letter-spacing:.12em;text-transform:uppercase">Service</span>
        <span style="color:var(--amber)">${esc(rule.service)}.service</span></div>` : ""}
    </div>
    <div class="dpzone-lbl">Rule Actions</div>
    <div class="dpbtn-row">
      <button class="btn btn-red btn-sm"
        onclick="fwDeleteRule('${esc(String(rule.num))}',this);closePanel()">✕ Delete Rule</button>
    </div>
    <div style="margin:.3rem .9rem .55rem;font-size:.72rem;color:var(--text-dim);
      line-height:1.5">
      ${_fwCockpitInstalled
        ? `To change this rule's action, use Cockpit's firewall panel
           (<span style="color:var(--sky)">https://&lt;host&gt;:9090</span> →
           Networking → Firewall) — sysmon only deletes existing rules.`
        : `To change this rule's action, delete it and re-add it with the
           desired action, or use the ufw CLI directly — sysmon only
           deletes existing rules.`}
    </div>
    ${svcHtml}
    <div id="dpanel-output" style="margin:.55rem .9rem;background:#0a1020;
      border:1px solid var(--border);border-radius:3px;min-height:50px;
      max-height:160px;overflow-y:auto;padding:.5rem .7rem;
      font-family:var(--mono);font-size:.77rem;color:#fff;line-height:1.65">
      <span class="dp-out-dim">Action results appear here</span>
    </div>`;

  document.getElementById("dpanel-overlay").classList.add("open");
  document.getElementById("dpanel").classList.add("open");
}

async function fwAddRule() {
  const port   = document.getElementById("fw-add-port").value.trim();
  const proto  = document.getElementById("fw-add-proto").value;
  const action = document.getElementById("fw-add-action").value;
  const from_  = document.getElementById("fw-add-from").value.trim() || "Anywhere";
  if (!port) { toast("Enter a port number", "err"); return; }
  const d = await api("/api/firewall", "POST",
    {action: action, port: port, proto: proto, src: from_});
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "Rule added" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) {
    document.getElementById("fw-add-port").value = "";
    document.getElementById("fw-add-from").value = "";
    setTimeout(loadFirewall, 600);
  }
}

async function fwDeleteRule(num, btn) {
  if (!await confirm(`Delete firewall rule #${num}?`)) return;
  if (btn) btn.disabled = true;
  const d = await api("/api/firewall", "POST", {action: "delete", rule_num: num});
  if (btn) btn.disabled = false;
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "Rule deleted" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) setTimeout(loadFirewall, 600);
}

async function fwUfwEnable() {
  const d = await api("/api/firewall", "POST", {action: "enable"});
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "ufw enabled" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) setTimeout(loadFirewall, 800);
}

async function fwUfwDisable() {
  if (!await confirm("Disable ufw? All firewall rules will be inactive.")) return;
  const d = await api("/api/firewall", "POST", {action: "disable"});
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "ufw disabled" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) setTimeout(loadFirewall, 800);
}

// ---- END Firewall tab implementation ----

// ============================================================
// SHARED: journal-viewer popup (jp-*), part 1 of 2 -- module state.
// This popup is opened from three places: the Journal tab directly
// (renderJournalList below), and from the Ports and Firewall tabs via
// ptViewJournal() (defined in the Ports tab section further down).
// The Journal-tab-exclusive block sits right below this state block;
// the rest of the shared jp-* functions resume after it, marked below.
// ============================================================
let _jpUnit  = "";    // unit currently shown in popup
let _jpLines = 200;   // current line count setting
let _jpRaw   = "";    // raw journal text for client-side grep
let _jpFilteredText = "";  // currently displayed (grep-filtered) text — what Copy copies

// ---- Journal tab (exclusive: loadTab_journal / loadJournalList /
// renderJournalList only) ----
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

// ---- SHARED: journal-viewer popup (jp-*), part 2 of 2 -- functions.
// See the part-1 boundary comment above for what uses this. ----
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

// ---- END shared jp-popup component ----

let _edDirty = false;

// ============================================================
// EDIT TAB -- implementation (edToggleAslDvs/edTogglePinned/
// edAslDvsLoad/edToggleFileHidden/ED_FIELDS/edReload/
// ED_LOCKED_TABS/edSetTabVis/edGetTabVis/edTabVisChanged/edValidate/
// edField/edClearErrors/edUpdateSaveBtn/edSetStatus/edCountPinned/
// edSave/edAllConf/allConfOverlayClick/closeAllConf/allConfCopy/
// _copyWithVerify). edSetTabVis()/edTabVisChanged() write the shared
// _savedEnabledTabs/_enabledTabSet state (Stage 2 core); edSave()
// writes the shared _cfg_nr_warn/_cfg_nr_crit (Stage 3d). Ends with
// several SHARED utilities physically homed here rather than in the
// Stage 2 core section or their using tab's own section -- see the
// notes at each below.
// ============================================================
window.loadTab_edit = function() { edReload(); edAslDvsLoad(); };

let _edAslOpen = false;

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

let _edPinnedOpen = false;

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
    current.delete(filename);   // un-hiding
  } else {
    current.add(filename);      // hiding
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

const ED_LOCKED_TABS = ["overview", "edit"];   // mirror of backend _LOCKED_TABS

function edSetTabVis(enabled) {
  const set = new Set(Array.isArray(enabled) ? enabled : TABS);
  for (const t of TABS) {
    if (ED_LOCKED_TABS.includes(t)) continue;   // locked: always checked+disabled
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


// Part of the shared polling system (see SHARED CORE at top of file).
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
    // ASL AllConf: asterisk config files + allmon3 (ASL web monitor) files
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
    // DVS AllConf: dvswitch config files only
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

// ---- END Edit tab's own implementation. ----
//
// ============================================================
// SHARED: confirm/alert modal system (confirm()/modalCancel()/
// modalConfirm()/alertModal()/_resetModalAlertUI(), plus the
// DOMContentLoaded listener just below this block that wires up the
// #modal-overlay buttons). This is the single most widely-called
// shared utility in the file -- confirm() alone has 27+ call sites
// across virtually every tab (any destructive action: stop/restart/
// delete/disable/etc.) -- yet it's physically homed here, at the
// tail of the Edit tab's section, rather than in the Stage 2 shared
// core block. Not part of Edit's own functionality at all.
// ============================================================
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

// ---- SHARED: postAction(), a small POST+confirm+toast wrapper used
// only by the global emergency-bar and command-bar buttons (Emergency
// Restart, Reboot, Shutdown -- see the HTML comment at #emg-bar).
// Not called from within any tab panel. ----
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


// ---- Shared polling system, continued (see SHARED CORE above) ----
// pauseAllPolling()/resumeAllPolling() below are an extension of the
// same stopStatusPolling()/startStatusPolling()/stopTabPolling()
// system defined at the top of this file, kept here because they're
// tied to the in-page "return to dashboard" navigation link. Treat
// with the same care as the core section above.
let _pausedByNavigation = false;

function pauseAllPolling() {
  _pausedByNavigation = true;
  sessionStorage.setItem("sysmon_paused_by_nav", "1");
  stopStatusPolling();
  stopTabPolling("ports");
  stopTabPolling("services");
  stopTabPolling("sdcard");
  console.info("[sysmon] All polling paused (navigating to dashboard)");
}

function resumeAllPolling() {
  _pausedByNavigation = false;
  startStatusPolling();   // the primary 5-second loop
  console.info("[sysmon] All polling resumed");
}

// window.loadTab_services used to sit here (paired with the old
// window.loadTab_ports location before that was relocated in the
// Ports tab's own stage). Relocated to the Services tab section
// above, next to openServicePanel(), matching every other
// already-labeled tab. Safe to move for the same reason documented
// at the Ports tab's relocation note: this is a window.x = function
// assignment only ever invoked from switchTab() or the
// DOMContentLoaded bootstrap, both of which fire only after this
// whole script has finished its initial top-to-bottom run.

// ============================================================
// SHARED: universal file editor (uf-*) -- core implementation.
// openUnitFileEditor()/closeUnitFileEditor()/ufOverlayClick()/
// ufCopy()/ufSetStatus()/_ufSaveOrig()/ufRestart()/ufReloadDaemon()
// below were built for systemd unit files -- called from Overview
// and Services (their per-row Edit button). Not owned by either tab.
// ASL-DVS's four config editors (further down, in three separate
// locations -- see its own boundary comments) bypass
// openUnitFileEditor() and populate the same #uf-overlay DOM
// directly, same pattern Ports/Firewall use with the dpanel. Save
// for ALL of this (unit files and ASL-DVS's config files alike) is
// dispatched through ufSave(), defined far below right after the
// Asterisk-config section, which delegates back to _ufSaveOrig()
// here for plain unit files.
// ============================================================
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

window.loadTab_asldvs = function() { loadAstFiles(); loadAllmon3Files(); loadDvsFiles(); };

// ---------------------------------------------------------------------------
// Reg tab -- Stage 1 scaffold. Own small renderer (not the ast-check-row
// pattern reused by ASL-DVS/Allmon3/DVS above) because those three have no
// "warn" badge case, and Stage 2's statpost check needs one (see planning
// notes: statpost failure should render as its own warning, not fail the
// whole tab). get_reg_status() currently returns one placeholder "info"
// card; real checks land in Stage 2+.
// ---------------------------------------------------------------------------
function renderRegChecks(checks) {
  const body = document.getElementById("reg-body");
  const meta = document.getElementById("reg-meta");
  if (!body) return;
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

window.loadTab_reg = async function() {
  if (!_enabledTabSet.has("reg")) return;
  const d = await api("/api/reg");
  if (!d || !d.ok) {
    const body = document.getElementById("reg-body");
    if (body) body.innerHTML = '<div class="stub-panel" style="min-height:60px">Server unreachable</div>';
    return;
  }
  renderRegChecks(d.checks);
};
// window.loadTab_tune used to sit here too, right next to
// window.loadTab_asldvs -- both were part of the original
// hooks-registry cluster (see the comment a few dozen lines above).
// Relocated to the Tune tab's own section, matching every other
// already-labeled tab. window.loadTab_asldvs stays here: ASL-DVS's
// implementation has no single contiguous home to move it to (see
// its own boundary comments -- it's split into three parts around
// this very Tune tab).

// ============================================================
// SD CARD TAB -- implementation (loadSdHealth/renderSdHealth/
// sdKernelLogCopy/loadSdTests/sdTestPoll/sdTestStart/sdTestCancel/
// renderSdTests). Fully self-contained: no calls into the dpanel,
// jp-popup, uf-editor, or diagnostic-test engine shared components
// used elsewhere in this file. Its background integrity test uses
// _sdTestTimer (declared in the shared core section, Stage 2) to
// poll while a test runs across tab switches. Ends where the
// SHARED _esc() helper / Hardware tab's section begins, just below.
// ============================================================
window.loadTab_sdcard = function() {
  if (!_enabledTabSet.has("sdcard")) return;   // v5.4.0 gate (arms _sdTestTimer)
  loadSdHealth(); loadSdTests();
};

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

// ---- END SD Card tab implementation. ----
//
// ============================================================
// HARDWARE TAB -- implementation (loadHardware/loadHardwareDiag/
// renderUsbSection/renderAslFindSoundSection/renderAlsaSection/
// renderPowerSection/renderAmbeSection/renderAudioSection/
// hwApplyUdev/hwDelUdev/hwSetBaud/hwPing/hwResetChip and their
// supporting helpers). Fully self-contained: no calls into the
// dpanel, jp-popup, uf-editor, or diagnostic-test engine shared
// components used elsewhere in this file. Ends where the SHARED
// _esc() helper begins, just below.
// ============================================================
window.loadTab_hardware = function() { loadHardware(); };

const _hwPingCache = {};

let _hwUsbView  = "flat";     // "flat" | "tree"
let _hwAlsaView = "playback"; // "playback" | "capture"
let _hwDiagData = null;       // last /api/hardware/diag response

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

const _HW_AMBE_PAIRS  = {"0403:6015": "ThumbDV"};
const _HW_FTDI_VIDS   = {"0403": true};

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
    <span style="font-family:var(--mono);font-size:.946rem;
      color:var(--text-bright);font-weight:700">${_esc(primary.label)}</span>
    ${badge}
    <span style="font-family:var(--mono);font-size:.715rem;
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
        ? `<span style="font-family:var(--mono);font-size:.715rem;color:#fff;margin-left:.4rem">→</span>
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
    <span style="font-family:var(--mono);font-size:.946rem;
      color:var(--text-bright);font-weight:700">${_esc(primary.card_name)}</span>
    <span class="hw-badge hw-badge-audio">USB AUDIO</span>
    <span style="font-family:var(--mono);font-size:.715rem;
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

  html += `</div>`; // hw-compat-section

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

// ---- END Hardware tab implementation. ----
//
// SHARED: _esc() below, despite being defined at the tail of the
// Hardware tab's section, is used well beyond Hardware -- DVSM and
// STFU both call it extensively for HTML-escaping. It's functionally
// a near-duplicate of the shared esc() defined in the core section
// near the top of this file; not consolidated here, since merging
// them is a real code change, not a reorganization, and out of scope
// for a comment-only stage.
function _esc(s) {
  return String(s || "")
    .replace(/&/g,"&amp;")
    .replace(/</g,"&lt;")
    .replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;")
    .replace(/'/g,"&#39;");
}

// ============================================================
// ASL-DVS tab, part 1 of 3 (DVSwitch config: loadAstFiles/
// loadDvsFiles/renderDvsFiles/openDvsEditor/openAppConfEditor).
// NOTE the split: loadAstFiles() below loads Asterisk's file list,
// but its renderer -- renderAstFiles() -- lives in part 3, on the
// far side of the entire Tune tab implementation. openDvsEditor()/
// openAppConfEditor() populate the shared #uf-overlay directly (see
// the SHARED uf-editor comment above) rather than calling
// openUnitFileEditor().
//
// This tab's three pieces were left physically separated rather than
// consolidated in this stage: doing so safely would mean reasoning
// about the ~900-line Tune tab implementation sitting between parts
// 2 and 3 as well, which is out of proportion for an ASL-DVS-scoped
// pass. Recommended as a dedicated future pass, likely paired with
// Tune's own stage rather than folded into either tab's alone.
// ============================================================
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
      `${esc(f.label)}<span style="color:#fff;font-size:.715rem;margin-left:.6rem">${esc(f.path)}</span>`;
    if (!f.exists) {
      nameEl.innerHTML +=
        `<span style="color:var(--amber);font-size:.66rem;margin-left:.4rem">⚠ not found</span>`;
    }
    if (isHidden) {
      nameEl.innerHTML +=
        `<span style="color:#fff;font-size:.66rem;margin-left:.4rem">hidden</span>`;
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
    const collapsible = false;   // DVSwitch checks always expanded
    if (checks.length) {
      const cb = document.createElement("div");
      cb.className = "ast-checks";
      checks.forEach(c => {
        if (c.title.startsWith("[")) {
          const lbl = document.createElement("div");
          lbl.style.cssText =
            "font-family:var(--mono);font-size:.66rem;letter-spacing:.15em;" +
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
      body.appendChild(cb);
    }

    if (portLines.length) {
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
      body.appendChild(pl);
    }
  });
}

async function openDvsEditor(label) {
  _ufUnit = "\x00dvs:" + label;

  document.getElementById("uf-title").textContent      = `✎ ${label}`;
  document.getElementById("uf-path").textContent       = "Loading…";
  document.getElementById("uf-textarea").value         = "";
  document.getElementById("uf-status").textContent     = "";
  document.getElementById("uf-promoted-bar").classList.remove("show");
  document.getElementById("uf-save-btn").disabled      = true;
  document.getElementById("uf-restart-btn").disabled   = true;
  document.getElementById("uf-restart-btn").style.display = "none";
  document.getElementById("uf-overlay").classList.add("open");

  const d = await api(`/api/dvswitch/file?label=${encodeURIComponent(label)}`);
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

async function openAppConfEditor(label) {
  _ufUnit = "\x00appconf:" + label;

  document.getElementById("uf-title").textContent      = `✎ ${label}`;
  document.getElementById("uf-path").textContent       = "Loading…";
  document.getElementById("uf-textarea").value         = "";
  document.getElementById("uf-status").textContent     = "";
  document.getElementById("uf-promoted-bar").classList.remove("show");
  document.getElementById("uf-save-btn").disabled      = true;
  document.getElementById("uf-restart-btn").disabled   = true;
  document.getElementById("uf-restart-btn").style.display = "none";
  document.getElementById("uf-overlay").classList.add("open");

  const dc = await api(`/api/appconf/file?label=${encodeURIComponent(label)}`);
  if (!dc || !dc.ok) {
    ufSetStatus(dc?.message || "Failed to load", false);
    return;
  }
  document.getElementById("uf-textarea").value      = dc.content;
  document.getElementById("uf-save-btn").disabled   = !dc.writable;
  document.getElementById("uf-path").textContent    = dc.path;
  if (!dc.exists) {
    ufSetStatus("⚠ File does not exist yet — saving will create it", false);
  } else {
    ufSetStatus(dc.writable ? "" : "Read-only (not running as root)");
  }
}

// ---- ASL-DVS tab, part 2 of 3 (Allmon3 config: loadAllmon3Files/
// renderAllmon3Files/openAllmon3Editor). Part 3 (Asterisk config)
// resumes after the entire Tune tab implementation below -- see the
// part 1 comment above for why. ----
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
      `${esc(f.label)}<span style="color:#fff;font-size:.715rem;margin-left:.6rem">${esc(f.path)}</span>`;
    if (!f.exists) {
      nameEl.innerHTML +=
        `<span style="color:var(--amber);font-size:.66rem;margin-left:.4rem">⚠ not found</span>`;
    }
    if (isHidden) {
      nameEl.innerHTML +=
        `<span style="color:#fff;font-size:.66rem;margin-left:.4rem">hidden</span>`;
    }
    if (isRO) {
      nameEl.innerHTML +=
        `<span style="color:#fff;font-size:.66rem;margin-left:.4rem">read-only</span>`;
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
      checks.forEach(c => {
        if (c.title.startsWith("[")) {
          const lbl = document.createElement("div");
          lbl.style.cssText =
            "font-family:var(--mono);font-size:.66rem;letter-spacing:.15em;" +
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
        if      (c.status === "pass") { badge.className = "ast-check-pass"; badge.textContent = "[PASS]"; }
        else if (c.status === "fail") { badge.className = "ast-check-fail"; badge.textContent = "[FAIL]"; }
        else if (c.status === "info") { badge.className = "ast-check-info"; badge.textContent = "[INFO]"; }
        else                          { badge.className = "ast-check-none"; badge.textContent = "[NONE]"; }
        crow.appendChild(title);
        crow.appendChild(val);
        crow.appendChild(badge);
        cb.appendChild(crow);
        if (Array.isArray(c.notes)) {
          c.notes.forEach(line => {
            const nrow = document.createElement("div");
            nrow.className   = "ast-check-note";
            nrow.textContent = line;
            cb.appendChild(nrow);
          });
        }
      });
      body.appendChild(cb);
    }

    if (portLines.length) {
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
      body.appendChild(pl);
    }
  });
}

async function openAllmon3Editor(label) {
  _ufUnit = "\x00allmon3:" + label;

  document.getElementById("uf-title").textContent      = `✎ ${label}`;
  document.getElementById("uf-path").textContent       = "Loading…";
  document.getElementById("uf-textarea").value         = "";
  document.getElementById("uf-status").textContent     = "";
  document.getElementById("uf-promoted-bar").classList.remove("show");
  document.getElementById("uf-save-btn").disabled      = true;
  document.getElementById("uf-restart-btn").disabled   = true;
  document.getElementById("uf-restart-btn").style.display = "none";
  document.getElementById("uf-overlay").classList.add("open");

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

// ============================================================
// TUNE TAB -- implementation (38 functions/vars: tuneCardDefaultOpen
// through setActiveRadioButton -- card open/close, live radio-stack
// status polling, per-driver tune card load/render/save, the radio
// preset dialog, and applyRadioPreset()/updateRadioButtons(), which
// drive the global "Radio N" buttons in the command bar -- see the
// HTML comment there). Fully self-contained: no calls into the
// dpanel, jp-popup, uf-editor, or diagnostic-test engine shared
// components used elsewhere in this file. window.loadTab_tune is
// relocated to just below (it used to sit in the old hooks-registry
// cluster, paired with window.loadTab_asldvs -- see the note there).
// ASL-DVS's part 3 resumes after this tab's implementation ends, at
// renderAstFiles.
// ============================================================
window.loadTab_tune = function() { loadSimpleUSBTune(); loadUsbradioTune(); Promise.all([loadRadioPresets(), loadRadioDriver()]).then(() => { updateRadioButtons(); renderRadioPresets(window.radioPresets || {}); restoreActiveRadioButton(); }); };

function tuneCardDefaultOpen(moduleState) {
  return moduleState === "load" || moduleState === "require";
}
function setTuneCardOpen(prefix, open) {
  const body = document.getElementById(prefix + "-tune-body");
  const btn  = document.getElementById(prefix + "-tune-toggle");
  if (!body || !btn) return;
  body.classList.toggle("hidden", !open);
  btn.textContent = open ? "Hide" : "Show";
  btn.setAttribute("aria-expanded", open ? "true" : "false");
}
function toggleTuneCard(prefix) {
  const body = document.getElementById(prefix + "-tune-body");
  if (!body) return;
  setTuneCardOpen(prefix, body.classList.contains("hidden"));
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
  if (!busy) updateRadioButtons();   // re-derive proper enable state
}

async function pollRadioStackStatus() {
  const DEADLINE_MS = 35000;
  const INTERVAL_MS = 1500;
  const t0 = Date.now();

  while (Date.now() - t0 < DEADLINE_MS) {
    await new Promise(r => setTimeout(r, INTERVAL_MS));
    const s = await api("/api/radio/stack_status");
    if (!s || !s.ok) continue;               // transient fetch failure — keep polling

    if (s.restarting) continue;              // still unloading/settling/restarting

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

const TUNE_DRIVERS = {
  simpleusb: {
    label: "SimpleUSB",
    readEndpoint: "/api/simpleusb/tune",
    notFoundMsg: "⚠ simpleusb.conf not found at /etc/asterisk/simpleusb.conf",
    fever: false,
    fields: [
      { id: "rxmixerset", label: "RX Mixer Set", color: "var(--blue)",   tint: "rgba(100,150,220,0.15)", min: 0, max: 1000, step: 1, dec: 0, def: 500 },
      { id: "txmixaset",  label: "TX Mix A Set", color: "var(--green)",  tint: "rgba(100,180,100,0.15)", min: 0, max: 1000, step: 1, dec: 0, def: 300 },
      { id: "txmixbset",  label: "TX Mix B Set", color: "var(--orange)", tint: "rgba(220,140,60,0.15)",  min: 0, max: 1000, step: 1, dec: 0, def: 300 },
    ],
    // Stage 6 — "Simpleusb Advanced Settings" subsection. Data only for now;
    // renderTuneCard()/getTuneValues()/isTuneDirty() wiring is Stages 7-8.
    // Each entry renders as a checkbox: checked -> "yes", unchecked -> "no",
    // matching simpleusb.conf's own yes/no convention. First-check appends
    // the key to the node's own stanza (inherits from [node-main] until then);
    // unchecking after that flips the existing line back to "no" in place —
    // see save_simpleusb_tune_settings() on the backend.
    boolFields: [
      { id: "rxboost",     label: "RX Boost" },
      { id: "deemphasis",  label: "De-emphasis" },
      { id: "preemphasis", label: "Pre-emphasis" },
    ],
    // "RX/TX Delay" subsection — checkbox + number box pairs, one checkbox
    // per field (not a shared toggle). Unchecked always saves 0 to
    // simpleusb.conf, matching the file's own "0 = disabled" convention for
    // these two keys. Checking the box just unlocks the number input; it
    // does not itself change the saved value until the input has a nonzero
    // number. Values clamp to [min,max] on entry, same as the mixer sliders.
    numberFields: [
      { id: "rxondelay",  label: "RX On Delay",  hint: "ms Frames 0-100 Range", min: 0, max: 100 },
      { id: "txoffdelay", label: "TX Off Delay", hint: "ms Frames 0-100 Range", min: 0, max: 100 },
    ],
  },
  usbradio: {
    label: "USBRadio",
    readEndpoint: "/api/usbradio/read",
    notFoundMsg: "⚠ usbradio.conf not found at /etc/asterisk/usbradio.conf",
    fever: true,
    fields: [
      { id: "rxmixerset",   label: "RX Mixer Set",   color: "var(--blue)",   tint: "rgba(100,150,220,0.15)", min: 0,    max: 1000,   step: 1,    dec: 0, def: 500 },
      { id: "txmixaset",    label: "TX Mix A Set",   color: "var(--green)",  tint: "rgba(100,180,100,0.15)", min: 0,    max: 1000,   step: 1,    dec: 0, def: 300 },
      { id: "txmixbset",    label: "TX Mix B Set",   color: "var(--orange)", tint: "rgba(220,140,60,0.15)",  min: 0,    max: 1000,   step: 1,    dec: 0, def: 300 },
      { id: "txctcssadj",   label: "TX CTCSS Level", color: "var(--purple)", tint: "rgba(180,100,220,0.15)", min: 0,    max: 1000,   step: 1,    dec: 0, def: 100 },
      { id: "rxsquelchadj", label: "RX Squelch",     color: "var(--teal)",   tint: "rgba(60,200,200,0.15)",  min: 0,    max: 1000,   step: 1,    dec: 0, def: 800 },
      { id: "rxvoiceadj",   label: "RX Voice Adj",   color: "var(--pink)",   tint: "rgba(220,80,180,0.15)",  min: 0,    max: 1,      step: 0.01, dec: 2, def: 0.75 },
      { id: "rxctcssadj",   label: "RX CTCSS Adj",   color: "var(--blue)",   tint: "rgba(100,150,220,0.15)", min: 0,    max: 1,      step: 0.01, dec: 2, def: 0.5 },
      { id: "txslimsp",     label: "TX Bandwidth",   color: "var(--green)",  tint: "rgba(100,180,100,0.15)", min: 1000, max: 100000, step: 1000, dec: 0, def: 50000 },
    ],
  },
};

function tunePrefix(driver) { return driver === "usbradio" ? "ur" : "su"; }
function tuneDriverForPrefix(prefix) { return prefix === "ur" ? "usbradio" : "simpleusb"; }
function tuneFieldSpec(prefix, fieldId) {
  return TUNE_DRIVERS[tuneDriverForPrefix(prefix)].fields.find(f => f.id === fieldId);
}

async function loadTuneCard(driver) {
  const cfg    = TUNE_DRIVERS[driver];
  const prefix = tunePrefix(driver);
  const body   = document.getElementById(`${prefix}-tune-body`);
  const status = document.getElementById(`${prefix}-tune-status`);
  try {
    const resp = await api(cfg.readEndpoint);
    if (!resp || !resp.exists) {
      if (body)   body.innerHTML = `<div class="stub-panel" style="min-height:60px">${cfg.notFoundMsg}</div>`;
      if (status) status.textContent = "not found";
      if (resp) setTuneCardOpen(prefix, tuneCardDefaultOpen(resp.module));
      return;
    }
    if (status) status.textContent = "ready";
    renderTuneCard(driver, resp.settings || {});
    setTuneCardOpen(prefix, tuneCardDefaultOpen(resp.module));
  } catch (e) {
    if (body)   body.innerHTML = `<div class="stub-panel" style="color:#f88;min-height:60px">Error: ${e.message}</div>`;
    if (status) status.textContent = "error";
  }
}

async function loadSimpleUSBTune() { return loadTuneCard("simpleusb"); }
async function loadUsbradioTune()  { return loadTuneCard("usbradio"); }

function renderTuneCard(driver, s) {
  const cfg    = TUNE_DRIVERS[driver];
  const prefix = tunePrefix(driver);
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
              font-family: var(--mono);
              font-size: 0.85rem;
              font-weight: 400;
              background: ${f.tint};
              border: 1px solid var(--border2);
              border-radius: 0.3rem;
              padding: 0.2rem 0.4rem;
              width: 5.5rem;
              text-align: right;
              color: var(--text)"
            onchange="tuneNumberInput('${prefix}','${f.id}')"
            oninput="tuneNumberInput('${prefix}','${f.id}')">
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
          oninput="tuneSlide('${prefix}','${f.id}')">
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; font-size: 0.75rem; color: #5a7898">
          <span>Min: ${f.min}</span>
          <span style="text-align: right">Max: ${f.max}</span>
        </div>
      </div>`;
  }).join("");

  let feverHtml = "";
  if (cfg.fever) {
    originals.fever = s.fever === 1 ? 1 : 0;
    feverHtml = `
      <div style="display: grid; gap: 0.6rem">
        <label for="${prefix}-fever" style="
          font-weight: 600;
          font-size: 0.9rem;
          color: var(--red)">RF Overload (Fever)</label>
        <select id="${prefix}-fever" onchange="checkTuneDirty('${prefix}')" style="
          width: 100%;
          padding: 0.4rem 0.5rem;
          background: var(--surface2);
          color: var(--text);
          border: 1px solid var(--border2);
          border-radius: 0.3rem;
          cursor: pointer">
          <option value="0" ${s.fever === 1 ? "" : "selected"}>Off (0)</option>
          <option value="1" ${s.fever === 1 ? "selected" : ""}>On (1)</option>
        </select>
      </div>`;
  }

  // Stage 7 — "Simpleusb Advanced Settings" subsection. Generic loop over
  // cfg.boolFields (currently rxboost/deemphasis/preemphasis) so a future
  // registry addition (Stage 1 backend + a one-line entry in TUNE_DRIVERS,
  // Stage 6) needs no change here. originals[f.id] is seeded as the raw
  // "yes"/"no" string returned by the API, matching what getTuneValues()
  // will emit (Stage 8) so isTuneDirty()'s string compare works unmodified.
  let boolFieldsHtml = "";
  if (cfg.boolFields && cfg.boolFields.length) {
    const rows = cfg.boolFields.map(f => {
      const checked = s[f.id] === "yes";
      originals[f.id] = checked ? "yes" : "no";
      return `
        <label for="${prefix}-${f.id}" style="
          display: flex;
          align-items: center;
          gap: 0.5rem;
          font-size: 0.85rem;
          color: var(--text);
          cursor: pointer">
          <input type="checkbox" id="${prefix}-${f.id}"
            ${checked ? "checked" : ""}
            aria-label="${f.label}"
            onchange="checkTuneDirty('${prefix}')">
          <span>${f.label}</span>
        </label>`;
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
      </div>`;
  }

  // "RX/TX Delay" subsection — checkbox + number box per field, one
  // checkbox per field (not shared). Unchecked forces the number box to 0
  // and disables it; checking just unlocks entry, it does not itself
  // change the value. originals[f.id] is seeded as a plain integer so
  // isTuneDirty()'s existing numeric-tolerance compare handles these with
  // no special-casing (unlike boolFields' "yes"/"no" strings).
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
            font-size: 0.85rem;
            color: var(--text);
            cursor: pointer">
            <input type="checkbox" id="${prefix}-${f.id}-enable"
              ${checked ? "checked" : ""}
              aria-label="Enable ${f.label}"
              onchange="tuneDelayToggle('${prefix}','${f.id}')">
            <span>${f.label}</span>
            <span style="font-size: 0.72rem; color: #5a7898">${f.hint}</span>
          </label>
          <input type="number" id="${prefix}-${f.id}"
            value="${val}" min="${f.min}" max="${f.max}" step="1"
            ${checked ? "" : "disabled"}
            aria-label="${f.label} value (${f.min}-${f.max})"
            style="
              font-family: var(--mono);
              font-size: 0.85rem;
              background: var(--surface2);
              border: 1px solid var(--border2);
              border-radius: 0.3rem;
              padding: 0.3rem 0.5rem;
              width: 6rem;
              color: var(--text)"
            onchange="tuneDelayInput('${prefix}','${f.id}')"
            oninput="tuneDelayInput('${prefix}','${f.id}')">
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

  const tipText = driver === "usbradio"
    ? "RX values set receive levels and squelch; TX values set transmit levels, CTCSS, and bandwidth."
    : "RX adjusts input levels. TX adjusts output levels for each channel.";

  const defaultInfo = driver === "simpleusb" ? `
      <div style="
        font-size: 0.8rem;
        color: #fff;
        padding: 0.8rem;
        background: rgba(60,180,200,0.08);
        border-radius: 0.3rem;
        border-left: 3px solid var(--teal);
        line-height: 1.4">
        <strong>ℹ Default:</strong> Radio 1 preset is applied on startup.
      </div>` : "";

  body.innerHTML = `
    <div style="display: grid; gap: 1.4rem; padding: 1rem">

      
      <div style="
        padding: 0.8rem;
        background: rgba(100,120,140,0.08);
        border-radius: 0.4rem;
        font-size: 0.85rem;
        border-left: 3px solid var(--blue)">
        <div style="color: #3a5278; font-weight: 500; margin-bottom: 0.2rem">USB Device</div>
        <div style="font-family: var(--mono); color: var(--blue)">${esc(s.devstr || "—")}</div>
      </div>

      ${fieldHtml}
      ${feverHtml}
      ${boolFieldsHtml}
      ${numberFieldsHtml}

      
      <div style="display: flex; gap: 0.4rem; flex-wrap: wrap; margin-top: 0.5rem">
        <button class="btn btn-blue btn-sm" id="${prefix}-save-btn"
          onclick="openTuneSaveDialog('${driver}')"
          title="Save — choose preset and reload options">
          💾 Save
        </button>
        <button class="btn btn-muted btn-sm" id="${prefix}-reset-btn"
          onclick="resetTuneCard('${driver}')"
          title="Revert to server values without saving">
          ↺ Reset
        </button>
        <span id="${prefix}-dirty-indicator" style="display:none;font-size:0.8rem;color:var(--amber);align-self:center">● unsaved changes</span>
      </div>

      
      <div style="
        font-size: 0.8rem;
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

function tuneSlide(prefix, fieldId) {
  const spec = tuneFieldSpec(prefix, fieldId);
  const sl = document.getElementById(`${prefix}-${fieldId}`);
  if (!spec || !sl) return;
  const v = parseFloat(sl.value);
  const pct = ((v - spec.min) / (spec.max - spec.min)) * 100;
  const box = document.getElementById(`${prefix}-${fieldId}-val`);
  if (box) box.value = spec.dec ? v.toFixed(spec.dec) : String(v);
  sl.setAttribute("aria-valuenow", sl.value);
  sl.style.background =
    `linear-gradient(to right, ${spec.color} 0%, ${spec.color} ${pct}%, #ddd ${pct}%, #ddd 100%)`;
  checkTuneDirty(prefix);
}

function tuneNumberInput(prefix, fieldId) {
  const spec = tuneFieldSpec(prefix, fieldId);
  const box  = document.getElementById(`${prefix}-${fieldId}-val`);
  const sl   = document.getElementById(`${prefix}-${fieldId}`);
  if (!spec || !box || !sl) return;
  let v = parseFloat(box.value);
  if (!Number.isFinite(v)) return;   // mid-typing / not parseable yet — leave slider alone
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
  checkTuneDirty(prefix);
}

// RX/TX Delay checkbox+number pairs. Not routed through tuneFieldSpec()
// (that helper is scoped to cfg.fields, the slider set) — looked up
// directly against cfg.numberFields instead.
function tuneDelaySpec(prefix, fieldId) {
  const cfg = TUNE_DRIVERS[tuneDriverForPrefix(prefix)];
  return (cfg.numberFields || []).find(f => f.id === fieldId);
}

function tuneDelayToggle(prefix, fieldId) {
  const cb  = document.getElementById(`${prefix}-${fieldId}-enable`);
  const box = document.getElementById(`${prefix}-${fieldId}`);
  if (!cb || !box) return;
  box.disabled = !cb.checked;
  if (!cb.checked) {
    // Unchecked always defaults to 0, matching simpleusb.conf's own
    // "0 = disabled" convention for rxondelay/txoffdelay.
    box.value = "0";
  }
  checkTuneDirty(prefix);
}

function tuneDelayInput(prefix, fieldId) {
  const spec = tuneDelaySpec(prefix, fieldId);
  const box  = document.getElementById(`${prefix}-${fieldId}`);
  if (!spec || !box) return;
  let v = parseInt(box.value, 10);
  if (!Number.isFinite(v)) return;   // mid-typing — leave alone until it parses
  if (v < spec.min) v = spec.min;
  if (v > spec.max) v = spec.max;
  box.value = String(v);
  checkTuneDirty(prefix);
}

function resetTuneCard(driver) {
  const cfg    = TUNE_DRIVERS[driver];
  const prefix = tunePrefix(driver);
  const orig   = window[`${prefix}_original_values`];
  if (!orig) return;
  for (const f of cfg.fields) {
    if (orig[f.id] === undefined) continue;
    const sl = document.getElementById(`${prefix}-${f.id}`);
    if (sl) { sl.value = orig[f.id]; tuneSlide(prefix, f.id); }
  }
  if (cfg.fever) {
    const fev = document.getElementById(`${prefix}-fever`);
    if (fev && orig.fever !== undefined) fev.value = String(orig.fever);
  }
  // Stage 8 — reset the "Simpleusb Advanced Settings" checkboxes back to
  // their server-loaded state, same pattern as the fever <select> above.
  if (cfg.boolFields) {
    for (const f of cfg.boolFields) {
      if (orig[f.id] === undefined) continue;
      const cb = document.getElementById(`${prefix}-${f.id}`);
      if (cb) cb.checked = orig[f.id] === "yes";
    }
  }
  // "RX/TX Delay" checkbox+number pairs: restore both the number value and
  // the checkbox-checked state from server values, and re-sync the number
  // input's disabled state to match — same pattern as the boolFields block
  // above, just with a paired checkbox+input instead of a single checkbox.
  if (cfg.numberFields) {
    for (const f of cfg.numberFields) {
      if (orig[f.id] === undefined) continue;
      const cb  = document.getElementById(`${prefix}-${f.id}-enable`);
      const box = document.getElementById(`${prefix}-${f.id}`);
      if (cb)  cb.checked = orig[f.id] > 0;
      if (box) { box.value = String(orig[f.id]); box.disabled = !(orig[f.id] > 0); }
    }
  }
  checkTuneDirty(prefix);
  toast("Reset to server values", 1);
}

function getTuneValues(driver) {
  const cfg    = TUNE_DRIVERS[driver];
  const prefix = tunePrefix(driver);
  const out = {};
  for (const f of cfg.fields) {
    const el = document.getElementById(`${prefix}-${f.id}`);
    if (!el || el.value === "") continue;
    out[f.id] = f.dec ? parseFloat(el.value) : parseInt(el.value);
  }
  if (cfg.fever) {
    const fev = document.getElementById(`${prefix}-fever`);
    if (fev) out.fever = parseInt(fev.value);
  }
  // Stage 8 — read the "Simpleusb Advanced Settings" checkboxes into
  // "yes"/"no" strings, matching simpleusb.conf's own convention and what
  // the backend (Stages 3-4) expects on save.
  if (cfg.boolFields) {
    for (const f of cfg.boolFields) {
      const cb = document.getElementById(`${prefix}-${f.id}`);
      if (cb) out[f.id] = cb.checked ? "yes" : "no";
    }
  }
  // "RX/TX Delay" checkbox+number pairs. Unchecked always emits 0 regardless
  // of whatever stale number happens to be sitting in the (disabled) input —
  // this is enforced here too, not just in tuneDelayToggle()'s UI-side reset,
  // so a save can never carry a nonzero value for a field the user disabled.
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

function isTuneDirty(driver) {
  const prefix = tunePrefix(driver);
  const orig = window[`${prefix}_original_values`];
  if (!orig) return false;
  const cur = getTuneValues(driver);
  for (const [k, v] of Object.entries(cur)) {
    if (orig[k] === undefined) continue;   // never captured — can't judge
    // Stage 8 — boolFields carry "yes"/"no" strings, not numbers. Number("yes")
    // is NaN and NaN > 0.005 is always false, so the numeric diff below would
    // silently never flag these as dirty. String-compare whenever either side
    // isn't numeric; numeric fields (mixer levels, fever) keep the original
    // tolerance-based compare untouched.
    if (typeof v === "string" || typeof orig[k] === "string") {
      if (String(v) !== String(orig[k])) return true;
      continue;
    }
    if (Math.abs(Number(v) - Number(orig[k])) > 0.005) return true;
  }
  return false;
}

function checkTuneDirty(prefix) {
  const dirty = isTuneDirty(tuneDriverForPrefix(prefix));
  const ind = document.getElementById(prefix + "-dirty-indicator");
  if (ind) ind.style.display = dirty ? "inline" : "none";
  return dirty;
}

window.radioDialogSlot = null;
window.radioDialogMode = null;     // "capture" | "tunesave"
window.radioDialogDriver = null;   // "simpleusb" | "usbradio" — tunesave mode
window._tuneReloadChoice = false;  // Stage 2: remembered for the session

async function loadRadioPresets() {
  try {
    const result = await api("/api/radio/presets");
    if (!result || !result.ok) {
      console.warn("Failed to load radio presets");
      window.radioPresets = {};
      return;
    }
    window.radioPresets = result.presets || {};
    window.radioTune = result.tune || { active_slot: 0, active_driver: "", simpleusb: {}, usbradio: {} };
    renderRadioPresets(window.radioPresets);
  } catch (e) {
    console.error("Error loading radio presets:", e);
    window.radioPresets = {};
    window.radioTune = { active_slot: 0, active_driver: "", simpleusb: {}, usbradio: {} };
  }
}

function restoreActiveRadioButton() {
  const tune = window.radioTune;
  const currentDrv = window.radioDriver?.active || null;
  const slot = tune?.active_slot || 0;
  const drvMatch = slot >= 1 && slot <= 5 &&
                   currentDrv && tune.active_driver === currentDrv;
  setActiveRadioButton(drvMatch ? slot : 0);   // 0 → clear all highlights
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
    if (mirror[k] === undefined) continue;   // never mirrored — can't judge
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

function renderRadioPresets(presets) {
  const tbody = document.getElementById("rp-rows");
  if (!tbody) return;

  const EXTRA = ["txctcssadj", "rxsquelchadj", "rxvoiceadj", "rxctcssadj", "txslimsp"];
  const drv = window.radioDriver;
  const noDriver = !!(drv && drv.none);

  let html = "";
  for (let slot = 1; slot <= 5; slot++) {
    const preset = presets[slot];
    const populated = preset && preset.rxmixerset !== undefined;

    if (!populated) {
      html += `
      <tr style="border-bottom:1px solid var(--border2)">
        <td style="padding:.4rem;font-weight:500">Radio ${slot}
          <span style="color:#8a9bb0;font-weight:400">(empty)</span></td>
        <td style="padding:.4rem;text-align:center;color:#8a9bb0">—</td>
        <td style="padding:.4rem;color:#8a9bb0">—</td>
        <td style="padding:.4rem;text-align:center">
          <button class="btn btn-sm" style="background:var(--amber);color:#000;font-weight:500"
            onclick="overwriteRadioPreset(${slot})" ${noDriver ? "disabled" : ""}
            title="${noDriver ? "No radio channel driver loaded" : "Capture the active driver's live values into this slot"}">📌 Save live</button>
        </td>
      </tr>`;
      continue;
    }

    const extras = EXTRA.filter(f => preset[f] !== undefined);
    const isUR = extras.length > 0;
    const typeLabel = isUR ? "USBRadio" : "SimpleUSB";
    const typeColor = isUR ? "var(--orange)" : "var(--blue)";

    const base = `RX ${preset.rxmixerset} · TXA ${preset.txmixaset} · TXB ${preset.txmixbset}`;
    const extraNote = extras.length ? ` · +${extras.length}` : "";
    const fullTip = Object.keys(preset)
      .filter(k => k !== "title")
      .map(k => `${k}=${preset[k]}`)
      .join(", ");
    const titleLine = preset.title
      ? `<div style="color:#8a9bb0;font-weight:400;font-size:.82rem">${esc(preset.title)}</div>` : "";

    html += `
      <tr style="border-bottom:1px solid var(--border2)">
        <td style="padding:.4rem;font-weight:500">Radio ${slot}${titleLine}</td>
        <td style="padding:.4rem;text-align:center">
          <span style="font-size:.74rem;font-weight:600;color:${typeColor};
            border:1px solid ${typeColor};border-radius:.6rem;padding:.05rem .4rem;white-space:nowrap">${typeLabel}</span>
        </td>
        <td style="padding:.4rem;font-family:var(--mono);font-size:.82rem" title="${esc(fullTip)}">${base}${extraNote}</td>
        <td style="padding:.4rem;text-align:center;white-space:nowrap">
          <button class="btn btn-green btn-sm" onclick="applyRadioPreset(${slot})"
            ${noDriver ? "disabled" : ""}
            title="${noDriver ? "No radio channel driver loaded" : "Apply to the active driver & restart Asterisk"}">▶ Apply</button>
          <button class="btn btn-sm" style="background:var(--amber);color:#000;font-weight:500"
            onclick="overwriteRadioPreset(${slot})" ${noDriver ? "disabled" : ""}
            title="${noDriver ? "No radio channel driver loaded" : "Overwrite with the active driver's live values"}">📌</button>
          <button class="btn btn-muted btn-sm" onclick="clearRadioPreset(${slot})"
            title="Clear this slot">✕</button>
        </td>
      </tr>`;
  }
  tbody.innerHTML = html;
}

function overwriteRadioPreset(slot) {
  const active = window.radioDriver?.active || null;
  if (!active) {
    toast("⚠ No radio channel driver loaded", 0);
    return;
  }
  saveRadioDialog(slot, active === "usbradio" ? "ur" : "su");
}

async function clearRadioPreset(slot) {
  const preset = window.radioPresets?.[slot];
  const name = preset?.title || `Radio ${slot}`;
  if (!await confirm(`Clear preset "${name}"? This cannot be undone.`)) return;
  try {
    const result = await api("/api/radio/presets", "POST", { slot: slot, clear: true });
    if (!result || !result.ok) {
      toast(`✗ Failed: ${result?.message || "unknown error"}`, 0);
      return;
    }
    toast(`✓ ${result.message}`, 2);
    await loadRadioPresets();
    renderRadioPresets(window.radioPresets);
    updateRadioButtons();
  } catch (e) {
    toast(`✗ Error: ${e.message}`, 0);
  }
}

function showRadioDialogFormView() {
  document.getElementById("radio-dialog-form-view").style.display = "block";
  document.getElementById("radio-dialog-restart-view").style.display = "none";
}

function showRadioDialogError(msg) {
  const el = document.getElementById("radio-dialog-error");
  if (el) { el.textContent = "✗ " + msg; el.style.display = "block"; }
}

function saveRadioDialog(slot, source) {
  window.radioDialogMode = "capture";
  window.radioDialogSlot = slot;
  window.radioDialogSource = (source === "ur") ? "ur" : "su";
  window.radioDialogDriver = null;

  document.getElementById("radio-dialog-hdr").textContent = "Save to Radio Preset";
  document.getElementById("radio-dialog-preset-row").style.display = "none";
  document.getElementById("radio-dialog-reload-row").style.display = "none";
  document.getElementById("radio-dialog-error").style.display = "none";
  document.getElementById("radio-dialog-save-btn").textContent = "Save";

  const titleInput = document.getElementById("radio-dialog-title");
  titleInput.parentElement.style.display = "";
  const preset = window.radioPresets?.[slot];
  titleInput.value = preset?.title ?? "";
  const msg = document.getElementById("radio-dialog-msg");
  if (msg) {
    msg.textContent = window.radioDialogSource === "ur"
      ? "Name this preset (captures all USBRadio tune values):"
      : "Enter a name for this preset:";
  }
  showRadioDialogFormView();
  document.getElementById("radio-dialog-overlay").style.display = "flex";
  setTimeout(() => titleInput.focus(), 100);
}

function openTuneSaveDialog(driver) {
  if (!isTuneDirty(driver)) {
    toast("No changes to save", 1);
    return;
  }

  window.radioDialogMode = "tunesave";
  window.radioDialogDriver = driver;
  window.radioDialogSlot = null;
  window.radioDialogSource = null;

  document.getElementById("radio-dialog-hdr").textContent =
    driver === "usbradio" ? "Save USBRadio Tune" : "Save SimpleUSB Tune";
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
  tuneDialogPresetChanged();   // sync title-field relevance + pre-fill to the preselection

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
  window._tuneReloadChoice = !!on;   // remembered for the rest of the session
  const warn = document.getElementById("radio-dialog-reload-warn");
  if (warn) warn.style.display = on ? "block" : "none";
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
  const source = window.radioDialogSource || "su";
  const title = document.getElementById("radio-dialog-title")?.value?.trim() || "";

  const driver = source === "ur" ? "usbradio" : "simpleusb";
  const payload = {
    slot: slot,
    title: title,
    driver: driver,
    ...getTuneValues(driver),
  };
  delete payload.fever;

  try {
    const result = await api("/api/radio/presets", "POST", payload);
    if (!result || !result.ok) {
      toast(`✗ Failed: ${result?.message || "unknown error"}`, 0);
      return;
    }

    toast(`✓ ${result.message}`, 2);
    closeRadioDialog();

    await loadRadioPresets();
    renderRadioPresets(window.radioPresets);
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

  const fields  = getTuneValues(driver);
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
      refreshTuneCardAfterSave(driver);
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
      refreshTuneCardAfterSave(driver);
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

function refreshTuneCardAfterSave(driver) {
  if (driver === "usbradio") loadUsbradioTune(); else loadSimpleUSBTune();
  loadRadioPresets().then(() => {
    renderRadioPresets(window.radioPresets || {});
    updateRadioButtons();
    restoreActiveRadioButton();
  });
}

function updateRadioButtons() {
  const presets = window.radioPresets || {};
  const drv = window.radioDriver;
  const noDriver = !!(drv && drv.none);   // only "no driver" once actually checked
  const drvLabel = drv?.active === "usbradio" ? "USBRadio"
                 : drv?.active === "simpleusb" ? "SimpleUSB"
                 : "active driver";

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
      btn.title = `Apply ${preset.title || `Radio ${slot}`} → ${drvLabel}: ` +
                  `RX=${preset.rxmixerset}, TX-A=${preset.txmixaset}, TX-B=${preset.txmixbset}` +
                  (stale ? " — current settings have been changed since this preset was applied" : "");
    } else if (populated && noDriver) {
      btn.disabled = true;
      btn.classList.add("empty");
      btn.textContent = preset.title || `Radio ${slot}`;
      btn.title = "No radio channel driver loaded (chan_simpleusb / chan_usbradio)";
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
    toast("⚠ No radio channel driver loaded (chan_simpleusb / chan_usbradio)", 0);
    updateRadioButtons();   // reflect disabled state
    return;
  }
  if (drv.both && !window._radioBothWarned) {
    toast("⚠ Both channel drivers loaded — applying to USBRadio", 0);
    window._radioBothWarned = true;
  }

  let endpoint, payload, cardPrefix, refreshFn;
  if (active === "usbradio") {
    endpoint   = "/api/usbradio/save";
    cardPrefix = "ur";
    refreshFn  = loadUsbradioTune;
    payload    = { reload: true, slot: slot };   // slot → backend persists active_slot
    for (const f of ["rxmixerset", "txmixaset", "txmixbset", "txctcssadj",
                     "rxsquelchadj", "rxvoiceadj", "rxctcssadj", "txslimsp"]) {
      if (preset[f] !== undefined) payload[f] = preset[f];
    }
  } else {
    endpoint   = "/api/simpleusb/tune";
    cardPrefix = "su";
    refreshFn  = loadSimpleUSBTune;
    payload    = {
      rxmixerset: preset.rxmixerset,
      txmixaset:  preset.txmixaset,
      txmixbset:  preset.txmixbset,
      reload:     true,
      slot:       slot,   // → backend persists active_slot
    };
  }

  const body = document.getElementById(`${cardPrefix}-tune-body`);
  const isCardVisible = body && body.offsetParent !== null;

  if (isCardVisible) {
    const rxId  = active === "usbradio" ? "ur-rxmixerset" : "su-rxmixerset";
    const txaId = active === "usbradio" ? "ur-txmixaset"  : "su-txmixaset";
    const txbId = active === "usbradio" ? "ur-txmixbset"  : "su-txmixbset";
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
      updateRadioButtons();          // clears any stale "*" from before
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

// ---- TUNE TAB implementation ends above this line. ----
//
// ---- ASL-DVS tab, part 3 of 3 (Asterisk config: renderAstFiles/
// openAstEditor). loadAstFiles(), which calls renderAstFiles() below,
// is back in part 1 -- see that comment for the full picture. ----
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
      dim.style.cssText = "color:#fff;font-size:.66rem;margin-left:.5rem";
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

      checks.forEach(c => {
        if (c.title.startsWith("[")) {
          const lbl = document.createElement("div");
          lbl.style.cssText =
            "font-family:var(--mono);font-size:.66rem;letter-spacing:.15em;" +
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
          badge.className   = "ast-check-pass";
          badge.textContent = "[PASS]";
        } else if (c.status === "fail") {
          badge.className   = "ast-check-fail";
          badge.textContent = "[FAIL]";
        } else if (c.status === "info") {
          badge.className   = "ast-check-info";
          badge.textContent = "[INFO]";
        } else {
          badge.className   = "ast-check-none";
          badge.textContent = "[NONE]";
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
            a.href   = c.url;
            a.target = "_blank";
            a.rel    = "noopener noreferrer";
            a.className   = "ast-check-link";
            a.textContent = c.note;
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
      body.appendChild(cb);
    }

    if (portLines.length) {
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
      body.appendChild(pl);
    }
  });
}

async function openAstEditor(name) {
  
  _ufUnit = "\x00ast:" + name;   // sentinel prefix — distinguishes from unit files

  document.getElementById("dpanel")?.style.setProperty("--panel-accent", "var(--red)");
  document.getElementById("uf-overlay").style.setProperty("--uf-accent", "var(--red)");

  document.getElementById("uf-title").textContent      = `✎ ${name}`;
  document.getElementById("uf-path").textContent       = `/etc/asterisk/${name}`;
  document.getElementById("uf-textarea").value         = "";
  document.getElementById("uf-status").textContent     = "";
  document.getElementById("uf-promoted-bar").classList.remove("show");
  document.getElementById("uf-save-btn").disabled      = true;
  document.getElementById("uf-restart-btn").disabled   = true;
  document.getElementById("uf-restart-btn").style.display = "none";
  document.getElementById("uf-overlay").classList.add("open");

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

// ---- END ASL-DVS tab (all three parts). SHARED uf-editor save
// dispatcher resumes below -- see the SHARED uf-editor comment near
// the top of this file for the full picture (openUnitFileEditor()
// etc.). ufSave() is the actual handler wired to the Save button;
// it dispatches by _ufUnit's sentinel prefix to each ASL-DVS config
// category's own save logic, falling back to _ufSaveOrig() (defined
// with the rest of the shared core, above) for plain unit files. ----
async function ufSave() {
  if (_ufUnit.startsWith("\x00ast:")) {
    const name = _ufUnit.slice(5);
    if (!await confirm(`Save changes to ${name}?\n\nThis overwrites /etc/asterisk/${name} on disk.`)) return;
    const content = document.getElementById("uf-textarea").value;
    const btn     = document.getElementById("uf-save-btn");
    if (btn) btn.disabled = true;
    ufSetStatus("Saving…");
    const d = await api("/api/asterisk/file", "POST", {name, content});
    if (btn) btn.disabled = false;
    if (!d || !d.ok) {
      ufSetStatus(d?.message || "Save failed", false);
      toast(d?.message || "Save failed", "err");
      return;
    }
    ufSetStatus("Saved ✓", true);
    toast(`Saved ${name}`, "ok");
  } else if (_ufUnit.startsWith("\x00dvs:")) {
    const label = _ufUnit.slice(5);
    if (!await confirm(`Save changes to ${label}?\n\nThis overwrites the file on disk.`)) return;
    const content = document.getElementById("uf-textarea").value;
    const btn     = document.getElementById("uf-save-btn");
    if (btn) btn.disabled = true;
    ufSetStatus("Saving…");
    const d = await api("/api/dvswitch/file", "POST", {label, content});
    if (btn) btn.disabled = false;
    if (!d || !d.ok) {
      ufSetStatus(d?.message || "Save failed", false);
      toast(d?.message || "Save failed", "err");
      return;
    }
    ufSetStatus("Saved ✓", true);
    toast(`Saved ${label}`, "ok");
    loadDvsFiles();   // refresh exists flag
  } else if (_ufUnit.startsWith("\x00allmon3:")) {
    const label = _ufUnit.slice(9);
    if (!await confirm(`Save changes to ${label}?\n\nThis overwrites the file on disk.`)) return;
    const content = document.getElementById("uf-textarea").value;
    const btn     = document.getElementById("uf-save-btn");
    if (btn) btn.disabled = true;
    ufSetStatus("Saving…");
    const d = await api("/api/allmon3/file", "POST", {label, content});
    if (btn) btn.disabled = false;
    if (!d || !d.ok) {
      ufSetStatus(d?.message || "Save failed", false);
      toast(d?.message || "Save failed", "err");
      return;
    }
    ufSetStatus("Saved ✓", true);
    toast(`Saved ${label}`, "ok");
    loadAllmon3Files();   // refresh exists flag
  } else if (_ufUnit.startsWith("\x00appconf:")) {
    const label = _ufUnit.slice(9);
    if (!await confirm(`Save changes to ${label}?\n\nThis overwrites the file on disk.`)) return;
    const content = document.getElementById("uf-textarea").value;
    const btn     = document.getElementById("uf-save-btn");
    if (btn) btn.disabled = true;
    ufSetStatus("Saving…");
    const d = await api("/api/appconf/file", "POST", {label, content});
    if (btn) btn.disabled = false;
    if (!d || !d.ok) {
      ufSetStatus(d?.message || "Save failed", false);
      toast(d?.message || "Save failed", "err");
      return;
    }
    ufSetStatus("Saved ✓", true);
    toast(`Saved ${label}`, "ok");
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

// ============================================================
// DVSM TAB -- own implementation: loadDvsm(). _dvsmRenderAccount()/
// _dvsmRenderCompat() are also DVSM's, but not exclusively -- Zello
// reuses both directly (see the pre-existing comment at the start of
// Zello's own section). _dvsmBadgeClass()/_dvsmSetBadge()/dvsmCopy()/
// dvsmCopyAttr()/dvsmCopySecret()/dvsmReveal() are SHARED further
// still -- a small badge/copy/reveal utility library used by all
// four of DVSM, STFU, M17, and Zello, just physically homed here.
// No calls into the dpanel, jp-popup, uf-editor, or diagnostic-test
// engine shared components used elsewhere in this file. Ends where
// the STFU tab's hook begins, just below.
// ============================================================
window.loadTab_dvsm = function() { loadDvsm(); };

const _dvsmRevealed = new Map();
const _dvsmSecrets  = new Map();

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

function dvsmCopySecret(btn, fid) { dvsmCopy(btn, _dvsmSecrets.get(fid) || ""); }

function dvsmReveal(eyeBtn, fid) {
  const el  = document.getElementById(fid);
  if (!el) return;
  const now = !_dvsmRevealed.get(fid);
  _dvsmRevealed.set(fid, now);
  if (now) {
    el.textContent = _dvsmSecrets.get(fid) || "(empty)";
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
        ? `<span style="display:block;font-size:.66rem;color:#fff;margin-top:.1rem">` +
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
    const bc = _dvsmBadgeClass(c.status);
    const bt = _esc((c.status || "—").toUpperCase());
    html += `<tr>` +
            `<td class="dvsm-ct-key">${_esc(c.key)}</td>` +
            `<td class="dvsm-ct-enables">${_esc(c.enables)}</td>` +
            `<td class="dvsm-ct-badge"><span class="dpbadge ${bc}">${bt}</span></td>` +
            `</tr>`;
    
    const sub = c.fix || (c.status === "info" && c.value ? c.value : null);
    if (sub) {
      html += `<tr class="dvsm-ct-fix-row"><td colspan="3" class="dvsm-ct-fix">&#x21B3; ${_esc(sub)}</td></tr>`;
    }
  });
  if (curFile !== null) html += `</table>`;
  body.innerHTML = html;
}

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

// ---- END DVSM tab implementation. ----

window.loadTab_stfu = function() { loadStfu(); };
window.loadTab_m17  = function() { loadM17(); };

// ============================================================
// STFU + M17 -- interleaved implementation region. These two tabs'
// functions are woven together across the next ~900 lines, in this
// order: STFU part 1 (state/reveal/render/copyStanza) -> M17's own
// implementation in full -> STFU part 2 (editor actions) -> M17's
// loadM17() -> STFU part 3 (loadStfu()). Each STFU piece is marked
// "STFU tab, part N of 3" below; M17's own pieces are marked but not
// otherwise touched -- M17 gets its own stage. Neither tab calls into
// the dpanel, jp-popup, uf-editor, or diagnostic-test engine shared
// components used elsewhere in this file.
// ============================================================

// ---- STFU tab, part 1 of 3 (state, reveal/copy-secret, the four
// _stfuRender* functions, stfuCopyStanza). Part 2 resumes after all
// of M17's own implementation, just below. ----
const _stfuSecrets  = new Map();
const _stfuRevealed = new Map();

let _stfuSampleText = "";

let _stfuDvsPath = "";

let _stfuLoadedContent = null;

// ---- M17 tab's own state (interleaved here, inside what's labeled
// "STFU tab, part 1" above -- these three lines belong to M17, not
// STFU; see "M17 tab, part 1" further down for the rest of M17's
// implementation). ----
let _m17SampleText = "";
let _m17IniPath = "";
let _m17LoadedContent = null;
// ---- back to STFU tab, part 1 (state/reveal/copy-secret). ----

function _stfuCopySecret(btn, fid) {
  dvsmCopy(btn, _stfuSecrets.get(fid) || "");
}

function _stfuReveal(eyeBtn, fid) {
  const el  = document.getElementById(fid);
  if (!el) return;
  const now = !_stfuRevealed.get(fid);
  _stfuRevealed.set(fid, now);
  if (now) {
    el.textContent = _stfuSecrets.get(fid) || "(empty)";
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

function _stfuRenderInstall(bodyId, badgeId, inst) {
  
  const allOk  = inst.binary_ok && inst.service_installed && inst.service_active;
  const anyOk  = inst.binary_ok || inst.service_installed;
  const status = allOk ? "pass" : anyOk ? "warn" : "fail";
  _dvsmSetBadge(badgeId, status);

  const body = document.getElementById(bodyId);
  if (!body) return;

  const row = (key, enables, ok, fixMsg) => {
    const bc = _dvsmBadgeClass(ok ? "pass" : (fixMsg ? "warn" : "fail"));
    const bt = ok ? "PASS" : (fixMsg ? "WARN" : "FAIL");
    let html = `<tr>` +
      `<td class="dvsm-ct-key">${_esc(key)}</td>` +
      `<td class="dvsm-ct-enables">${_esc(enables)}</td>` +
      `<td class="dvsm-ct-badge"><span class="dpbadge ${bc}">${bt}</span></td>` +
      `</tr>`;
    if (!ok && fixMsg) {
      html += `<tr class="dvsm-ct-fix-row">` +
              `<td colspan="3" class="dvsm-ct-fix">&#x21B3; ${_esc(fixMsg)}</td>` +
              `</tr>`;
    }
    return html;
  };

  let html = `<table class="dvsm-compat-tbl">`;
  html += row(
    inst.binary_path || "/opt/STFU/STFU",
    "Binary present and executable",
    inst.binary_ok,
    inst.binary_ok ? null : "Download STFU.armhf from DVSwitch GitHub → copy to /opt/STFU/STFU → chmod +x"
  );
  html += row(
    inst.service_path || "stfu.service",
    "systemd unit installed",
    inst.service_installed,
    inst.service_installed ? null : "Copy stfu.service to /lib/systemd/system/ → systemctl daemon-reload"
  );
  html += row(
    "Service active",
    "systemctl is-active stfu",
    inst.service_active,
    (!inst.service_active && inst.service_installed)
      ? "systemctl start stfu"
      : (!inst.service_active ? "Install service first" : null)
  );
  html += `</table>`;
  body.innerHTML = html;
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
  let inTbl  = false;   // tracks whether a <table> is currently open
  let cardKey = 0;      // unique key per field for secret Map ids

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
        ? `<span style="display:block;font-size:.66rem;color:#fff;margin-top:.1rem">` +
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
  const body = document.getElementById(bodyId);
  if (!body) return;

  
  const highlighted = rawText
    .split("\n")
    .map(line => {
      if (/^\s*;/.test(line))
        return `<span style="color:#fff">${_esc(line)}</span>`;
      const secM = line.match(/^(\[.+?\])(.*)/);
      if (secM)
        return `<span class="stfu-ini-section">${_esc(secM[1])}</span>` +
               `<span style="color:#fff">${_esc(secM[2])}</span>`;
      const kvM = line.match(/^([^=]+)(=)(.*)/);
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

function _stfuRenderCompat(bodyId, compat) {
  const body = document.getElementById(bodyId);
  if (!body) return;
  if (!compat || !compat.length) {
    body.innerHTML = `<div class="stub-panel" style="min-height:40px">No checks available</div>`;
    return;
  }
  let html = `<table class="dvsm-compat-tbl">`;
  compat.forEach(c => {
    const bc = _dvsmBadgeClass(c.status);
    const bt = _esc((c.status || "—").toUpperCase());
    html += `<tr>` +
            `<td class="dvsm-ct-key">${_esc(c.key)}</td>` +
            `<td class="dvsm-ct-enables">${_esc(c.enables)}</td>` +
            `<td class="dvsm-ct-badge"><span class="dpbadge ${bc}">${bt}</span></td>` +
            `</tr>`;
    if (c.fix) {
      html += `<tr class="dvsm-ct-fix-row">` +
              `<td colspan="3" class="dvsm-ct-fix">&#x21B3; ${_esc(c.fix)}</td>` +
              `</tr>`;
    }
  });
  html += `</table>`;
  body.innerHTML = html;
}

function stfuCopyStanza(btn) {
  dvsmCopy(btn, _stfuSampleText);
  
  const orig = btn.textContent;
  btn.textContent = "✓ Copied";
  setTimeout(() => { btn.textContent = orig; }, 1400);
}

// ============================================================
// M17 tab, part 1 of 2 (render functions _m17RenderInstall/
// _m17RenderConfig/_m17RenderCompat/_m17RenderSample, plus
// m17CopyStanza/m17Restart/m17OpenEditor/m17ToggleEditor/m17Save/
// m17Copy/m17DiscardEdit). Own state (_m17SampleText/_m17IniPath/
// _m17LoadedContent) sits further up, inside STFU's part 1 block --
// see the note there. Uses the shared _dvsmSetBadge()/dvsmCopy()
// helpers homed in the DVSM tab's section; no calls into the dpanel,
// jp-popup, uf-editor, or diagnostic-test engine. STFU part 2
// resumes right after this block ends, at stfuOpenEditor(); M17's
// own part 2 (just loadM17()) resumes after that.
// ============================================================
function _m17RenderInstall(bodyId, badgeId, inst) {
  const allOk  = inst.binary_ok && inst.service_installed && inst.service_active;
  const anyOk  = inst.binary_ok || inst.service_installed;
  const status = allOk ? "pass" : anyOk ? "warn" : "fail";
  _dvsmSetBadge(badgeId, status);

  const body = document.getElementById(bodyId);
  if (!body) return;

  const row = (key, enables, ok, fixMsg) => {
    const bc = _dvsmBadgeClass(ok ? "pass" : (fixMsg ? "warn" : "fail"));
    const bt = ok ? "PASS" : (fixMsg ? "WARN" : "FAIL");
    let html = `<tr>` +
      `<td class="dvsm-ct-key">${_esc(key)}</td>` +
      `<td class="dvsm-ct-enables">${_esc(enables)}</td>` +
      `<td class="dvsm-ct-badge"><span class="dpbadge ${bc}">${bt}</span></td>` +
      `</tr>`;
    if (!ok && fixMsg) {
      html += `<tr class="dvsm-ct-fix-row">` +
              `<td colspan="3" class="dvsm-ct-fix">&#x21B3; ${_esc(fixMsg)}</td>` +
              `</tr>`;
    }
    return html;
  };

  let html = `<table class="dvsm-compat-tbl">`;
  html += row(
    inst.binary_path || "/opt/USRP2M17/USRP2M17",
    "Binary present and executable",
    inst.binary_ok,
    inst.binary_ok ? null : "See USRP2M17 Bridge Manual §5 — build/install USRP2M17 to /opt/USRP2M17/"
  );
  html += row(
    inst.service_path || "usrp2m17.service",
    "systemd unit installed",
    inst.service_installed,
    inst.service_installed ? null : "Copy usrp2m17.service to /lib/systemd/system/ → systemctl daemon-reload"
  );
  html += row(
    "Service active",
    "systemctl is-active usrp2m17",
    inst.service_active,
    (!inst.service_active && inst.service_installed)
      ? "systemctl start usrp2m17"
      : (!inst.service_active ? "Install service first" : null)
  );
  html += `</table>`;
  body.innerHTML = html;
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

  // M17 fields never carry a masked/secret value (no passwords in
  // USRP2M17.ini), so this renderer skips STFU's reveal/eye machinery.
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
      ? `<span style="display:block;font-size:.66rem;color:#fff;margin-top:.1rem">` +
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
  const body = document.getElementById(bodyId);
  if (!body) return;
  if (!compat || !compat.length) {
    body.innerHTML = `<div class="stub-panel" style="min-height:40px">No checks available</div>`;
    return;
  }
  let html = `<table class="dvsm-compat-tbl">`;
  compat.forEach(c => {
    const bc = _dvsmBadgeClass(c.status);
    const bt = _esc((c.status || "—").toUpperCase());
    html += `<tr>` +
            `<td class="dvsm-ct-key">${_esc(c.key)}</td>` +
            `<td class="dvsm-ct-enables">${_esc(c.enables)}</td>` +
            `<td class="dvsm-ct-badge"><span class="dpbadge ${bc}">${bt}</span></td>` +
            `</tr>`;
    if (c.fix) {
      html += `<tr class="dvsm-ct-fix-row">` +
              `<td colspan="3" class="dvsm-ct-fix">&#x21B3; ${_esc(c.fix)}</td>` +
              `</tr>`;
    }
  });
  html += `</table>`;
  body.innerHTML = html;
}

function _m17RenderSample(bodyId, rawText) {
  _m17SampleText = rawText;
  const body = document.getElementById(bodyId);
  if (!body) return;

  const highlighted = rawText
    .split("\n")
    .map(line => {
      if (/^\s*;/.test(line))
        return `<span style="color:#fff">${_esc(line)}</span>`;
      const secM = line.match(/^(\[.+?\])(.*)/);
      if (secM)
        return `<span class="stfu-ini-section">${_esc(secM[1])}</span>` +
               `<span style="color:#fff">${_esc(secM[2])}</span>`;
      const kvM = line.match(/^([^=]+)(=)(.*)/);
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
  if (opening) m17OpenEditor();   // load content on first open
}

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

function m17DiscardEdit() {
  const wrap   = document.getElementById("m17-editor-wrap");
  const togBtn = document.getElementById("m17-editor-toggle");
  const ta     = document.getElementById("m17-textarea");
  if (wrap)   wrap.classList.remove("open");
  if (togBtn) togBtn.textContent = "▼ Expand";
  if (ta)     ta.value = "";
}

// ---- M17 tab implementation ends above this line. ----
//
// ---- STFU tab, part 2 of 3 (editor actions: stfuOpenEditor/
// stfuToggleEditor/stfuSave/stfuRestart/stfuCopy/stfuDiscardEdit).
// Part 3 (just loadStfu()) resumes after M17's own loadM17(), just
// below. ----
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
  if (opening) stfuOpenEditor();   // load content on first open
}

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

async function stfuRestart() {
  if (!await confirm("Restart STFU service?")) return;
  const d = await api("/api/stfu", "POST", {action: "restart"});
  if (!d || !d.ok) { toast(d?.message || "Restart failed", "err"); return; }
  toast("STFU restarted", "ok");
}

async function stfuCopy() {
  const ta = document.getElementById("stfu-textarea");
  if (!ta || !ta.value) { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(ta.value);
}

function stfuDiscardEdit() {
  const wrap   = document.getElementById("stfu-editor-wrap");
  const togBtn = document.getElementById("stfu-editor-toggle");
  const ta     = document.getElementById("stfu-textarea");
  if (wrap)   wrap.classList.remove("open");
  if (togBtn) togBtn.textContent = "▼ Expand";
  if (ta)     ta.value = "";
}

// ---- STFU tab implementation (part 2) ends above this line. ----
//
// ---- M17 tab, part 2 of 2: loadM17() only. ----
async function loadM17() {
  ["install", "config"].forEach(k =>
    _dvsmSetBadge("m17-badge-" + k, "info", "...")
  );

  const d = await api("/api/m17");
  if (!d || !d.ok) {
    ["install", "config"].forEach(k =>
      _dvsmSetBadge("m17-badge-" + k, "fail", "ERR")
    );
    toast("M17: failed to load config", "warn");
    return;
  }

  _m17RenderInstall("m17-body-install", "m17-badge-install", d.install || {});
  _m17RenderConfig("m17-body-config",  "m17-badge-config",
                    "m17-config-path",  d.config || {});
  _m17RenderCompat("m17-body-compat",  d.compat || []);
  _m17RenderSample("m17-body-sample",  d.sample_stanza || "");
  _m17IniPath = (d.config && d.config.ini_path) || "";
}

// ---- STFU tab, part 3 of 3: loadStfu() only. END of the STFU+M17
// interleaved region -- Zello's own section begins right after this
// function (see its own pre-existing comment there). ----
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

// ============================================================
// ZELLO TAB -- implementation (_zelloRenderInstall/
// _zelloRenderStatus/_zelloRenderSample/zelloCopySample/loadZello/
// zelloOpenEditor/zelloToggleEditor/zelloSave/zelloAction/zelloCopy/
// zelloDiscardEdit). Fully contiguous -- no interleaving with any
// other tab. No calls into the dpanel, jp-popup, uf-editor, or
// diagnostic-test engine, EXCEPT that the HTML panel's "Full
// Journal" button calls the shared openServicePanel() directly (see
// the Services tab's boundary comment) -- not reflected in this
// tab's own JS, just its markup. The pre-existing comment just below
// (from the original author) explains the DVSM-reuse pattern in more
// detail than this one repeats.
// ============================================================
// ---------------------------------------------------------------------
// Zello tab — Stage 6: panel wiring. Config/Compat cards reuse the
// already-generic _dvsmRenderAccount()/_dvsmRenderCompat() renderers (same
// ones the DVSM tab uses) rather than duplicating that table-rendering
// logic a third time. Install/Sample/Editor follow the STFU/M17 per-tab
// convention (own state vars) since those two aren't generic elsewhere
// in this file either.
// ---------------------------------------------------------------------

let _zelloSampleText    = "";
let _zelloOverridePath  = "";
let _zelloLoadedContent = null;

function _zelloRenderInstall(bodyId, badgeId, inst) {
  const allOk  = inst.binary_ok && inst.service_installed && inst.service_active;
  const anyOk  = inst.binary_ok || inst.service_installed;
  const status = allOk ? "pass" : anyOk ? "warn" : "fail";
  _dvsmSetBadge(badgeId, status);

  const body = document.getElementById(bodyId);
  if (!body) return;

  const row = (key, enables, ok, fixMsg) => {
    const bc = _dvsmBadgeClass(ok ? "pass" : (fixMsg ? "warn" : "fail"));
    const bt = ok ? "PASS" : (fixMsg ? "WARN" : "FAIL");
    let html = `<tr>` +
      `<td class="dvsm-ct-key">${_esc(key)}</td>` +
      `<td class="dvsm-ct-enables">${_esc(enables)}</td>` +
      `<td class="dvsm-ct-badge"><span class="dpbadge ${bc}">${bt}</span></td>` +
      `</tr>`;
    if (!ok && fixMsg) {
      html += `<tr class="dvsm-ct-fix-row">` +
              `<td colspan="3" class="dvsm-ct-fix">&#x21B3; ${_esc(fixMsg)}</td>` +
              `</tr>`;
    }
    return html;
  };

  let html = `<table class="dvsm-compat-tbl">`;
  html += row(
    inst.binary_path || "/opt/asl-zello-bridge/venv/bin/asl-zello-bridge",
    "Bridge installed (pip+venv or setup.py)",
    inst.binary_ok,
    inst.binary_ok ? null : "See README — pip+venv install (recommended) or deprecated setup.py"
  );
  html += row(
    inst.service_path || "asl-zello-bridge.service",
    "systemd unit installed",
    inst.service_installed,
    inst.service_installed ? null : "Copy asl-zello-bridge.service to /etc/systemd/system/ → systemctl daemon-reload"
  );
  html += row(
    "Service active",
    "systemctl is-active asl-zello-bridge",
    inst.service_active,
    (!inst.service_active && inst.service_installed)
      ? "systemctl start asl-zello-bridge"
      : (!inst.service_active ? "Install service first" : null)
  );
  html += `</table>`;
  body.innerHTML = html;
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
  const body = document.getElementById(bodyId);
  if (!body) return;

  const highlighted = rawText
    .split("\n")
    .map(line => {
      if (/^\s*#/.test(line))
        return `<span style="color:#fff">${_esc(line)}</span>`;
      const secM = line.match(/^(\[.+?\])(.*)/);
      if (secM)
        return `<span class="stfu-ini-section">${_esc(secM[1])}</span>` +
               `<span style="color:#fff">${_esc(secM[2])}</span>`;
      const kvM = line.match(/^(Environment=[^=]+)(=)(.*)/);
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

  // Cache the real editable content for the editor without forcing it open —
  // openEditor() will re-fetch fresh on demand, same as STFU/M17 do, so a
  // stale cache here is never actually served to the textarea.
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
  loadZello();   // refresh the read-only cards to reflect the new values
}

async function zelloAction(action) {
  const verbs = {start: "Start", stop: "Stop", restart: "Restart"};
  const verb  = verbs[action] || action;
  if (!await confirm(`${verb} asl-zello-bridge?`)) return;
  const d = await api("/api/zello", "POST", {action});
  if (!d || !d.ok) { toast(d?.message || `${verb} failed`, "err"); return; }
  toast(`asl-zello-bridge: ${verb.toLowerCase()}ed`, "ok");
  setTimeout(loadZello, 1200);   // give systemd a beat before re-polling state
}

async function zelloCopy() {
  const ta = document.getElementById("zello-textarea");
  if (!ta || !ta.value) { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(ta.value);
}

function zelloDiscardEdit() {
  const wrap   = document.getElementById("zello-editor-wrap");
  const togBtn = document.getElementById("zello-editor-toggle");
  if (wrap)   wrap.classList.remove("open");
  if (togBtn) togBtn.textContent = "▼ Expand";
  _zelloLoadedContent = null;
}

window.loadTab_zello = function() { loadZello(); };

// ---- END Zello tab implementation. ----


document.addEventListener("DOMContentLoaded", () => {
// Main app bootstrap -- the entry point that starts the whole page:
// restores tab visibility, kicks off the status poll loop via
// startStatusPolling()/resumeAllPolling(), and activates the
// Overview tab. Part of the shared polling system (see SHARED CORE
// at top of file).
  if (sessionStorage.getItem("sysmon_paused_by_nav")) {
    sessionStorage.removeItem("sysmon_paused_by_nav");
    _pausedByNavigation = true;  // Will be cleared by resumeAllPolling below
  }

  const lnk = document.getElementById("lnk-dashboard");
  if (lnk) {
    const port = window.location.port || "8989";
    const host = window.location.hostname;
    const dashboardUrl = `http://${host}:8989/`;
    lnk.href = dashboardUrl;
    lnk.title = "Return to ASL-DVS Dashboard";
  }

  api("/api/config").then(d => {
    if (d && d.ok) {
      _savedEnabledTabs = d.ui?.enabled_tabs || TABS.slice();
      _applyTabVisibilityGated();
    }
  }).catch(() => {});   // visibility is cosmetic — never block init on it

  Promise.all([loadRadioPresets(), loadRadioDriver()]).then(() => {
    updateRadioButtons();
    renderRadioPresets(window.radioPresets || {});
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
});

window.addEventListener("beforeunload", () => {
  stopStatusPolling();
});

</script>

</body>
</html>"""

_HTML_SRC   = _HTML.replace("__VERSION__", VERSION)
_HTML_BYTES = _HTML_SRC.encode("utf-8")
_HTML_GZIP  = gzip.compress(_HTML_BYTES, compresslevel=6)

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

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        handler = _GET_ROUTES.get(path)
        if not handler:
            self.send_response(404)
            self.end_headers()
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
        handler = _POST_ROUTES.get(path)
        if not handler:
            self.send_response(404)
            self.end_headers()
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
    })

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

def _route_log(h: Handler) -> None:
    qs    = parse_qs(urlparse(h.path).query)
    since = int(qs.get("since", ["0"])[0])
    with _log_lock:
        buf   = list(_log_buf)
        total = _log_idx
    oldest = total - len(buf)
    start  = max(0, since - oldest)
    h.send_json({
        "lines":      buf[start:],
        "next_index": total,
    })

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
        })

    h.send_json({"ok": True, "groups": groups})

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

    h.send_json({"ok": True, "output": output, "view": view, **detail})

def _route_ports(h: Handler) -> None:
    qs    = parse_qs(urlparse(h.path).query)
    proto = qs.get("proto", ["both"])[0].strip().lower()
    if proto not in ("both", "tcp", "udp"):
        proto = "both"

    ports = get_open_ports(proto)
    label_ports(ports, _pinned)
    fw_map = _fw_state_map()
    for p in ports:
        p["fw_state"] = fw_map.get(f"{p.get('port')}/{p.get('proto')}", "")
    h.send_json({"ok": True, "ports": ports})

def _route_ports_probe(h: Handler) -> None:
    import urllib.request as _urllib
    import urllib.error   as _urlerr

    qs   = parse_qs(urlparse(h.path).query)
    kind = qs.get("type", ["tcp"])[0].strip().lower()
    port_str = qs.get("port", [""])[0].strip()

    if not port_str.isdigit():
        h.send_json({"ok": False, "message": f"Invalid port: {port_str!r}"}, 400)
        return

    port = int(port_str)

    if kind == "http":
        try:
            url  = f"http://localhost:{port}/"
            req  = _urllib.Request(url, method="GET")
            resp = _urllib.urlopen(req, timeout=4)
            code = resp.getcode()
            ok   = 200 <= code < 400
            h.send_json({"ok": ok,
                         "message": f"HTTP {code} from :{port}"})
        except _urlerr.HTTPError as e:
            h.send_json({"ok": False,
                         "message": f"HTTP {e.code} from :{port}"})
        except Exception as e:
            h.send_json({"ok": False,
                         "message": f"HTTP probe failed: {str(e)[:80]}"})
        return

    if kind in ("tcp", "udp"):
        try:
            if kind == "tcp":
                s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
                s.settimeout(4)
                s.connect(("127.0.0.1", port))
                s.close()
                h.send_json({"ok": True,
                             "message": f"TCP :{port} accepting connections"})
            else:
                s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
                s.settimeout(2)
                s.sendto(b"", ("127.0.0.1", port))
                s.close()
                h.send_json({"ok": True,
                             "message": f"UDP :{port} reachable (no ICMP unreachable)"})
        except Exception as e:
            h.send_json({"ok": False,
                         "message": f"{kind.upper()} :{port} — {str(e)[:80]}"})
        return

    h.send_json({"ok": False, "message": f"Unknown probe type: {kind!r}"}, 400)

def _route_firewall_get(h: Handler) -> None:
    backend    = get_firewall_backend()
    status     = ""
    rules      = []
    raw        = ""
    chain_info = None
    zone_info  = None

    if backend == "ufw":
        status = get_ufw_status()
        raw_rules = get_ufw_rules()

        for r in raw_rules:
            r["service"] = _label_fw_rule(r, _pinned)
        rules = raw_rules
    elif backend == "nft":
        raw = get_raw_ruleset(backend)
        chain_ref = _nft_find_input_chain()
        if chain_ref:
            status = "active"
            tagged = _nft_list_tagged_rules(*chain_ref)
            for r in tagged:
                r["service"] = _label_fw_rule(r, _pinned)
            rules = tagged
            chain_info = {
                "family": chain_ref[0], "table": chain_ref[1], "chain": chain_ref[2],
            }
        else:
            status = "unknown"
    elif backend == "firewalld":
        zone = _firewalld_zone()
        if zone:
            status = "active"
            tagged = _firewalld_list_ports(zone)
            for r in tagged:
                r["service"] = _label_fw_rule(r, _pinned)
            rules = tagged
            raw = _run(["firewall-cmd", f"--zone={zone}", "--list-all"], timeout=6)
            zd = _firewalld_parse_list_all(raw)
            zone_info = {
                "zone":            zone,
                "interfaces":      zd["interfaces"],
                "target":          zd["target"],
                "target_desc":     _fw_target_desc(zd["target"]),
                "rich_rule_count": len(zd["rich_rules"]),
            }
        else:
            status = "unknown"
    elif backend == "iptables":
        raw = get_raw_ruleset(backend)

    h.send_json({
        "ok":               True,
        "backend":          backend,
        "status":           status,
        "rules":            rules,
        "raw":              raw,
        "chain_info":       chain_info,
        "zone_info":        zone_info,
        "cockpit_installed": get_service_installed("cockpit.service"),
    })

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

def _route_firewall_post_nft(h: Handler, data: dict, action: str) -> None:
    chain_ref = _nft_find_input_chain()
    if not chain_ref:
        h.send_json({
            "ok": False,
            "message": ("Could not identify a single base input chain in "
                        "the live nft ruleset (found none, or more than "
                        "one) — refusing to guess which one to mutate. "
                        "Add/remove the rule manually with nft."),
        })
        return
    family, table, chain = chain_ref

    if action in ("allow", "deny"):
        port  = str(data.get("port",  "")).strip()
        proto = str(data.get("proto", "tcp")).strip().lower()
        src   = str(data.get("src",   "Anywhere")).strip()

        if not port.isdigit():
            h.send_json({"ok": False, "message": f"Invalid port: {port!r}"}, 400)
            return
        if proto not in ("tcp", "udp"):
            proto = "tcp"
        if src and src != "Anywhere":
            h.send_json({
                "ok": False,
                "message": ("nft rules added through this tool only support "
                            "source \"Anywhere\" — use the nft CLI directly "
                            "for source-restricted rules."),
            })
            return

        verdict = "accept" if action == "allow" else "drop"
        ok, msg = _nft_add_rule(family, table, chain, port, proto, verdict)
        _log(msg, stderr=not ok)
        h.send_json({"ok": ok, "message": msg})
        return

    if action == "delete":
        num = data.get("rule_num")
        try:
            num = int(num)
        except (TypeError, ValueError):
            h.send_json({"ok": False, "message": "rule_num must be an integer"}, 400)
            return

        ok, msg = _nft_delete_rule(family, table, chain, num)
        _log(msg, stderr=not ok)
        h.send_json({"ok": ok, "message": msg})
        return

    if action in ("enable", "disable", "limit"):
        h.send_json({
            "ok": False,
            "message": f"'{action}' is not supported for the nft backend in this tool.",
        })
        return

    h.send_json({"ok": False, "message": f"Unknown firewall action: {action!r}"}, 400)

def _route_firewall_post_firewalld(h: Handler, data: dict, action: str) -> None:
    zone = _firewalld_zone()
    if not zone:
        h.send_json({
            "ok": False,
            "message": ("Could not determine a single active firewalld "
                        "zone bound to a real interface (found none, or "
                        "more than one) — refusing to guess. Use "
                        "firewall-cmd directly with --zone=<name>."),
        })
        return

    if action in ("allow", "deny"):
        port  = str(data.get("port",  "")).strip()
        proto = str(data.get("proto", "tcp")).strip().lower()
        src   = str(data.get("src",   "Anywhere")).strip()

        if not port.isdigit():
            h.send_json({"ok": False, "message": f"Invalid port: {port!r}"}, 400)
            return
        if proto not in ("tcp", "udp"):
            proto = "tcp"
        if src and src != "Anywhere":
            h.send_json({
                "ok": False,
                "message": ("firewalld rules added through this tool only "
                            "support source \"Anywhere\" — use firewall-cmd "
                            "rich rules directly for source-restricted rules."),
            })
            return

        if action == "allow":
            ok, msg = _firewalld_add_port(zone, port, proto)
        else:
            ok, msg = _firewalld_remove_port(zone, port, proto)
        _log(msg, stderr=not ok)
        h.send_json({"ok": ok, "message": msg})
        return

    if action == "delete":
        spec = str(data.get("rule_num", "")).strip()
        if "/" not in spec:
            h.send_json({"ok": False, "message": f"Invalid rule spec: {spec!r}"}, 400)
            return
        port, proto = spec.split("/", 1)
        ok, msg = _firewalld_remove_port(zone, port, proto)
        _log(msg, stderr=not ok)
        h.send_json({"ok": ok, "message": msg})
        return

    if action in ("enable", "disable", "limit"):
        h.send_json({
            "ok": False,
            "message": f"'{action}' is not supported for the firewalld backend in this tool.",
        })
        return

    h.send_json({"ok": False, "message": f"Unknown firewall action: {action!r}"}, 400)

def _route_firewall_post(h: Handler, data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "root required"}); return

    backend = get_firewall_backend()
    action  = str(data.get("action", "")).strip().lower()

    if backend == "nft":
        _route_firewall_post_nft(h, data, action)
        return

    if backend == "firewalld":
        _route_firewall_post_firewalld(h, data, action)
        return

    if backend != "ufw":
        h.send_json({
            "ok":      False,
            "message": f"Firewall mutations require ufw, nft, or firewalld (detected: {backend})",
        }); return

    if action in ("allow", "deny", "limit"):
        port  = str(data.get("port",  "")).strip()
        proto = str(data.get("proto", "tcp")).strip().lower()
        src   = str(data.get("src",   "Anywhere")).strip()

        if not port.isdigit():
            h.send_json({"ok": False, "message": f"Invalid port: {port!r}"}, 400)
            return
        if proto not in ("tcp", "udp", "any"):
            proto = "tcp"

        rule_spec = f"{port}/{proto}" if proto != "any" else port
        cmd = ["ufw", action, "from", src, "to", "any", "port", port,
               "proto", proto] if src != "Anywhere" \
              else ["ufw", action, rule_spec]

        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        ok  = r.returncode == 0
        msg = f"ufw {action} {rule_spec}: {'OK' if ok else r.stderr.strip() or 'failed'}"
        _log(msg, stderr=not ok)
        h.send_json({"ok": ok, "message": msg})
        return

    if action == "delete":
        num = data.get("rule_num")
        try:
            num = int(num)
        except (TypeError, ValueError):
            h.send_json({"ok": False, "message": "rule_num must be an integer"}, 400)
            return

        r = subprocess.run(
            ["ufw", "delete", str(num)],
            input="y\n", capture_output=True, text=True, timeout=10,
        )
        ok  = r.returncode == 0
        msg = f"ufw delete {num}: {'OK' if ok else r.stderr.strip() or 'failed'}"
        _log(msg, stderr=not ok)
        h.send_json({"ok": ok, "message": msg})
        return

    if action == "enable":
        r = subprocess.run(
            ["ufw", "--force", "enable"],
            capture_output=True, text=True, timeout=10,
        )
        ok  = r.returncode == 0
        msg = f"ufw enable: {'OK' if ok else r.stderr.strip() or 'failed'}"
        _log(msg, stderr=not ok)
        h.send_json({"ok": ok, "message": msg})
        return

    if action == "disable":
        r = subprocess.run(
            ["ufw", "disable"],
            capture_output=True, text=True, timeout=10,
        )
        ok  = r.returncode == 0
        msg = f"ufw disable: {'OK' if ok else r.stderr.strip() or 'failed'}"
        _log(msg, stderr=not ok)
        h.send_json({"ok": ok, "message": msg})
        return

    h.send_json({"ok": False,
                 "message": f"Unknown firewall action: {action!r}"}, 400)

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

def _route_dvswitch_list(h: Handler) -> None:
    qs          = parse_qs(urlparse(h.path).query)
    include_all = qs.get("all", [""])[0] == "1"
    hidden_set  = _get_hidden_files()

    best: "dict[str, Path]" = {}
    for p in _DVSWITCH_FILES:
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
        dvs_parser = _DVS_FILE_PARSERS.get(label)
        files.append({
            "label":      label,
            "path":       str(p),
            "exists":     file_exists,
            "writable":   os.geteuid() == 0,
            "hidden":     is_hidden,
            "checks":     dvs_parser(content) if (dvs_parser and file_exists) else [],
            "port_lines": extract_port_lines(content),
        })

    h.send_json({"ok": True, "files": files})

def _route_dvswitch_get(h: Handler) -> None:
    qs    = parse_qs(urlparse(h.path).query)
    label = qs.get("label", [""])[0].strip()

    p = _dvs_file_by_label(label)
    if p is None:
        h.send_json({"ok": False, "message": f"Unknown file: {label!r}"}, 400)
        return

    content, err = read_path_file(p)
    if err and not p.is_file():

        h.send_json({
            "ok":       True,
            "label":    label,
            "path":     str(p),
            "content":  "",
            "exists":   False,
            "writable": os.geteuid() == 0,
        })
        return
    if err:
        h.send_json({"ok": False, "message": err}, 500)
        return

    h.send_json({
        "ok":       True,
        "label":    label,
        "path":     str(p),
        "content":  content,
        "exists":   True,
        "writable": os.geteuid() == 0,
    })

def _route_dvswitch_post(h: Handler, data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "root required"}); return

    label   = str(data.get("label",   "")).strip()
    content = str(data.get("content", ""))

    p = _dvs_file_by_label(label)
    if p is None:
        h.send_json({"ok": False, "message": f"Unknown file: {label!r}"}, 400)
        return

    ok, msg = write_path_file(p, content)
    _log(msg, stderr=not ok)
    h.send_json({"ok": ok, "message": msg, "path": str(p)},
                200 if ok else 500)

def _route_usbradio_get(h: Handler) -> None:
    settings = parse_usbradio_settings()
    
    h.send_json({
        "ok":        settings.get("exists", False),
        "settings": {
            "devstr":       settings.get("devstr"),
            "rxmixerset":   settings.get("rxmixerset"),
            "txmixaset":    settings.get("txmixaset"),
            "txmixbset":    settings.get("txmixbset"),
            "rxvoiceadj":   settings.get("rxvoiceadj"),
            "rxctcssadj":   settings.get("rxctcssadj"),
            "txctcssadj":   settings.get("txctcssadj"),
            "rxsquelchadj": settings.get("rxsquelchadj"),
            "fever":        settings.get("fever"),
            "txslimsp":     settings.get("txslimsp"),
        },
        "path":      settings.get("path"),
        "exists":    settings.get("exists"),
        "module":    module_state("chan_usbradio.so"),
    })

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
            normalized = str(val).strip().lower()
            if normalized not in ("yes", "no"):
                h.send_json({
                    "ok": False,
                    "message": f"{key} must be 'yes' or 'no' (got {repr(val)})"
                }, 400)
                return
            updates[key] = normalized

    if not updates:
        h.send_json({
            "ok": False,
            "message": f"no settings to update — provide one of {', '.join(_SIMPLEUSB_FIELD_SPECS)}"
        }, 400)
        return

    ok, msg = save_simpleusb_tune_settings(updates)
    if not ok:
        h.send_json({
            "ok": False,
            "message": msg
        }, 500)
        return

    if not _set_radio_tune("simpleusb", updates):
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
    ur = module_state("chan_usbradio.so")
    su_on = su in ("load", "require")
    ur_on = ur in ("load", "require")

    if ur_on:
        active = "usbradio"
    elif su_on:
        active = "simpleusb"
    else:
        active = None

    h.send_json({
        "ok":        True,
        "simpleusb": su,
        "usbradio":  ur,
        "active":    active,
        "both":      su_on and ur_on,
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

def _route_usbradio_post(h: Handler, data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({
            "ok": False,
            "message": "Root required for save"
        }, 403)
        return
    
    allowed_fields = {
        "rxmixerset", "txmixaset", "txmixbset", "rxvoiceadj", "rxctcssadj",
        "txctcssadj", "rxsquelchadj", "fever", "txslimsp"
    }
    updates = {k: v for k, v in data.items() if k in allowed_fields}
    
    if not updates:
        h.send_json({
            "ok": False,
            "message": "No valid tune fields provided"
        }, 400)
        return
    
    ok, msg = save_usbradio_settings(updates)
    if not ok:
        h.send_json({
            "ok": False,
            "message": msg
        }, 400)
        return

    mirror_updates = {k: v for k, v in updates.items() if k != "fever"}
    if mirror_updates and not _set_radio_tune("usbradio", mirror_updates):
        _log("WARN — usbradio save: radio_tune mirror update failed")

    slot_raw = data.get("slot")
    if slot_raw is not None:
        try:
            slot = int(slot_raw)
        except (TypeError, ValueError):
            slot = -1
        if 1 <= slot <= 5:
            if not _set_active_radio_slot(slot, "usbradio"):
                _log(f"WARN — usbradio save: active_slot={slot} persist failed")
        else:
            _log(f"WARN — usbradio save: ignoring bad slot {slot_raw!r}")

    reload_requested = bool(data.get("reload", False))
    restart_state = None
    restart_msg = ""
    if reload_requested:
        started, restart_msg = start_radio_stack_restart("usbradio")
        if not started and "in progress" in restart_msg:
            h.send_json({
                "ok": False,
                "message": f"Saved, but restart not started: {restart_msg}",
                "restart": "busy",
            }, 409)
            return
        restart_state = "started" if started else "failed"

    h.send_json({
        "ok": True,
        "message": msg,
        "updated_fields": list(updates.keys()),
        "restart": restart_state,
        "restart_msg": restart_msg or None,

        "reload_ok": None,
        "reload_msg": None,
    })

_RADIO_TUNE_DRIVER_FIELDS = {

    "simpleusb": tuple(_SIMPLEUSB_FIELD_SPECS.keys()),
    "usbradio":  ("rxmixerset", "txmixaset", "txmixbset", "rxvoiceadj", "rxctcssadj",
                  "txctcssadj", "rxsquelchadj", "fever", "txslimsp"),
}
_RADIO_TUNE_SAVE_FN = {
    "simpleusb": save_simpleusb_tune_settings,
    "usbradio":  save_usbradio_settings,
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
            "message": f"unknown driver {driver!r} — must be 'simpleusb' or 'usbradio'"
        }, 400)
        return

    allowed_fields = _RADIO_TUNE_DRIVER_FIELDS[driver]
    updates = {k: data[k] for k in allowed_fields if k in data and data[k] is not None}

    if not updates:
        h.send_json({
            "ok": False,
            "message": f"no settings to update — provide one of {', '.join(allowed_fields)}"
        }, 400)
        return

    ok, msg = _RADIO_TUNE_SAVE_FN[driver](updates)
    if not ok:
        h.send_json({"ok": False, "message": msg}, 400)
        return

    mirror_updates = {k: v for k, v in updates.items() if k != "fever"}
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

def _route_allmon3_list(h: Handler) -> None:
    qs          = parse_qs(urlparse(h.path).query)
    include_all = qs.get("all", [""])[0] == "1"
    hidden_set  = _get_hidden_files()

    files = []
    for p in _ALLMON3_FILES:
        label       = p.name
        is_hidden   = label in hidden_set
        is_readonly = label in _ALLMON3_READONLY
        file_exists = p.is_file()

        if not include_all and is_hidden:
            continue

        content, _ = read_path_file(p) if file_exists else ("", None)
        parser     = _ALLMON3_FILE_PARSERS.get(label)
        files.append({
            "label":      label,
            "path":       str(p),
            "exists":     file_exists,
            "writable":   os.geteuid() == 0,
            "hidden":     is_hidden,
            "readonly":   is_readonly,
            "checks":     parser(content) if (parser and file_exists) else [],
            "port_lines": extract_port_lines(content),
        })

    h.send_json({"ok": True, "files": files})

def _route_allmon3_get(h: Handler) -> None:
    qs    = parse_qs(urlparse(h.path).query)
    label = qs.get("label", [""])[0].strip()

    p = _allmon3_file_by_label(label)
    if p is None:
        h.send_json({"ok": False, "message": f"Unknown file: {label!r}"}, 400)
        return

    is_readonly = label in _ALLMON3_READONLY
    content, err = read_path_file(p)
    if err and not p.is_file():
        h.send_json({
            "ok":       True,
            "label":    label,
            "path":     str(p),
            "content":  "",
            "exists":   False,
            "writable": os.geteuid() == 0,
            "readonly": is_readonly,
        })
        return
    if err:
        h.send_json({"ok": False, "message": err}, 500)
        return

    h.send_json({
        "ok":       True,
        "label":    label,
        "path":     str(p),
        "content":  content,
        "exists":   True,
        "writable": os.geteuid() == 0,
        "readonly": is_readonly,
    })

def _route_allmon3_post(h: Handler, data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "root required"}); return

    label   = str(data.get("label",   "")).strip()
    content = str(data.get("content", ""))

    if label in _ALLMON3_READONLY:
        h.send_json({
            "ok":      False,
            "message": f"{label!r} is read-only — use allmon3-passwd to manage users",
        }, 403)
        return

    p = _allmon3_file_by_label(label)
    if p is None:
        h.send_json({"ok": False, "message": f"Unknown file: {label!r}"}, 400)
        return

    ok, msg = write_path_file(p, content)
    _log(msg, stderr=not ok)
    h.send_json({"ok": ok, "message": msg, "path": str(p)},
                200 if ok else 500)

def _route_appconf_list(h: Handler) -> None:
    _APPCONF_DESCS = {
        "asl_dvs.conf": "ASL-DVS Dashboard",
        "sysmon.conf":  "SysMon",
    }
    files = []
    for p in _APPCONF_FILES:
        files.append({
            "label":    p.name,
            "path":     str(p),
            "exists":   p.is_file(),
            "writable": os.geteuid() == 0,
            "desc":     _APPCONF_DESCS.get(p.name, p.name),
        })
    h.send_json({"ok": True, "files": files})

def _route_appconf_get(h: Handler) -> None:
    qs    = parse_qs(urlparse(h.path).query)
    label = qs.get("label", [""])[0].strip()

    p = _appconf_file_by_label(label)
    if p is None:
        h.send_json({"ok": False, "message": f"Unknown file: {label!r}"}, 400)
        return

    content, err = read_path_file(p)
    if err and not p.is_file():
        h.send_json({
            "ok":       True,
            "label":    label,
            "path":     str(p),
            "content":  "",
            "exists":   False,
            "writable": os.geteuid() == 0,
        })
        return
    if err:
        h.send_json({"ok": False, "message": err}, 500)
        return

    h.send_json({
        "ok":       True,
        "label":    label,
        "path":     str(p),
        "content":  content,
        "exists":   True,
        "writable": os.geteuid() == 0,
    })

def _route_appconf_post(h: Handler, data: dict) -> None:
    if os.geteuid() != 0:
        h.send_json({"ok": False, "message": "root required"}); return

    label   = str(data.get("label",   "")).strip()
    content = str(data.get("content", ""))

    p = _appconf_file_by_label(label)
    if p is None:
        h.send_json({"ok": False, "message": f"Unknown file: {label!r}"}, 400)
        return

    ok, msg = write_path_file(p, content)
    _log(msg, stderr=not ok)
    h.send_json({"ok": ok, "message": msg, "path": str(p)},
                200 if ok else 500)

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

def _route_reg_get(h: Handler) -> None:
    h.send_json(get_reg_status())

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

def _route_dvsm(h: Handler) -> None:
    payload = _build_dvsm_payload()
    payload["ok"] = True
    h.send_json(payload)

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

    h.send_json({"ok": False, "message": f"unknown action '{action}'"}, 400)

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

_ZELLO_SECRET_KEYS = ("ZELLO_PASSWORD",)

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

_GET_ROUTES = {
    "/":                       _route_html,
    "/api/ping":               lambda h: h.send_ping(),
    "/api/dashboard-status":   lambda h: h.send_json(action_dashboard_status()),
    "/api/status":             _route_status,
    "/api/config":             _route_config_get,
    "/api/log":                _route_log,
    "/api/overview":           _route_overview,
    "/api/services":           _route_services,
    "/api/services/detail":    _route_service_detail,
    "/api/ports":              _route_ports,
    "/api/ports/probe":        _route_ports_probe,
    "/api/firewall":           _route_firewall_get,
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
    "/api/radio/presets":      _route_radio_presets_get,
    "/api/radio/driver":       _route_radio_driver_get,
    "/api/radio/stack_status": _route_radio_stack_status,
    "/api/usbradio/read":      _route_usbradio_get,
    "/api/appconf/files":      _route_appconf_list,
    "/api/appconf/file":       _route_appconf_get,
    "/api/pinned":             _route_pinned_get,
    "/api/abinfo":             _route_abinfo,
    "/api/hardware":           _route_hardware_get,
    "/api/hardware/diag":      _route_hardware_diag,
    "/api/reg":                _route_reg_get,
    "/api/dvsm":               _route_dvsm,
    "/api/stfu":               _route_stfu_get,
    "/api/m17":                _route_m17_get,
    "/api/zello":              _route_zello_get,
    "/api/sdcard":             _route_sdcard_get,
    "/api/sdcard/test":        _route_sdcard_test_get,
}

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

_POST_ROUTES = {
    "/api/svc":             _route_svc,
    "/api/reboot":          _route_reboot,
    "/api/shutdown":        _route_shutdown,
    "/api/config":          _route_config_post,
    "/api/firewall":        _route_firewall_post,
    "/api/unit_file":       _route_unit_file_post,
    "/api/asterisk/file":   _route_asterisk_post,
    "/api/allmon3/file":    _route_allmon3_post,
    "/api/dvswitch/file":   _route_dvswitch_post,
    "/api/simpleusb/tune":  _route_simpleusb_tune_post,
    "/api/radio/presets":   _route_radio_presets_post,
    "/api/usbradio/save":   _route_usbradio_post,
    "/api/radio/tune/save": _route_radio_tune_save_post,
    "/api/appconf/file":    _route_appconf_post,
    "/api/pinned":          _route_pinned_post,
    "/api/hardware":        _route_hardware_post,
    "/api/stfu":            _route_stfu_post,
    "/api/m17":             _route_m17_post,
    "/api/zello":           _route_zello_post,
    "/api/sdcard/test":     _route_sdcard_test_post,
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

def main() -> None:
    parser = argparse.ArgumentParser(description="ASL-DVS SYSMON")
    parser.add_argument("--install", action="store_true", help="Install sysmon as a systemd service")
    parser.add_argument("--uninstall", action="store_true", help="Remove sysmon systemd service")
    args = parser.parse_args()

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

    Handler.allow_reuse_address = True
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
