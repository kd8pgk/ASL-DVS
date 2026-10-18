# Uninstaller (uninstall_all) changelog

Current file: `uninstall_all_v1_6_0_20261018.sh`. Newest entries first.

## 1.6.0 (2026-10-18)

- Removes **Node Listen** too, with its own `--uninstall`
  (`/usr/local/bin/nodelisten.py`), after 44helper. That takes its `outstreamcmd`
  line out of `/etc/asterisk/rpt.conf` (backup in `/etc/asl_dvs/nodelisten_backups/`)
  and says to restart Asterisk; its config `/etc/asl_dvs/nodelisten.conf` stays,
  like the other configs.
- At the end, warns if rpt.conf still mentions nodelisten.
- Moves to the three-part version numbers (1.5 -> 1.6.0).

## 1.5 (2026-10-12)

- Renamed `uninstall_all_v….sh` (was `uninstall_asl_dvs_all_v….sh`); the title
  line is now `# uninstall_all.sh  v1.5`. instmon 2.43.0 runs it as the
  uninstaller.
- The Dashboard is uninstalled as `nodecontrol` from
  `/usr/local/bin/nodecontrol.py`, or from `/usr/local/bin/asl_dvs_dashboard.py`
  on a node that hasn't switched.
- Tested in the same container run as installer 7.1: every tool but instmon
  removed, `/usr/local/lib/asl_dvs/` gone, configs kept.

## 1.4 (2026-10-12)

For the standard install layout (each tool in `/usr/local/lib/asl_dvs/<tool>/`,
linked from `/usr/local/bin`).

- 44helper is found at `/usr/local/bin/44helper.py` (0.0.180 and later), or at
  `/opt/44helper/asl_dvs_m17_44helper.py` on an older install, and its own
  `--uninstall` runs from there.
- Removed the M17/Zello dashboard and Watchdog entries (no longer in the repo;
  the installer still removes an old Watchdog).
- The closing note names what is left: instmon and its lib folder,
  `/etc/asl_dvs/`, and the `/etc/sysmon/`, `/etc/wifimon/` and `/etc/44helper/`
  config folders. Each tool's own `--uninstall` now removes its lib folder, so
  the old note about the two library folders being left was dropped.
- Tested in a container with `systemctl` stubbed: a node with the Dashboard,
  SysMon, wifimon and instmon in the new layout and 44helper 0.0.179 still in
  `/opt`, and again with 44helper 0.0.180. Every tool but instmon was removed,
  including both 44helper links; instmon, the launcher it uses and all config
  folders stayed.

## 1.3 (2026-10-07)

- After the tools are removed, puts back the SysMon Pi02w Hardware-tab boot settings in
  `/boot/firmware/config.txt`: removes the `#ASL-DVS-VIDEO-OFF# ` prefix (video driver back
  on) and the `#ASL-DVS-GPUMEM-BEGIN` … `#ASL-DVS-GPUMEM-END` block (GPU memory back to the
  default). Saves `config.txt.asl_dvs.bak` first and says a reboot is needed. Skipped when
  the file has no ASL-DVS markers.

## 1.2 (2026-10-06)

- No code change from 1.1. Repo copy is comment-stripped. The change history that was in the file's comments now lives in this changelog. The title line stays: instmon reads the script's version from it.


## Earlier history

Carried over unchanged from the comments of the files below.

### uninstall_asl_dvs_all_v1_2.sh (header comments, as of 1.1)

```text
uninstall_asl_dvs_all.sh  v1.2  (2026-10-06)
Mass-uninstall every ASL-DVS suite component EXCEPT instmon.

Removes: asl_dvs_dashboard.py, asl_dvs_m17_dashboard.py (M17/Zello fork),
         sysmon.py, wifimon.py, asl_dvs_m17_44helper.py, asl_dvs_watchdog.sh

Left untouched (always):
  - instmon.py / instmon.service / INSTMON_LIBRARY_DIR
  - /etc/asl_dvs/  (asl_dvs.conf, instmon_library, etc.)
  - /etc/wifimon/wifimon.conf
  - any other config or library directory

How: each component ships its own `--uninstall` (self-installers all
follow the same "Library Card" convention — stop+disable the service,
remove only its own binary/symlink/unit, never touch config). This
script just finds each installed binary and calls its own --uninstall,
so it inherits that safety guarantee instead of re-implementing it.

v1.1: asl_dvs_m17_dashboard.py (the M17/Zello fork) picked up its own
  --install/--uninstall as of v7.753-zello, so it now goes through the
  same COMPONENTS loop as everything else instead of the old
  best-effort "no self-uninstaller, disable the unit manually" fallback.
  That fallback is removed below — a self-installed
  asl_dvs_m17_dashboard.service is now cleaned up correctly (own
  binary + symlink removed too, not just the unit file).

Usage:
  sudo bash uninstall_asl_dvs_all.sh
```
