# Installer (install_asl_dvs) changelog

Current file: `install_asl_dvs_v6_6_20261006.sh`. Newest entries first.

## 6.6 (2026-10-06)

- Launcher version 2 (`/usr/local/bin/asl_dvs_launch.py`, the same file every ASL-DVS `--install` writes) adds three memory savers, each with an off switch. Create the file and restart the service to turn one off; delete it and restart to turn it back on.
  - `python3 -OO`: drops docstrings from the loaded code. Off: `/etc/asl_dvs/launch_no_optimize`
  - `MALLOC_ARENA_MAX=2`: at most 2 malloc pools instead of up to 8 per CPU core. Off: `/etc/asl_dvs/launch_no_arena_cap`
  - `malloc_trim`: 1 minute after start, then every 5 minutes, freed memory is handed back to Linux. Off: `/etc/asl_dvs/launch_no_trim`
  
  The service files are unchanged: the launcher starts Python once more with `-OO` and `MALLOC_ARENA_MAX` (same PID, so systemd notify and watchdog are not affected). The launcher itself is comment-stripped too.

- Repo copy is comment-stripped. The change history that was in the file's comments now lives in this changelog. The title line (`# install_asl_dvs_dashboard.sh  v6.6 ...`) stays: instmon reads the script's version from it.


## Earlier history

Carried over unchanged from the comments of the files below.

### install_asl_dvs_v6_6_20261006.sh (header comments)

