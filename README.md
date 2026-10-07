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
| 44helper | `asl_dvs_m17_44helper_v*.py` | 9997 | 44Net Connect, firewall, router and SvxLink helper; config restore points and presets (Config tab). |
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
| File name | `sysmon_v6_13_72_20261007.py` | `sysmon_pi02w_v6_13_67_7_20261007.py` | `instmon_v2_38_2_20261006.py` |
| `VERSION` | `6.13.70` | `6.13.67.5-pi02w` | `2.38.2` |

The `-pi02w` suffix on `VERSION` marks the fork; the installer and instmon
read it from there. File names follow `<tool>_vX_Y_Z_YYYYMMDD.py`. A version
number is never reused: every change gets a new version.

### Which build a node gets

- **The installer** keeps the build that is already installed. On a fresh install it checks the Pi's model: a Pi Zero 2 W gets the fork, and every other Pi gets the full build. To force a build, set `SYSMON_VARIANT` or `DASH_VARIANT` to `pi02w` or `full`.
- **instmon** (v2.38.0 and later) shows a **Pi Zero 2 W build** choice on the GitHub Updates card when it runs on a Pi Zero 2 W:
  - **Pi02w fork (default)**
  - **Full build (override)**

  Full Update installs the chosen build. If the other build is installed, Full Update switches it and lists it as **SWITCH**. On other Pis the choice is hidden and each tool keeps the build it has.

## Installing

Step-by-step manuals (PDF):

- Pi Zero 2 W build: [`docs/ASL-DVS_Pi02w_Install_Manual.pdf`](docs/ASL-DVS_Pi02w_Install_Manual.pdf)
- Full build (Pi 3, 4 or 5): [`docs/ASL-DVS_Full_Build_Install_Manual.pdf`](docs/ASL-DVS_Full_Build_Install_Manual.pdf)

Phone dialplan guide (PDF, 24 pages): dialplan nuts and bolts, stock ASL3 next to the Phone tab's dialplan (Pi02w 9.3.71.10 and full 9.3.73 on):
[`docs/ASL-DVS_Pi02w_Phone_Dialplan_Guide.pdf`](docs/ASL-DVS_Pi02w_Phone_Dialplan_Guide.pdf)

Idealized node configuration (PDF, 14 pages): the target ASL3 + DVSwitch + USRP2M17 bridge-node files, port map, services and firewall for a clean build, with no identity data (placeholders only):
[`docs/ASL-DVS_Idealized_Node_Configuration.pdf`](docs/ASL-DVS_Idealized_Node_Configuration.pdf)

1. Copy the files you want onto the Pi, all in one folder.
2. Install instmon first:
   ```
   sudo python3 instmon_v2_38_2_20261006.py --install
   ```
   Then open `http://<pi-address>:8990`.
