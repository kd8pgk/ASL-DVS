#!/usr/bin/env bash
# uninstall_asl_dvs_all.sh  v1.3  (2026-10-07)
set -u

RED=$'\033[0;31m'; GRN=$'\033[0;32m'; YEL=$'\033[0;33m'; CYN=$'\033[0;36m'; RST=$'\033[0m'
ok()   { echo "${GRN}  ✔ ${RST}$*"; }
info() { echo "${CYN}  → ${RST}$*"; }
warn() { echo "${YEL}  ⚠ ${RST}$*"; }

[[ $EUID -eq 0 ]] || { echo "${RED}Run as root: sudo bash $0${RST}"; exit 1; }

echo "== ASL-DVS Suite — Mass Uninstall (instmon, library, and config are left alone) =="
echo

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

BOOT_CFG=/boot/firmware/config.txt
echo "-- config.txt (HDMI/video driver, GPU memory) --"
if [[ -f "$BOOT_CFG" ]] && grep -q -e '^#ASL-DVS-VIDEO-OFF# ' -e '^#ASL-DVS-GPUMEM-BEGIN' "$BOOT_CFG"; then
    cp -p "$BOOT_CFG" "${BOOT_CFG}.asl_dvs.bak"
    if sed -i -e 's/^#ASL-DVS-VIDEO-OFF# //' -e '/^#ASL-DVS-GPUMEM-BEGIN/,/^#ASL-DVS-GPUMEM-END/d' "$BOOT_CFG"; then
        sync
        ok "Restored the video driver and GPU memory in ${BOOT_CFG} (backup ${BOOT_CFG}.asl_dvs.bak)"
        warn "Reboot to apply"
    else
        warn "Could not edit ${BOOT_CFG} — restore it from ${BOOT_CFG}.asl_dvs.bak"
    fi
else
    info "No ASL-DVS changes in ${BOOT_CFG}, skipping"
fi
echo

echo "== Done =="
echo "Untouched by design: instmon, /etc/asl_dvs/ (config + instmon_library), /etc/wifimon/wifimon.conf,"
echo "and both library dirs (/usr/local/lib/asl_dvs, /usr/local/lib/asl_dvs_sysmon)."