```text
install_asl_dvs_dashboard.sh  v6.6  (2026-10-06)
Build: common (all nodes, including Pi Zero 2 W)
Installs or updates:
  ASL-DVS Node Control Dashboard  (port 8989)
  ASL-DVS-M17 Node Control Dashboard (M17/Zello fork, port 8989)
  ASL-DVS SysMon                  (port 9999)
  wifimon  — WiFi/voltage watchdog (no web UI, no port)
  44helper — 44Net Connect / firewall / router dashboard (port 9997)
  SVX Dashboard — standalone SVXLink node controller (port 8991)
  (asl_dvs_watchdog is retired as of v6.4 -- an installed copy is
   removed, see the v6.4 note below)

  Dashboard and its M17/Zello fork are two separate builds of the SAME
  role — pick whichever one file you actually deploy on a given node,
  not both. They share port 8989 and (not by accident) the exact same
  config file, /etc/asl_dvs/asl_dvs.conf; running both at once on one
  node will fight over the port. This installer will happily stage and
  install both if both are found, but it does not stop you from doing
  that, so don't unless you've moved one to a different port yourself.

Usage:
  sudo bash install_asl_dvs_dashboard.sh
  sudo bash install_asl_dvs_dashboard.sh --non-interactive   (or --auto, -y)

Searches the current directory, common locations, AND the instmon
web installer's staging library for:
  asl_dvs_dashboard*.py
  sysmon*.py
  wifimon*.py
  asl_dvs_m17_44helper*.py
Each component is optional — any subset may be installed.

v5.3: Added the instmon library subfolders to the discovery search
path (${INSTMON_LIBRARY_DIR:-/etc/asl_dvs/instmon_library}/dashboard
and .../sysmon), so files staged via instmon's "Upload & stage"
button show up here too, without needing to be copied to /tmp or
/root by hand first. Override the library root with the
INSTMON_LIBRARY_DIR env var if instmon is configured with a
non-default path on this node.

v5.4: Added a non-interactive mode. Previously every `read -r -p
... </dev/tty` prompt would just hang forever when this script was
run from a backgrounded subprocess with no attached terminal --
exactly what instmon's "Run Script" button does (Python's
subprocess.Popen gives it no tty). Non-interactive mode is
auto-detected whenever stdin isn't a terminal (covers the instmon
case with zero cooperation needed from the caller), and can also be
forced manually with --non-interactive / --auto / -y for testing.
In this mode:
  - version selection always takes the newest staged file
  - "reinstall anyway?" on an up-to-date file defaults to skip (n)
  - operation mode defaults to "update" if an existing install is
    found, "install" otherwise (never prompts, never quits)
  - first-run callsign/node/label prompts are replaced by the
    AUTO_CALLSIGN / AUTO_NODE / AUTO_LABEL environment variables.
    If a first-run config is needed and AUTO_CALLSIGN or AUTO_NODE
    is missing, the script dies with a clear message instead of
    hanging -- there's no safe default identity to invent.

v6.0: Added wifimon and 44helper as installable components, so this
is now the single entry point for the whole fleet instead of just
dashboard+sysmon.

  DESIGN NOTE — dashboard/sysmon vs. wifimon/44helper install path:
  Dashboard and sysmon are installed the original way: this script
  copies the binary and writes the systemd unit itself (write_service()
  below). wifimon and 44helper are NOT installed that way — instead
  this script shells out to each script's own embedded
  `python3 <file> --install`. Reason: those two already ship a correct,
  self-contained installer (own bin path — /usr/local/bin for wifimon,
  /opt/44helper for 44helper — own service unit content, e.g. wifimon's
  Nice/OOMScoreAdjust priorities), and reimplementing that in bash would
  mean maintaining two copies of each unit file that could drift apart.
  Both self-installers were audited safe for unattended use: 44helper's
  --install has no interactive input() calls anywhere in its path;
  wifimon's install_service() only reaches an interactive prompt when
  stdin is a tty (guarded internally), so it never hangs when this
  script runs non-interactively. Both self-installers' `enable --now`
  bug (the same STFU-visibility-class bug found in the dashboard —
  re-running --install was a no-op on an already-active service,
  leaving the old process in memory) is fixed as of wifimon v4.4,
  asl_dvs_dashboard v7.777, sysmon v6.5.4, and 44helper v0.0.11 — this
  installer's own "install all, including silent auto-install" promise
  depends on that fix, so treat any of the four falling below those
  versions as a blocker, not a cosmetic issue.

  wifimon has no web UI/port; its config (WiFi networks/PSKs) is
  intentionally NOT seeded by this installer — that stays wifimon's
  own job via --setup-wifi, run manually after install. 44helper's
  config also self-initializes with defaults on first run; no identity
  seeding needed for either (AUTO_CALLSIGN/AUTO_NODE only apply to
  dashboard/sysmon, unchanged from v5.4).

v6.1: Added asl_dvs_watchdog as a fifth delegated self-installer,
  same pattern as wifimon/44helper — this script never writes its
  unit files directly, it shells out to the watchdog's own
  `bash <file> --install`. Unlike wifimon/44helper the watchdog has
  no persistent daemon of its own (it's a oneshot + timer pair), so
  there's no equivalent of the "enable --now is a no-op on an
  already-active unit" bug class to worry about here — every timer
  firing re-execs whatever binary currently sits at
  /usr/local/bin/asl_dvs_watchdog.sh, so a fresh --install always
  takes effect on the very next check regardless of what was running
  before. No identity seeding needed (no config file at all).

v6.2: Added the M17/Zello dashboard fork (asl_dvs_m17_dashboard.py) as
  a sixth delegated self-installer, now that it ships its own
  --install/--uninstall (as of its own v7.753-zello) instead of the
  old manual-cp-only deploy path. It follows the exact same delegation
  pattern as wifimon/44helper/watchdog above: this script only
  discovers, stages, and syntax-checks the file, then shells out to
  `python3 <file> --install`, which does its own copy + symlink +
  service unit (Type=notify, WatchdogSec=30) + enable + restart. No
  identity seeding here either — it shares asl_dvs.conf with the
  regular dashboard and reads/writes it the same way that dashboard
  does, so if a seed config was already written for one fork the other
  picks it straight up with no separate prompt.

v6.3: Added SVX Dashboard (svx_dashboard.py) as a seventh delegated
  self-installer, same pattern as wifimon/44helper/M17-dash above: this
  script only discovers, stages, and syntax-checks the file, then shells
  out to `python3 <file> --install`, which does its own copy + symlink +
  service unit + enable + restart (see svx_dashboard's own
  install_service()). Own, separate config file (not the shared
  asl_dvs.conf), so no identity seeding. Port 8991 — deliberately chosen
  to avoid instmon's own 8990, which svx_dashboard's PORT constant used
  to collide with before that was fixed upstream.

v6.4: asl_dvs_watchdog retired.  The dashboard's own unit already has
  Restart=always + WatchdogSec=30 (systemd restarts it if it dies or
  hangs), so the external curl watchdog added little, and v2.2 of it
  restarted a healthy v9.x dashboard every ~50 s because /api/status
  now needs a login.  This installer no longer finds, stages or
  installs asl_dvs_watchdog*.sh; instead, on every run, it stops,
  disables and deletes any installed watchdog timer/service (including
  instance-suffixed ones) and /usr/local/bin/asl_dvs_watchdog*.sh.
  Staged copies in the instmon library are left alone and ignored.

v6.5: SysMon and Dashboard build choice.  Each now comes in two builds
  that match the same file pattern: the full one (sysmon_v*.py,
  asl_dvs_dashboard_v*.py) and the lighter Pi Zero 2 W one
  (sysmon_pi02w_v*.py, asl_dvs_dashboard_pi02w_v*.py, VERSION
  "x.y.z-pi02w").  Picking the newest file by date could put either on
  either kind of Pi, so the build is chosen first, per component, and
  only that build's files are offered:
    1. SYSMON_VARIANT / DASH_VARIANT = pi02w or full, if set;
    2. otherwise the build already installed (its VERSION line);
    3. otherwise pi02w on a "Raspberry Pi Zero 2 W" (device-tree
       model), full on anything else.
  Every ASL-DVS file names its build in a header line: "Build: Pi Zero
  2 W fork of vX.Y.Z" for a fork (also _pi02w_ in the file name and
  -pi02w on its VERSION) or "Build: common (all nodes, including Pi Zero
  2 W)" for a tool every node runs.
  No file of the chosen build found -> that component is not installed
  (with a warning saying how to override); the other build is never
  substituted.
  A Pi02w build is started through /usr/local/bin/asl_dvs_launch.py
  (written here, same file the Pi02w builds' own --install writes):
  run directly, Python compiles the whole file on every start and keeps
  that memory (sysmon ~54 MB, dashboard ~45 MB); started through the
  launcher it is imported, so Python saves the compiled copy in
  __pycache__ and reuses it (~26 MB and ~25 MB, twice as fast to start).

v6.6: Launcher version 2 (the same file every ASL-DVS --install writes):
  three memory savers, each with an off switch -- python3 -OO (drops
  docstrings from the loaded code; off: /etc/asl_dvs/launch_no_optimize),
  MALLOC_ARENA_MAX=2 (at most 2 malloc pools instead of up to 8 per CPU
  core; off: /etc/asl_dvs/launch_no_arena_cap) and malloc_trim every 5
  minutes (freed memory handed back to Linux; off:
  /etc/asl_dvs/launch_no_trim).  Create the file and restart the service
  to turn one off.  The service files are unchanged; the launcher starts
  Python once more with -OO and MALLOC_ARENA_MAX (same PID).
```
