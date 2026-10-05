# ASL-DVS

Web tools for running an AllStarLink (ASL) node with DVSwitch digital voice
on a Raspberry Pi. Each tool is a single Python or shell file. Each tool runs
as its own systemd service and serves its own page in the browser.

By KD8PGK, written with Claude (Anthropic).

## The tools

| Tool | File | Port | What it does |
|---|---|---|---|
| Dashboard | `asl_dvs_dashboard_v*.py` | 8989 | Node control. Connect ASL and EchoLink nodes, tune DMR, YSF, P25, NXDN, D-STAR, XLX and M17, manage favorites, Phone. |
| SysMon | `sysmon_v*.py` | 9999 | System monitor and health checks for the node, DVSwitch and its config files. |
| instmon | `instmon_v*.py` | 8990 | Installer and manager. Install, update, start and stop the other tools, update from GitHub, Quiet System, disk images. |
| wifimon | `wifimon_v*.py` | 8991 | WiFi and supply-voltage watchdog. Shuts the Pi down cleanly on sustained low voltage or lost network. |
| 44helper | `asl_dvs_m17_44helper_v*.py` | 9997 | 44Net Connect, firewall, router and SvxLink helper. |
| Watchdog | `asl_dvs_watchdog_v*.sh` | none | Restarts the Dashboard if it stops answering. See the note under [Installing](#installing). |

Scripts:

- `install_asl_dvs_v*.sh`: installs or updates the Dashboard, SysMon, wifimon and 44helper.
- `uninstall_asl_dvs_all_v*.sh`: removes every tool except instmon, and leaves configs in place.
- `wifi_menu.sh`: a text menu for WiFi status and switching networks (uses `nmcli`).

Pages that ask for a login use the Pi's root password.

## Two builds: full and Pi Zero 2 W

SysMon and the Dashboard come in two builds:

- **Full build:** for a Pi 3, 4 or 5.
- **Pi Zero 2 W fork:** a lighter build for the 512 MB Pi Zero 2 W.
  - **SysMon:** drops the Console, Net, Reg, Firewall and Zello tabs.
  - **Dashboard:** keeps every tab, including Phone and all digital modes. It searches the AllStar and EchoLink lists from disk instead of memory, and polls less often.

All the other tools are **common**, with one build for every node.

### How files are named and marked

| | Full build | Pi Zero 2 W fork | Common tool |
|---|---|---|---|
| File name | `sysmon_v6_13_67_20261005.py` | `sysmon_pi02w_v6_13_67_2_20261005.py` | `instmon_v2_38_1_20261005.py` |
| `VERSION` | `6.13.67` | `6.13.67.2-pi02w` | `2.38.1` |
| Header | | `Build: Pi Zero 2 W fork of v6.13.67` | `Build: common (all nodes, including Pi Zero 2 W)` |

File names follow `<tool>_vX_Y_Z_YYYYMMDD.py`. A version number is never
reused: every change gets a new version.

### Which build a node gets

- **The installer** keeps the build that is already installed. On a fresh install it checks the Pi's model: a Pi Zero 2 W gets the fork, and every other Pi gets the full build. To force a build, set `SYSMON_VARIANT` or `DASH_VARIANT` to `pi02w` or `full`.
- **instmon** (v2.38.0 and later) shows a **Pi Zero 2 W build** choice on the GitHub Updates card when it runs on a Pi Zero 2 W:
  - **Pi02w fork (default)**
  - **Full build (override)**

  Full Update installs the chosen build. If the other build is installed, Full Update switches it and lists it as **SWITCH**. On other Pis the choice is hidden and each tool keeps the build it has.

## Installing

1. Copy the files you want onto the Pi, all in one folder.
2. Install instmon first:
   ```
   sudo python3 instmon_v2_38_1_20261005.py --install
   ```
   Then open `http://<pi-address>:8990`.
3. Install the rest with the installer:
   ```
   sudo bash install_asl_dvs_v6_5_20261005.sh
   ```
   - On first install it asks for your callsign, node number and a label.
   - Run it with `--non-interactive` (or `-y`) to skip the questions. In that case, set `AUTO_CALLSIGN`, `AUTO_NODE` and `AUTO_LABEL` first.
   - Any subset of the tools can be installed.

   You can also stage the files in instmon's library and press Install there.

Each Python tool also installs and removes itself:

```
sudo python3 <file>.py --install
sudo python3 <file>.py --uninstall
```

**Watchdog note:** the installer (v6.4 and later) no longer installs the
Watchdog, and it removes an installed copy. The Dashboard's own service
already restarts it with `Restart=always` and `WatchdogSec=30`. The Watchdog
script stays in the repo, and instmon can still install it.

## Updating from GitHub (instmon)

The **GitHub Updates** card in instmon reads this repo's file list directly.

- **Check GitHub:** shows the newest GitHub copy of each tool and whether it is newer than what is installed.
  - The full and Pi Zero 2 W builds get separate rows.
  - Rows for the build this Pi Zero 2 W isn't using are tagged "other build".
- **Update:** downloads one file into instmon's library. Every download is checked before it is saved: same file as GitHub's list, a version line, the right first line, a syntax check, and `--install` support. Nothing installs until you press Install.
- **Full Update:** updates every installed tool:
  1. Downloads and checks every new file before anything changes.
  2. Pauses the web tools.
  3. Goes one tool at a time: saves a copy of the installed file in the library, uninstalls it, then installs the new one. If the new one fails, it puts the old one back and moves on.
  4. Updates instmon last. A timer reinstalls the old instmon if the new one isn't answering after 90 seconds.
  5. Ends with a summary.

  New install scripts only go to the Scripts library. Full Update never runs them.
- **Quiet System / Restore:** pauses SysMon, the Dashboard, 44helper and the Watchdog timer before a big upload or install on a small Pi.
  - Asterisk, the bridges, Allmon3, SSH and wifimon keep running.
  - Everything comes back automatically after 30 minutes.

To start using this on a node that has an older instmon, install the current
instmon once by hand. From then on, instmon updates itself.

## The launcher

The Pi Zero 2 W builds and the common tools start through a small file,
`/usr/local/bin/asl_dvs_launch.py`:

```
ExecStart=/usr/bin/python3 /usr/local/bin/asl_dvs_launch.py /usr/local/bin/instmon.py
```

The launcher loads the tool as a module instead of running the file directly.
That way Python keeps the compiled copy in `__pycache__` and reuses it on each
start. Python recompiles by itself after an update.

The result is about half the memory and a faster start:

| Tool | Started directly | Through the launcher |
|---|---|---|
| SysMon (Pi Zero 2 W fork) | 54 MB | 26 MB |
| Dashboard (Pi Zero 2 W fork) | 45 MB | 25 MB |
| instmon | 34 MB | 21 MB |
| wifimon | 36 MB | 22 MB |
| 44helper | 48 MB | 26 MB |

Each tool writes the launcher when it installs. It removes the launcher on
uninstall once no service uses it any more.

## Removing everything

```
sudo bash uninstall_asl_dvs_all_v1_1.sh
```

This removes every tool except instmon. It leaves `/etc/asl_dvs/`,
instmon's library and `/etc/wifimon/wifimon.conf` in place. To remove instmon
afterwards, run its own `--uninstall`.

## Files

| File | Build |
|---|---|
| `asl_dvs_dashboard_v9_3_71_20261004.py` | Dashboard, full (current) |
| `asl_dvs_dashboard_pi02w_v9_3_71_1_20261005.py` | Dashboard, Pi Zero 2 W (current) |
| `asl_dvs_dashboard_v8_0_3_20260822.py` | Dashboard, full (older) |
| `sysmon_v6_13_67_20261005.py` | SysMon, full (current) |
| `sysmon_pi02w_v6_13_67_2_20261005.py` | SysMon, Pi Zero 2 W (current) |
| `sysmon_v6_5_18_20260823.py` | SysMon, full (older) |
| `instmon_v2_38_1_20261005.py` | common |
| `wifimon_v5_23_20261005.py` | common |
| `asl_dvs_m17_44helper_v0_0_158_20261005.py` | common |
| `asl_dvs_watchdog_v2_3_20261005.sh` | common |
| `install_asl_dvs_v6_5_20261005.sh` | common |
| `uninstall_asl_dvs_all_v1_1.sh` | common |
| `wifi_menu.sh` | common |

When there is more than one version of a tool, instmon and the installer
always pick the newest.

## License

Licensed under [Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)](https://creativecommons.org/licenses/by-nc/4.0/). See [LICENSE](LICENSE).

You may share and adapt these files if you credit KD8PGK and don't use them for commercial purposes.
