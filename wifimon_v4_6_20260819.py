#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#"""
#wifimon.py — WiFi & Voltage Watchdog for Raspberry Pi Zero 2W
#Version: 4.6 (Self-Installing, Aggressive Reconnect, Interactive WiFi Setup)

#Monitors wifi connectivity and supply voltage.
#Triggers a clean system shutdown on:
#  1. Sustained low voltage (undervoltage protection).
#  2. Sustained network connection loss.
#
#v4.6 — Fixed the shebang: it was `# -*- coding: utf-8 -*-` on line 1
#  and `#!/usr/bin/env python3` commented out on line 2, so running the
#  file directly (./wifimon.py) couldn't find an interpreter — it only
#  ever worked when invoked as `python3 wifimon.py`. The shebang is now
#  the literal, uncommented first line; the coding declaration moved to
#  line 2, which PEP 263 also allows. No other change.
#
#v4.5 — Line-ending normalization only. No behavior change. Lines 252-412
#  (the WiFi-setup-wizard block: _prompt_manual_networks through
#  run_wifi_setup) had plain LF endings while the rest of the file used
#  CRLF — evidently pasted in from a different editor/source at some
#  point without normalizing. Whole file is now LF throughout, matching
#  the rest of the ASL-DVS-M17 suite (asl_dvs_m17_44helper, instmon).
#  Verified: every line's content is byte-identical to v4.4 once both
#  are normalized for comparison — only line-ending bytes changed.
#
#v4.3 — Added /etc/wifimon/wifimon.conf with a [network_N] section per
#  known WiFi network (ssid/psk/priority). While the connection is down,
#  wifimon now aggressively retries connecting — the network that was
#  just lost first, then the configured networks in priority order —
#  using nmcli if present, falling back to wpa_cli. This runs alongside
#  the existing shutdown countdown, not instead of it: NO_CONN_SHUTDOWN_SECS
#  still fires on schedule no matter how many reconnect attempts happened.
#  If wifimon.conf has no networks configured, this is a no-op and
#  behavior is unchanged from v4.2.
#
#v4.4 — --install now prompts for WiFi setup on an interactive terminal
#  if no networks are configured yet: enter one manually, or import
#  networks already saved on the system (nmcli connection profiles or
#  wpa_supplicant.conf). Skipped automatically for non-interactive
#  installs, and never re-prompts if wifimon.conf already has networks
#  in it. The same menu is also available standalone via --setup-wifi.
#
#Usage:
#  sudo python3 wifimon.py --install      Install as systemd service & start
#  sudo python3 wifimon.py --uninstall    Stop & remove systemd service
#  sudo python3 wifimon.py --setup-wifi   Add/import WiFi networks
#  python3 wifimon.py                     Run watchdog in foreground
#"""

import argparse
import configparser
import getpass
import logging
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from typing import Dict, List, Optional

INTERFACE                 = "wlan0"
PING_TARGET               = "8.8.8.8"
CHECK_INTERVAL            = 5
PING_TIMEOUT              = 2
NO_CONN_SHUTDOWN_SECS     = 180
LOW_VOLTAGE_THRESHOLD     = 0.90
LOW_VOLTAGE_SHUTDOWN_SECS = 30
RECONNECT_INTERVAL_SECS   = 15

CONFIG_DIR  = "/etc/wifimon"
CONFIG_FILE = os.path.join(CONFIG_DIR, "wifimon.conf")

_DEFAULT_CONFIG = {
    "network_1": {
        "ssid": "",
        "psk": "",
        "priority": "1",
    },
}


def _ensure_config() -> None:
    if os.path.exists(CONFIG_FILE):
        return
    os.makedirs(CONFIG_DIR, exist_ok=True)
    cfg = configparser.ConfigParser()
    for section, values in _DEFAULT_CONFIG.items():
        cfg[section] = values
    with open(CONFIG_FILE, "w") as f:
        cfg.write(f)
    os.chmod(CONFIG_FILE, 0o600)
    log.info("Created default config at %s", CONFIG_FILE)


