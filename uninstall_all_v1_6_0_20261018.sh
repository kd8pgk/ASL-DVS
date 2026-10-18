#!/usr/bin/env bash
# uninstall_all.sh  v1.6.0  (2026-10-18)
set -u

RED=$'\033[0;31m'; GRN=$'\033[0;32m'; YEL=$'\033[0;33m'; CYN=$'\033[0;36m'; RST=$'\033[0m'
ok()   { echo "${GRN}  ✔ ${RST}$*"; }
info() { echo "${CYN}  → ${RST}$*"; }
warn() { echo "${YEL}  ⚠ ${RST}$*"; }

[[ $EUID -eq 0 ]] || { echo "${RED}Run as root: sudo bash $0${RST}"; exit 1; }

echo "== ASL-DVS Suite — Mass Uninstall (instmon, library, and config are left alone) =="
echo

DASH_PATH=/usr/local/bin/nodecontrol.py
if [[ ! -e "$DASH_PATH" && -e /usr/local/bin/asl_dvs_dashboard.py ]]; then
    DASH_PATH=/usr/local/bin/asl_dvs_dashboard.py
fi

HELPER_PATH=/usr/local/bin/44helper.py
if [[ ! -e "$HELPER_PATH" && -e /opt/44helper/asl_dvs_m17_44helper.py ]]; then
    HELPER_PATH=/opt/44helper/asl_dvs_m17_44helper.py
fi

COMPONENTS=(
    "nodecontrol|${DASH_PATH}|python3"
    "sysmon|/usr/local/bin/sysmon.py|python3"
    "wifimon|/usr/local/bin/wifimon.py|python3"
    "44helper|${HELPER_PATH}|python3"
    "nodelisten|/usr/local/bin/nodelisten.py|python3"
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
echo "Untouched by design: instmon (and /usr/local/lib/asl_dvs/instmon), /etc/asl_dvs/ (config + instmon_library),"
echo "/etc/sysmon/, /etc/wifimon/ and /etc/44helper/."
if grep -q 'nodelisten' /etc/asterisk/rpt.conf 2>/dev/null; then
    warn "rpt.conf still mentions nodelisten — check /etc/asterisk/rpt.conf"
fi