3. Install the rest with the installer:
   ```
   sudo bash install_asl_dvs_v6_6_20261006.sh
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

### Memory savers

Launcher version 2 (written by SysMon Pi02w 6.13.67.3, Dashboard Pi02w
9.3.71.2, instmon 2.38.2, wifimon 5.24, 44helper 0.0.159 and installer v6.6)
adds three more savers. The service files do not change: the launcher starts
Python once more with the first two, in the same process.

| Saver | What it does | Off switch |
|---|---|---|
| `python3 -OO` | Drops the built-in help text (docstrings) from the loaded code. | `/etc/asl_dvs/launch_no_optimize` |
| `MALLOC_ARENA_MAX=2` | At most 2 memory pools instead of up to 8 per CPU core. Each pool keeps the memory its threads freed. | `/etc/asl_dvs/launch_no_arena_cap` |
| `malloc_trim` | 1 minute after start, then every 5 minutes, hands freed memory back to Linux. | `/etc/asl_dvs/launch_no_trim` |

To turn a saver off for every tool, create its file and restart the services:

```
sudo touch /etc/asl_dvs/launch_no_arena_cap
sudo systemctl restart sysmon asl_dvs_dashboard instmon wifimon 44helper
```

Delete the file and restart to turn it back on. With `-OO`, the first start
after an update compiles the tool (and the parts of Python it uses) once more;
memory settles from the next restart on.

## Removing everything

```
sudo bash uninstall_asl_dvs_all_v1_3.sh
```

This removes every tool except instmon. It leaves `/etc/asl_dvs/`,
instmon's library and `/etc/wifimon/wifimon.conf` in place. To remove instmon
afterwards, run its own `--uninstall`. If the SysMon Hardware tab (either build) turned off
the video driver or lowered GPU memory, it puts `/boot/firmware/config.txt` back
(reboot to apply).

## Files

| File | Build |
|---|---|
| `asl_dvs_dashboard_v9_3_73_20261006.py` | Dashboard, full (current) |
| `asl_dvs_dashboard_pi02w_v9_3_71_11_20261007.py` | Dashboard, Pi Zero 2 W (current) |
| `asl_dvs_dashboard_v8_0_3_20260822.py` | Dashboard, full (older) |
| `sysmon_v6_13_72_20261007.py` | SysMon, full (current) |
| `sysmon_pi02w_v6_13_67_7_20261007.py` | SysMon, Pi Zero 2 W (current) |
| `sysmon_v6_5_18_20260823.py` | SysMon, full (older) |
| `instmon_v2_38_2_20261006.py` | common |
| `wifimon_v5_26_20261006.py` | common |
| `asl_dvs_m17_44helper_v0_0_167_20261007.py` | common |
| `asl_dvs_watchdog_v2_4_20261006.sh` | common |
| `install_asl_dvs_v6_6_20261006.sh` | common |
| `uninstall_asl_dvs_all_v1_3.sh` | common |
| `wifi_menu.sh` | common |

When there is more than one version of a tool, instmon and the installer
always pick the newest.

## Comment-stripped copies and changelogs

The scripts in this repo are comment-stripped copies: comments and docstrings
are removed, and the code is otherwise unchanged. A few comment lines stay
because something reads them:

- the first line (`#!...`) and a Python `coding` line;
- the title line of each `.sh` script (for example
  `# install_asl_dvs_dashboard.sh  v6.6  (2026-10-06)`): instmon reads a
  shell script's version from it.

Text inside strings is left alone, including files the tools write onto the
Pi, like service units and the launcher.

The change history of each script is in [`changelogs/`](changelogs), one file
per tool and build:

| Changelog | Scripts |
|---|---|
| [`sysmon.md`](changelogs/sysmon.md) | `sysmon_v*.py` (full) |
| [`sysmon_pi02w.md`](changelogs/sysmon_pi02w.md) | `sysmon_pi02w_v*.py` |
| [`asl_dvs_dashboard.md`](changelogs/asl_dvs_dashboard.md) | `asl_dvs_dashboard_v*.py` (full) |
| [`asl_dvs_dashboard_pi02w.md`](changelogs/asl_dvs_dashboard_pi02w.md) | `asl_dvs_dashboard_pi02w_v*.py` |
| [`instmon.md`](changelogs/instmon.md) | `instmon_v*.py` |
| [`wifimon.md`](changelogs/wifimon.md) | `wifimon_v*.py` |
| [`asl_dvs_m17_44helper.md`](changelogs/asl_dvs_m17_44helper.md) | `asl_dvs_m17_44helper_v*.py` |
| [`asl_dvs_watchdog.md`](changelogs/asl_dvs_watchdog.md) | `asl_dvs_watchdog_v*.sh` |
| [`install_asl_dvs.md`](changelogs/install_asl_dvs.md) | `install_asl_dvs_v*.sh` |
| [`uninstall_asl_dvs_all.md`](changelogs/uninstall_asl_dvs_all.md) | `uninstall_asl_dvs_all_v*.sh` |
| [`wifi_menu.md`](changelogs/wifi_menu.md) | `wifi_menu.sh` |

Every new version adds an entry at the top of its changelog.

## License

Licensed under [Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)](https://creativecommons.org/licenses/by-nc/4.0/). See [LICENSE](LICENSE).

You may share and adapt these files if you credit KD8PGK and don't use them for commercial purposes.