def load_wifi_networks() -> List[Dict[str, object]]:
    _ensure_config()
    cfg = configparser.ConfigParser()
    try:
        cfg.read(CONFIG_FILE)
    except configparser.Error as e:
        log.error("Failed to parse %s: %s", CONFIG_FILE, e)
        return []

    networks = []
    for section in cfg.sections():
        if not section.startswith("network_"):
            continue
        ssid = cfg.get(section, "ssid", fallback="").strip()
        if not ssid:
            continue
        psk = cfg.get(section, "psk", fallback="")
        try:
            priority = int(cfg.get(section, "priority", fallback="99"))
        except ValueError:
            priority = 99
        networks.append({"ssid": ssid, "psk": psk, "priority": priority})

    networks.sort(key=lambda n: n["priority"])
    return networks


def save_wifi_networks(networks: List[Dict[str, object]]) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    cfg = configparser.ConfigParser()
    for i, n in enumerate(networks, start=1):
        cfg[f"network_{i}"] = {
            "ssid": n["ssid"],
            "psk": n.get("psk", ""),
            "priority": str(n.get("priority", i)),
        }
    with open(CONFIG_FILE, "w") as f:
        cfg.write(f)
    os.chmod(CONFIG_FILE, 0o600)
    print(f"  [+] Saved {len(networks)} network(s) to {CONFIG_FILE}")

INSTALL_BIN_PATH = "/usr/local/bin/wifimon.py"
SYSTEMD_SERVICE_PATH = "/etc/systemd/system/wifimon.service"

SYSTEMD_SERVICE_CONTENT = """[Unit]
Description=WiFi and Voltage Watchdog Daemon
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/bin/wifimon.py
Restart=always
RestartSec=3s
StandardOutput=journal
StandardError=journal

# Process Priorities
Nice=-5
OOMScoreAdjust=-500

[Install]
WantedBy=multi-user.target
"""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("wifimon")

_shutdown_event = threading.Event()

def _handle_sigterm(signum: int, frame: object) -> None:
    log.info("Signal %d received — exiting cleanly", signum)
    _shutdown_event.set()

signal.signal(signal.SIGTERM, _handle_sigterm)
signal.signal(signal.SIGINT,  _handle_sigterm)

def install_service() -> None:
    if os.geteuid() != 0:
        print("Error: Installation requires root privileges. Run with 'sudo'.")
        sys.exit(1)

    current_script = os.path.abspath(__file__)

    print("Installing wifimon...")
    
    if current_script != INSTALL_BIN_PATH:
        shutil.copy2(current_script, INSTALL_BIN_PATH)
        print(f"  [+] Copied script to {INSTALL_BIN_PATH}")
    os.chmod(INSTALL_BIN_PATH, 0o755)

    with open(SYSTEMD_SERVICE_PATH, "w") as f:
        f.write(SYSTEMD_SERVICE_CONTENT)
    print(f"  [+] Created service file at {SYSTEMD_SERVICE_PATH}")

    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "wifimon.service"], check=True)
    subprocess.run(["systemctl", "restart", "wifimon.service"], check=True)
    print("  [+] Enabled and restarted wifimon.service")

    if not load_wifi_networks():
        if sys.stdin.isatty():
            run_wifi_setup()
            if load_wifi_networks():
                subprocess.run(["systemctl", "restart", "wifimon.service"], check=False)
                print("  [+] Restarted wifimon.service to pick up the new network(s)")
        else:
            print(f"  [i] No WiFi networks configured. Run "
                  f"'sudo python3 {INSTALL_BIN_PATH} --setup-wifi' to add some,")
            print(f"      or edit {CONFIG_FILE} directly.")

    print("\nInstallation complete! View logs anytime using:")
    print("  journalctl -u wifimon -f")


