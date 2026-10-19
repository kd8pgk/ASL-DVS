# Node Controller

Web tools for running an AllStarLink (ASL) node with DVSwitch digital voice
on a Raspberry Pi. Each tool is a single Python or shell file. Each tool runs
as its own systemd service and serves its own page in the browser.

By KD8PGK, written with Claude (Anthropic).

## The tools

| Tool | File | Port | What it does |
|---|---|---|---|
| Dashboard | `nodecontrol_v*.py` | 8989 | Node control. Connect ASL and EchoLink nodes, tune DMR, YSF, P25, NXDN, D-STAR, XLX and M17, manage favorites, Phone. |
| SysMon | `sysmon_v*.py` | 9999 | System monitor and health checks for the node, DVSwitch and its config files. |
| instmon | `instmon_v*.py` | 8990 | Installer and manager. Install, update, start and stop the other tools, update from GitHub, Quiet System, disk images, and the manuals and any other PDF to upload, open or download. |
| wifimon | `wifimon_v*.py` | 8991 | WiFi and supply-voltage watchdog. Powers off on sustained low voltage; reboots (or powers off) on a lost network. Hardware watchdog, and alerts by ntfy or webhook. |
| 44helper | `44helper_v*.py` | 9997 | 44Net Connect, firewall, router and SvxLink helper; config restore points and presets (Config tab); boot timeline, logs and saved copies (Boot tab). |
| Node Listen | `nodelisten_v*.py` | 8993 | Listen to an ASL node's audio in the browser. Asterisk sends the node's audio through one `outstreamcmd` line in rpt.conf, which the Node card adds or removes. |

Scripts:

- `install_all_v*.sh`: installs or updates the Dashboard, SysMon, wifimon and 44helper, and Node Listen when you ask for it.
- `uninstall_all_v*.sh`: removes every tool except instmon, and leaves configs in place.
- `wifi_menu_v3_1_20261011.sh`: a text menu for WiFi status and switching networks (uses `nmcli`).

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
| File name | `sysmon_v6_13_86_20261014.py` | `sysmon_pi02w_v6_13_73_20261018.py` | `instmon_v2_58_0_20261018.py` |
| `VERSION` | `6.13.86` | `6.13.73-pi02w` | `2.57.0` |

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

Step-by-step manuals (PDF). The source is in `docs/src/install_manuals/`:

- Pi Zero 2 W build: [`docs/ASL-DVS_Pi02w_Install_Manual.pdf`](docs/ASL-DVS_Pi02w_Install_Manual.pdf)
- Full build (Pi 3, 4 or 5): [`docs/ASL-DVS_Full_Build_Install_Manual.pdf`](docs/ASL-DVS_Full_Build_Install_Manual.pdf)

Phone dialplan guide (PDF, 31 pages): dialplan nuts and bolts, stock ASL3 next to the Phone tab's dialplan, the autopatch dead key and how `rpt(node,Pv)` avoids it (Pi02w 9.3.71.10 and full 9.3.73 on). The source is in `docs/src/dialplan_guide/`:
[`docs/ASL-DVS_Pi02w_Phone_Dialplan_Guide.pdf`](docs/ASL-DVS_Pi02w_Phone_Dialplan_Guide.pdf)

Idealized node configuration (PDF, 14 pages): the target ASL3 + DVSwitch + USRP2M17 bridge-node files, port map, services and firewall for a clean build, with no identity data (placeholders only):
[`docs/ASL-DVS_Idealized_Node_Configuration.pdf`](docs/ASL-DVS_Idealized_Node_Configuration.pdf)

User manual (PDF, 103 pages): every tool, tab and button, with SysMon and 44helper in depth, troubleshooting, and port, file and service tables. Pi Zero 2 W edition with full-build notes. The source is in `docs/src/user_manual/`:
[`docs/ASL-DVS_User_Manual.pdf`](docs/ASL-DVS_User_Manual.pdf)

44helper manual (PDF, 51 pages): every 44helper tab and card in detail: the tunnel modes (split, half, full with exceptions, full) side by side, the half-tunnel and exceptions cards with all their checks, every installer step, Update, System Optimization, Config, troubleshooting and a file and routing reference. The source is in `docs/src/44helper_manual/`:
[`docs/ASL-DVS_44helper_Manual.pdf`](docs/ASL-DVS_44helper_Manual.pdf)

