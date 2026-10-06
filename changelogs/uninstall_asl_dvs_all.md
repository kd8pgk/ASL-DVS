# Uninstaller (uninstall_asl_dvs_all) changelog

Current file: `uninstall_asl_dvs_all_v1_2.sh`. Newest entries first.

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