def uninstall_service() -> None:
    if os.geteuid() != 0:
        print("Error: Uninstallation requires root privileges. Run with 'sudo'.")
        sys.exit(1)

    print("Uninstalling wifimon...")

    subprocess.run(["systemctl", "disable", "--now", "wifimon.service"], stderr=subprocess.DEVNULL)
    print("  [-] Stopped and disabled wifimon.service")

    if os.path.exists(SYSTEMD_SERVICE_PATH):
        os.remove(SYSTEMD_SERVICE_PATH)
        print(f"  [-] Removed {SYSTEMD_SERVICE_PATH}")

    subprocess.run(["systemctl", "daemon-reload"], stderr=subprocess.DEVNULL)

    if os.path.exists(INSTALL_BIN_PATH):
        os.remove(INSTALL_BIN_PATH)
        print(f"  [-] Removed {INSTALL_BIN_PATH}")

    print("\nUninstallation complete.")

def _prompt_manual_networks(start_priority: int = 1) -> List[Dict[str, object]]:
    networks: List[Dict[str, object]] = []
    priority = start_priority
    while True:
        ssid = input("  SSID: ").strip()
        if not ssid:
            print("  (blank SSID, skipping)")
        else:
            psk = getpass.getpass("  Password (blank for open network): ")
            networks.append({"ssid": ssid, "psk": psk, "priority": priority})
            priority += 1
        again = input("Add another network? [y/N]: ").strip().lower()
        if again != "y":
            break
    return networks


def _discover_nmcli_networks() -> List[Dict[str, object]]:
    found: List[Dict[str, object]] = []
    try:
        out = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return found

    seen_ssids = set()
    for line in out.stdout.splitlines():
        parts = line.split(":")
        if len(parts) < 2 or parts[1] != "802-11-wireless":
            continue
        name = parts[0]
        if name in seen_ssids:
            continue
        seen_ssids.add(name)
        psk = ""
        try:
            sec = subprocess.run(
                ["nmcli", "-s", "-g", "802-11-wireless-security.psk",
                 "connection", "show", name],
                capture_output=True, text=True, timeout=10,
            )
            psk = sec.stdout.strip()
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        found.append({"ssid": name, "psk": psk, "found_pw": bool(psk)})
    return found


def _discover_wpa_supplicant_networks() -> List[Dict[str, object]]:
    found: List[Dict[str, object]] = []
    path = "/etc/wpa_supplicant/wpa_supplicant.conf"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return found

    for block in content.split("network={")[1:]:
        block = block.split("}", 1)[0]
        ssid = None
        psk = ""
        hashed = False
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("ssid="):
                ssid = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("psk="):
                raw = line.split("=", 1)[1].strip().strip('"')
                psk = raw
                if '"' not in line.split("=", 1)[1] and len(raw) == 64:
                    hashed = True
        if ssid:
            found.append({"ssid": ssid, "psk": psk, "found_pw": bool(psk),
                           "hashed": hashed})
    return found


def _discover_system_networks() -> List[Dict[str, object]]:
    backend = _wifi_backend()
    if backend == "nmcli":
        return _discover_nmcli_networks()
    if backend == "wpa_cli":
        return _discover_wpa_supplicant_networks()
    return []