To rebuild a PDF from its source: `cd docs/src/<folder> && node build.mjs` (needs Playwright with Chromium; set `PLAYWRIGHT_MODULE` and `CHROMIUM_PATH` if they aren't found by default).

1. Copy the files you want onto the Pi, all in one folder.
2. Install instmon first:
   ```
   sudo python3 instmon_v2_58_0_20261018.py --install
   ```
   Then open `http://<pi-address>:8990`.
3. Install the rest with the installer:
   ```
   sudo bash install_all_v7_2_0_20261018.sh
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
script and its changelog are no longer in the repo.

## Node Listen

Node Listen is a phone-friendly page for one node on your home network: it
plays the node's audio about half a second behind, transmits with
push-to-talk, and connects to up to 10 favorites. It is optional. The installer (7.2.0 and later) asks before it
installs it on a node that doesn't have it (non-interactive: set
`INSTALL_NODELISTEN=1`), and always updates it once it is installed. instmon
(2.58.0 and later) lists it with the other tools: its library, GitHub Updates
and Full Update, which updates it only where it is installed. It also installs
on its own:

```
sudo python3 nodelisten_v0_3_0_20261019.py --install
```

Then open `http://<pi-address>:8993` (it moves you to `https://`; the
certificate is made on the Pi, so accept the browser's warning), log in with
the root password, and on the **Setup** tab pick the node, press **Send its
audio here**, then **Restart Asterisk**. That adds one line to the node's stanza in
`/etc/asterisk/rpt.conf` (a backup goes to `/etc/asl_dvs/nodelisten_backups/`):

```
outstreamcmd = /usr/bin/python3,/usr/local/bin/nodelisten.py,--feed,6200
```

Asterisk runs that command and writes the node's audio (8 kHz, 16-bit) to it;
the command passes it to Node Listen on `127.0.0.1:6200/udp`. A node takes
one `outstreamcmd`, so a node that already feeds Broadcastify is refused.
Each listener uses about 64 kbit/s; the default limit is 3. **Listen without
logging in** (Settings) lets anyone who can reach the page listen, but never
change anything.

**Push-to-talk** (0.3.0 and later) sends the phone's microphone to private
node 1921 (`rxchannel = USRP/127.0.0.1:34018:32018`), which Node Listen keeps
linked to the main node. **Add node 1921** on the Setup tab writes its stanza
and `[nodes]` line (with a backup); restart Asterisk once. A transmission
stops at the time-out (120 s by default), 1 s after audio stops arriving, or
when you let go, and PTT is refused while the node is busy unless you turn
that off. Browsers only allow the microphone on an `https://` page, which is
why HTTPS is on by default.

**Favorites:** the Connect tab offers only the (up to) 10 favorites set on the
Setup tab, where the Dashboard's ASL and EchoLink favorites can be picked from
a list. Connect and Disconnect use `rpt cmd <node> ilink 3` / `ilink 1`;
Disconnect drops linked favorites only. `--uninstall` removes the
`outstreamcmd` line and node 1921 too.

## Updating from GitHub (instmon)

The **GitHub Updates** card in instmon reads this repo's file list directly.

- **Update channel** (instmon 2.50.0 and later): **Stable** (default) installs each
  tool's build from the stable list; **Testing** (opt-in) installs the newest
  file on `main`. On Stable, a tool newer than stable is left alone, and its row
  offers **Get stable** to go back. See "Release channels and checks" below.
- **After each update** Full Update watches the tool for 60 seconds (still running,
  not restarting, answering on its port) and puts the previous version back if it
  isn't steady.

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

## Release channels and checks

Every build lands on `main`, the **testing** channel. **Stable** is a list of
proven builds, one per tool, in [`channels/stable.json`](channels). instmon
reads it from version 2.50.0 on, with Stable as the default and Testing as an
opt-in; until then instmon keeps updating from `main`.

- **Releases and cosmetic builds.** `X.Y.Z` is a release. `X.Y.Z.N` is a
  cosmetic build (text, wording, colors or layout only). Cosmetic builds never
  go to stable and don't count below.
- **When a release becomes stable** (each tool on its own count; full and
  Pi Zero 2 W builds are separate):
  - four newer releases of that tool are on `main`, and it has been there at
    least 3 days; or
  - it has been the newest release for 14 days.
- **Overrides** in `channels/overrides.json`: `hold` keeps a release off
  stable; `hotfix` puts a release on stable at once.
- **instmon** is never older than 2.50.0 on stable, the first version that
  reads channels. A build still under an old file name is never promoted.
- The `promote-stable` workflow rewrites `channels/stable.json` after every
  merge to `main` and once a day. Each entry names the file, version, commit
  and git blob hash, so a node can fetch that exact file and check it. The
  rules are in `channels/rules.json`.

The `checks` workflow runs on every pull request (`python3
ci/check_repo.py --base origin/main` runs it locally). On the files the pull
request changes it runs `py_compile`, `pyflakes`, `node --check` on the page
JavaScript and `bash -n`, and checks that:

- each new file's version matches its name, has three or four parts, and ends
  in `-pi02w` only for the Pi Zero 2 W fork;
- the version is newer than the file it replaces, and a tool file is never
  changed in place;
- a cosmetic build changes only strings, not code;
- the README lists the file and its changelog names it at the top;
- each tool has one file, and the shared launcher text is the same everywhere;
- `channels/stable.json` is not edited by hand.

## The launcher

The Pi Zero 2 W builds and the common tools start through a small file,
`/usr/local/bin/asl_dvs_launch.py`:

```
ExecStart=/usr/bin/python3 /usr/local/bin/asl_dvs_launch.py /usr/local/bin/instmon.py
```

The launcher loads the tool as a module instead of running the file directly.
That way Python keeps the compiled copy in `__pycache__` and reuses it on each
start. Python recompiles by itself after an update. Launcher version 3
(instmon 2.43.0, wifimon 5.30, 44helper 0.0.181, SysMon Pi02w 6.13.67.13 and
Dashboard Pi02w 9.3.71.15) does this for a file whose name starts with a digit
too, such as `44helper_v….py`; version 2 recompiled those on every start.

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
sudo systemctl restart sysmon nodecontrol instmon wifimon 44helper
```

Delete the file and restart to turn it back on. With `-OO`, the first start
after an update compiles the tool (and the parts of Python it uses) once more;
memory settles from the next restart on.

## Removing everything

```
sudo bash uninstall_all_v1_6_0_20261018.sh
```

This removes every tool except instmon. It leaves `/etc/asl_dvs/`,
instmon's library and every tool's config folder (`/etc/sysmon/`,
`/etc/wifimon/`, `/etc/44helper/`) in place. To remove instmon
afterwards, run its own `--uninstall`. If the SysMon Hardware tab (either build) turned off
the video driver or lowered GPU memory, it puts `/boot/firmware/config.txt` back
(reboot to apply).

## Files

| File | Build |
|---|---|
| `nodecontrol_v9_3_84_20261018.py` | Dashboard, full (current) |
| `nodecontrol_pi02w_v9_3_87_20261019.py` | Dashboard, Pi Zero 2 W (current) |
| `sysmon_v6_13_86_20261014.py` | SysMon, full (current) |
| `sysmon_pi02w_v6_13_73_20261018.py` | SysMon, Pi Zero 2 W (current) |
| `instmon_v2_58_0_20261018.py` | common |
| `wifimon_v5_38_0_20261018.py` | common |
| `44helper_v0_0_215_20261018.py` | common |
| `nodelisten_v0_3_0_20261019.py` | common |
| `install_all_v7_2_0_20261018.sh` | common |
| `uninstall_all_v1_6_0_20261018.sh` | common |
| `wifi_menu_v3_1_20261011.sh` | common |

When there is more than one version of a tool, instmon and the installer
always pick the newest.

## Comment-stripped copies and changelogs

The scripts in this repo are comment-stripped copies: comments and docstrings
are removed, and the code is otherwise unchanged. A few comment lines stay
because something reads them:

- the first line (`#!...`) and a Python `coding` line;
- the title line of each `.sh` script (for example
  `# install_all.sh  v7.1  (2026-10-12)`): instmon reads a
  shell script's version from it.

Text inside strings is left alone, including files the tools write onto the
Pi, like service units and the launcher.

The change history of each script is in [`changelogs/`](changelogs), one file
per tool and build:

| Changelog | Scripts |
|---|---|
| [`sysmon.md`](changelogs/sysmon.md) | `sysmon_v*.py` (full) |
| [`sysmon_pi02w.md`](changelogs/sysmon_pi02w.md) | `sysmon_pi02w_v*.py` |
| [`nodecontrol.md`](changelogs/nodecontrol.md) | `nodecontrol_v*.py` (full) |
| [`nodecontrol_pi02w.md`](changelogs/nodecontrol_pi02w.md) | `nodecontrol_pi02w_v*.py` |
| [`instmon.md`](changelogs/instmon.md) | `instmon_v*.py` |
| [`wifimon.md`](changelogs/wifimon.md) | `wifimon_v*.py` |
| [`44helper.md`](changelogs/44helper.md) | `44helper_v*.py` |
| [`nodelisten.md`](changelogs/nodelisten.md) | `nodelisten_v*.py` |
| [`install_all.md`](changelogs/install_all.md) | `install_all_v*.sh` |
| [`uninstall_all.md`](changelogs/uninstall_all.md) | `uninstall_all_v*.sh` |
| [`wifi_menu.md`](changelogs/wifi_menu.md) | `wifi_menu_v3_1_20261011.sh` |

Every new version adds an entry at the top of its changelog.

## License

Licensed under [Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)](https://creativecommons.org/licenses/by-nc/4.0/). See [LICENSE](LICENSE).

You may share and adapt these files if you credit KD8PGK and don't use them for commercial purposes.
