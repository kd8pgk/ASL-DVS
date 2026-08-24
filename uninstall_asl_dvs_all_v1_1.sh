#!/usr/bin/env bash
#
# uninstall_asl_dvs_all.sh  v1.1
# Mass-uninstall every ASL-DVS suite component EXCEPT instmon.
#
# Removes: asl_dvs_dashboard.py, asl_dvs_m17_dashboard.py (M17/Zello fork),
#          sysmon.py, wifimon.py, asl_dvs_m17_44helper.py, asl_dvs_watchdog.sh
#
# Left untouched (always):
#   - instmon.py / instmon.service / INSTMON_LIBRARY_DIR
#   - /etc/asl_dvs/  (asl_dvs.conf, instmon_library, etc.)
#   - /etc/wifimon/wifimon.conf
#   - any other config or library directory
#
# How: each component ships its own `--uninstall` (self-installers all
# follow the same "Library Card" convention — stop+disable the service,
# remove only its own binary/symlink/unit, never touch config). This
# script just finds each installed binary and calls its own --uninstall,
# so it inherits that safety guarantee instead of re-implementing it.
#
# v1.1: asl_dvs_m17_dashboard.py (the M17/Zello fork) picked up its own
#   --install/--uninstall as of v7.753-zello, so it now goes through the
#   same COMPONENTS loop as everything else instead of the old
#   best-effort "no self-uninstaller, disable the unit manually" fallback.
#   That fallback is removed below — a self-installed
#   asl_dvs_m17_dashboard.service is now cleaned up correctly (own
#   binary + symlink removed too, not just the unit file).
#
# Usage:
#   sudo bash uninstall_asl_dvs_all.sh
#
set -u

RED=$'\033[0;31m'; GRN=$'\033[0;32m'; YEL=$'\033[0;33m'; CYN=$'\033[0;36m'; RST=$'\033[0m'
ok()   { echo "${GRN}  ✔ ${RST}$*"; }
info() { echo "${CYN}  → ${RST}$*"; }
warn() { echo "${YEL}  ⚠ ${RST}$*"; }

[[ $EUID -eq 0 ]] || { echo "${RED}Run as root: sudo bash $0${RST}"; exit 1; }

echo "== ASL-DVS Suite — Mass Uninstall (instmon, library, and config are left alone) =="
echo

# name | installed binary path | interpreter
COMPONENTS=(
    "asl_dvs_dashboard|/usr/local/bin/asl_dvs_dashboard.py|python3"
    "asl_dvs_m17_dashboard|/usr/local/bin/asl_dvs_m17_dashboard.py|python3"
    "sysmon|/usr/local/bin/sysmon.py|python3"
    "wifimon|/usr/local/bin/wifimon.py|python3"
    "44helper|/opt/44helper/asl_dvs_m17_44helper.py|python3"
    "asl_dvs_watchdog|/usr/local/bin/asl_dvs_watchdog.sh|bash"
)

for entry in "${COMPONENTS[@]}"; do
    IFS='|' read -r name path interp <<< "$entry"
    echo "-- ${name} --"
    if [[ -f "$path" ]]; then
        info "Found ${path}, running its own --uninstall..."
        if "$interp" "$path" --uninstall; then
            ok "${name} uninstalled"
        else
            warn "${name} --uninstall reported an error (see output above) — check manually"
        fi
    else
        info "Not installed at ${path}, skipping"
    fi
    echo
done

echo "== Done =="
echo "Untouched by design: instmon, /etc/asl_dvs/ (config + instmon_library), /etc/wifimon/wifimon.conf,"
echo "and both library dirs (/usr/local/lib/asl_dvs, /usr/local/lib/asl_dvs_sysmon)."