def _prompt_import_networks(start_priority: int = 1) -> List[Dict[str, object]]:
    discovered = _discover_system_networks()
    if not discovered:
        print("  No saved networks found on this system — switching to manual entry.")
        return _prompt_manual_networks(start_priority)

    print(f"  Found {len(discovered)} saved network(s):")
    for i, n in enumerate(discovered, start=1):
        pw_note = "password saved" if n.get("found_pw") else "no password found"
        if n.get("hashed"):
            pw_note += ", pre-hashed key (wpa_cli-only)"
        print(f"    {i}) {n['ssid']}  [{pw_note}]")

    choice = input("Import all? [Y/n], or enter numbers (e.g. 1,3): ").strip().lower()
    if choice in ("", "y", "yes"):
        selected = discovered
    elif choice in ("n", "no"):
        return []
    else:
        idxs = []
        for tok in choice.split(","):
            tok = tok.strip()
            if tok.isdigit() and 1 <= int(tok) <= len(discovered):
                idxs.append(int(tok) - 1)
        selected = [discovered[i] for i in idxs]

    networks = []
    for i, n in enumerate(selected, start=start_priority):
        if n.get("hashed"):
            log.info("Imported %s as a pre-hashed key (wpa_cli-only)", n["ssid"])
        networks.append({"ssid": n["ssid"], "psk": n.get("psk", ""), "priority": i})
    return networks


def run_wifi_setup() -> None:
    if os.geteuid() != 0:
        print("ERROR: WiFi setup requires root  →  sudo python3 wifimon.py --setup-wifi",
              file=sys.stderr)
        sys.exit(1)

    existing = load_wifi_networks()
    next_priority = (max((n["priority"] for n in existing), default=0) + 1)

    print("\nWiFi network setup for wifimon:")
    print("  1) Enter a network manually (SSID + password)")
    print("  2) Import known networks already saved on this system")
    print("  3) Skip for now — edit /etc/wifimon/wifimon.conf later")
    choice = input("Choice [1/2/3]: ").strip()

    if choice == "1":
        new_networks = _prompt_manual_networks(next_priority)
    elif choice == "2":
        new_networks = _prompt_import_networks(next_priority)
    else:
        print(f"  Skipped. Edit {CONFIG_FILE} manually, or re-run --setup-wifi later.")
        return

    if not new_networks:
        print("  No networks added.")
        return

    save_wifi_networks(existing + new_networks)

def _has_carrier() -> bool:
    try:
        with open(f"/sys/class/net/{INTERFACE}/carrier", "r") as f:
            return f.read().strip() == "1"
    except OSError:
        return False

def _get_gateway() -> Optional[str]:
    try:
        with open("/proc/net/route", "r") as f:
            for line in f:
                fields = line.strip().split()
                if len(fields) >= 3 and fields[0] == INTERFACE and fields[1] == "00000000":
                    gw_hex = fields[2]
                    if gw_hex != "00000000":
                        gw_ip = socket.inet_ntoa(struct.pack("<I", int(gw_hex, 16)))
                        if gw_ip != "0.0.0.0":
                            return gw_ip
    except (OSError, ValueError, struct.error):
        pass
    return None

def is_connected() -> bool:
    if not _has_carrier():
        return False

    try:
        res = subprocess.run(
            ["ping", "-c", "1", "-W", str(PING_TIMEOUT), "-I", INTERFACE, PING_TARGET],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=PING_TIMEOUT + 2
        )
        if res.returncode == 0:
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    gw = _get_gateway()
    if gw:
        try:
            res = subprocess.run(
                ["ping", "-c", "1", "-W", str(PING_TIMEOUT), "-I", INTERFACE, gw],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=PING_TIMEOUT + 2
            )
            return res.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return False

_reconnect_lock = threading.Lock()
_reconnecting = False


def _wifi_backend() -> Optional[str]:
    if shutil.which("nmcli"):
        return "nmcli"
    if shutil.which("wpa_cli"):
        return "wpa_cli"
    return None


def _connect_nmcli(ssid: str, psk: str) -> bool:
    try:
        if psk:
            cmd = ["nmcli", "device", "wifi", "connect", ssid,
                   "password", psk, "ifname", INTERFACE]
        else:
            cmd = ["nmcli", "device", "wifi", "connect", ssid, "ifname", INTERFACE]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              timeout=20, text=True)
        if res.returncode != 0:
            log.debug("nmcli connect to %s failed: %s", ssid, res.stderr.strip())
        return res.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log.debug("nmcli connect to %s error: %s", ssid, e)
        return False


def _connect_wpa_cli(ssid: str, psk: str) -> bool:
    try:
        out = subprocess.run(["wpa_cli", "-i", INTERFACE, "list_networks"],
                              capture_output=True, text=True, timeout=10)
        net_id = None
        for line in out.stdout.splitlines()[1:]:
            fields = line.split("\t")
            if len(fields) >= 2 and fields[1] == ssid:
                net_id = fields[0]
                break

        if net_id is None:
            add_out = subprocess.run(["wpa_cli", "-i", INTERFACE, "add_network"],
                                      capture_output=True, text=True, timeout=10)
            net_id = add_out.stdout.strip().splitlines()[-1]
            subprocess.run(["wpa_cli", "-i", INTERFACE, "set_network", net_id,
                             "ssid", f'"{ssid}"'], capture_output=True, timeout=10)
            if psk:
                subprocess.run(["wpa_cli", "-i", INTERFACE, "set_network", net_id,
                                 "psk", f'"{psk}"'], capture_output=True, timeout=10)
            else:
                subprocess.run(["wpa_cli", "-i", INTERFACE, "set_network", net_id,
                                 "key_mgmt", "NONE"], capture_output=True, timeout=10)

        subprocess.run(["wpa_cli", "-i", INTERFACE, "enable_network", net_id],
                        capture_output=True, timeout=10)
        subprocess.run(["wpa_cli", "-i", INTERFACE, "select_network", net_id],
                        capture_output=True, timeout=10)
        subprocess.run(["wpa_cli", "-i", INTERFACE, "save_config"],
                        capture_output=True, timeout=10)
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError, IndexError) as e:
        log.debug("wpa_cli reconnect to %s error: %s", ssid, e)
        return False


def _attempt_reconnect(networks: List[Dict[str, object]], last_ssid: Optional[str]) -> None:
    global _reconnecting
    backend = _wifi_backend()
    if backend is None:
        log.warning("Reconnect: neither nmcli nor wpa_cli found — cannot retry")
        _reconnecting = False
        return

    connect_fn = _connect_nmcli if backend == "nmcli" else _connect_wpa_cli

    ordered: List[Dict[str, object]] = []
    if last_ssid:
        for n in networks:
            if n["ssid"] == last_ssid:
                ordered.append(n)
                break
    ordered.extend(n for n in networks if n["ssid"] != last_ssid)

    for n in ordered:
        if _shutdown_event.is_set():
            break
        log.info("Reconnect: trying %s (%s)", n["ssid"], backend)
        if connect_fn(n["ssid"], n["psk"]):
            log.info("Reconnect: %s command succeeded, verifying...", n["ssid"])
            time.sleep(3)
            if is_connected():
                log.info("Reconnect: back online via %s", n["ssid"])
                _reconnecting = False
                return
        log.debug("Reconnect: %s did not come up", n["ssid"])

    _reconnecting = False


def maybe_reconnect(networks: List[Dict[str, object]], last_ssid: Optional[str]) -> None:
    global _reconnecting
    if not networks:
        return
    with _reconnect_lock:
        if _reconnecting:
            return
        _reconnecting = True
    threading.Thread(target=_attempt_reconnect, args=(networks, last_ssid),
                      daemon=True, name="wifi-reconnect").start()


def _current_ssid() -> Optional[str]:
    try:
        r = subprocess.run(["iwgetid", "-r", INTERFACE], capture_output=True,
                            text=True, timeout=5)
        ssid = r.stdout.strip()
        if ssid:
            return ssid
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    try:
        r = subprocess.run(["nmcli", "-t", "-f", "active,ssid", "device", "wifi"],
                            capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if line.startswith("yes:"):
                return line.split(":", 1)[1]
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    return None


def _check_voltage() -> Optional[float]:
    try:
        with open("/sys/class/hwmon/hwmon0/in0_lcrit_alarm", "r") as f:
            if f.read().strip() == "1":
                return 0.80
    except OSError:
        pass

    try:
        r = subprocess.run(["vcgencmd", "measure_volts", "core"], capture_output=True, text=True, timeout=5)
        _, _, val_part = r.stdout.strip().partition("=")
        if val_part:
            volts = float(val_part.rstrip("Vv"))
            if 0.50 <= volts < LOW_VOLTAGE_THRESHOLD:
                return volts
    except (subprocess.SubprocessError, ValueError):
        pass

    return None

def do_shutdown(reason: str) -> None:
    log.critical("Shutting down: %s", reason)
    try:
        subprocess.run(["sync"], timeout=5)
        subprocess.run(["systemctl", "poweroff"], timeout=10)
    except Exception:
        pass
    time.sleep(15)
    subprocess.run(["poweroff", "-f"])

def run() -> None:
    log.info("wifimon starting — watchdog active on %s", INTERFACE)

    wifi_networks = load_wifi_networks()
    if wifi_networks:
        log.info("Loaded %d known WiFi network(s) from %s for aggressive reconnect",
                  len(wifi_networks), CONFIG_FILE)
    else:
        log.info("No WiFi networks configured in %s — reconnect feature is idle", CONFIG_FILE)

    down_since: Optional[float] = None
    low_voltage_since: Optional[float] = None
    last_good_ssid: Optional[str] = None
    last_reconnect_attempt: Optional[float] = None

    while not _shutdown_event.is_set():
        loop_start = time.monotonic()

        low_v = _check_voltage()
        if low_v is not None:
            if low_voltage_since is None:
                low_voltage_since = loop_start
                log.warning("Low voltage: %.4fV — starting timer", low_v)
            elif (loop_start - low_voltage_since) >= LOW_VOLTAGE_SHUTDOWN_SECS:
                do_shutdown(f"Low voltage ({low_v:.4f}V) sustained for {LOW_VOLTAGE_SHUTDOWN_SECS}s")
                break
        else:
            if low_voltage_since is not None:
                log.info("Voltage restored to normal")
                low_voltage_since = None

        if is_connected():
            if down_since is not None:
                log.info("Network restored")
                down_since = None
                last_reconnect_attempt = None
            ssid_now = _current_ssid()
            if ssid_now:
                last_good_ssid = ssid_now
        else:
            if down_since is None:
                down_since = loop_start
                log.warning("Network lost — starting shutdown timer")
            elif (loop_start - down_since) >= NO_CONN_SHUTDOWN_SECS:
                do_shutdown(f"No network connection for {NO_CONN_SHUTDOWN_SECS}s")
                break

            if wifi_networks and (
                last_reconnect_attempt is None
                or (loop_start - last_reconnect_attempt) >= RECONNECT_INTERVAL_SECS
            ):
                last_reconnect_attempt = loop_start
                maybe_reconnect(wifi_networks, last_good_ssid)

        elapsed = time.monotonic() - loop_start
        if _shutdown_event.wait(timeout=max(0.1, CHECK_INTERVAL - elapsed)):
            break

    log.info("wifimon exiting")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WiFi and Voltage Watchdog for Raspberry Pi")
    parser.add_argument("--install", action="store_true", help="Install wifimon as a systemd service")
    parser.add_argument("--uninstall", action="store_true", help="Remove wifimon systemd service")
    parser.add_argument("--setup-wifi", action="store_true", help="Add/import WiFi networks")
    args = parser.parse_args()

    if args.install:
        install_service()
    elif args.uninstall:
        uninstall_service()
    elif args.setup_wifi:
        run_wifi_setup()
        result = subprocess.run(["systemctl", "is-active", "--quiet", "wifimon.service"])
        if result.returncode == 0:
            subprocess.run(["systemctl", "restart", "wifimon.service"], check=False)
            print("  [+] Restarted wifimon.service to pick up the new network(s)")
    else:
        run()