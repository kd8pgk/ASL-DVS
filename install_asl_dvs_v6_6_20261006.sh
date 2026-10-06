#!/usr/bin/env bash
# install_asl_dvs_dashboard.sh  v6.6  (2026-10-06)

set -euo pipefail

RED=$'\033[0;31m'
GRN=$'\033[0;32m'
YEL=$'\033[0;33m'
CYN=$'\033[0;36m'
BLD=$'\033[1m'
RST=$'\033[0m'

ok()   { echo "${GRN}  ✔ ${RST}$*"; }
info() { echo "${CYN}  → ${RST}$*"; }
warn() { echo "${YEL}  ⚠ ${RST}$*"; }
die()  { echo "${RED}  ✘ ${RST}$*" >&2; exit 1; }
hdr()  { echo; echo "${BLD}${CYN}══ $* ${RST}"; }
sep()  { echo "  ${CYN}──────────────────────────────────────────${RST}"; }

NONINTERACTIVE=false
for _arg in "$@"; do
    case "${_arg}" in
        --non-interactive|--auto|-y) NONINTERACTIVE=true ;;
    esac
done
if [[ ! -t 0 ]]; then
    NONINTERACTIVE=true
fi

DASH_BIN="/usr/local/bin/asl_dvs_dashboard.py"
DASH_SERVICE="asl_dvs_dashboard"
DASH_SERVICE_FILE="/etc/systemd/system/${DASH_SERVICE}.service"
DASH_PORT=8989
DASH_CONF_DIR="/etc/asl_dvs"
DASH_CONF="${DASH_CONF_DIR}/asl_dvs.conf"
LEGACY_CONF="/etc/dvswitch/dvswitch.conf"

SYSMON_BIN="/usr/local/bin/sysmon.py"
SYSMON_SERVICE="sysmon"
SYSMON_SERVICE_FILE="/etc/systemd/system/${SYSMON_SERVICE}.service"
SYSMON_PORT=9999
SYSMON_CONF_DIR="/etc/sysmon"

M17DASH_BIN="/usr/local/bin/asl_dvs_m17_dashboard.py"
M17DASH_SERVICE="asl_dvs_m17_dashboard"
M17DASH_PORT=8989

WIFIMON_BIN="/usr/local/bin/wifimon.py"
WIFIMON_SERVICE="wifimon"

HELPER_BIN="/opt/44helper/asl_dvs_m17_44helper.py"
HELPER_SERVICE="44helper"
HELPER_PORT=9997

SVX_BIN="/usr/local/bin/svx_dashboard.py"
SVX_SERVICE="svx_dashboard"
SVX_PORT=8991

INSTMON_LIBRARY_DIR="${INSTMON_LIBRARY_DIR:-/etc/asl_dvs/instmon_library}"
DASH_LIB_DIR="${INSTMON_LIBRARY_DIR}/dashboard"
M17DASH_LIB_DIR="${INSTMON_LIBRARY_DIR}/m17_dashboard"
SYSMON_LIB_DIR="${INSTMON_LIBRARY_DIR}/sysmon"
WIFIMON_LIB_DIR="${INSTMON_LIBRARY_DIR}/wifimon"
HELPER_LIB_DIR="${INSTMON_LIBRARY_DIR}/44helper"
SVX_LIB_DIR="${INSTMON_LIBRARY_DIR}/svx"

LABELS=(a b c d e f g h i j)


stage_and_select() {
    local pattern="$1"
    local label="$2"
    local lib_dir="${3:-}"
    local exclude="${4:-}"

    local SCRIPT_DIR
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    local SEARCH_PATHS=("${SCRIPT_DIR}" "$(pwd)" "/root" "/home/pi" \
                        "/home/${SUDO_USER:-pi}" "/tmp")
    [[ -n "${lib_dir}" ]] && SEARCH_PATHS+=("${lib_dir}")

    declare -A _sp
    local UNIQUE_PATHS=()
    local p
    for p in "${SEARCH_PATHS[@]}"; do
        [[ -d "${p}" && -z "${_sp[${p}]+x}" ]] || continue
        _sp["${p}"]=1
        UNIQUE_PATHS+=("${p}")
    done

    info "Searching for ${pattern} in:"
    for p in "${UNIQUE_PATHS[@]}"; do info "  ${p}/"; done

    declare -A _sf
    local RAW_FOUND=()
    local f real
    for dir in "${UNIQUE_PATHS[@]}"; do
        while IFS= read -r -d '' f; do
            real="$(realpath "${f}" 2>/dev/null || echo "${f}")"
            if [[ -z "${_sf[${real}]+x}" ]]; then
                _sf["${real}"]=1
                RAW_FOUND+=("${real}")
            fi
        done < <(if [[ -n "${exclude}" ]]; then
                     find "${dir}" -maxdepth 1 -name "${pattern}" ! -name "${exclude}" -print0 2>/dev/null
                 else
                     find "${dir}" -maxdepth 1 -name "${pattern}" -print0 2>/dev/null
                 fi)
    done

    if [[ "${#RAW_FOUND[@]}" -eq 0 ]]; then
        warn "No ${pattern} files found — ${label} will not be installed"
        CHOSEN=""
        return 1
    fi

    ok "Found ${#RAW_FOUND[@]} ${label} file(s)"

    hdr "Staging ${label} to /tmp/"
    local STAGED=()
    local base dest
    for f in "${RAW_FOUND[@]}"; do
        base="$(basename "${f}")"
        dest="/tmp/${base}"
        if [[ "${f}" != "${dest}" ]]; then
            cp -- "${f}" "${dest}"
            info "Staged: ${base}"
        else
            info "Already staged: ${base}"
        fi
        STAGED+=("${dest}")
    done

    local SORTED=()
    mapfile -t SORTED < <(
        for f in "${STAGED[@]}"; do
            printf '%s %s\n' "$(stat -c '%Y' "${f}" 2>/dev/null || echo 0)" "${f}"
        done | sort -rn | awk '{print $2}'
    )

    ok "${#SORTED[@]} file(s) staged"

    if [[ "${NONINTERACTIVE}" == "true" ]]; then
        CHOSEN="${SORTED[0]}"
        ok "Non-interactive: auto-selected newest ${label} — $(basename "${CHOSEN}")"
        return 0
    fi

    hdr "${label} — version selection"
    echo
    echo "  ${BLD}Available ${label} versions  (newest first):${RST}"
    echo

    local -A LABEL_MAP
    local IDX=0 lbl
    for f in "${SORTED[@]}"; do
        lbl="${LABELS[${IDX}]:-${IDX}}"
        if [[ "${IDX}" -eq 0 ]]; then
            echo "  ${BLD}${GRN}[${lbl}]${RST}  $(basename "${f}")  ${YEL}← newest  (default)${RST}"
        else
            echo "  ${BLD}[${lbl}]${RST}  $(basename "${f}")"
        fi
        LABEL_MAP["${lbl}"]="${f}"
        (( IDX++ )) || true
    done

    echo
    echo "  ${BLD}[n]${RST}  None — skip ${label}"
    echo

    local DEFAULT_LABEL="${LABELS[0]}"
    local CHOICE

    while true; do
        read -r -p "  Select ${label} version [${DEFAULT_LABEL}]: " CHOICE </dev/tty
        CHOICE="${CHOICE:-${DEFAULT_LABEL}}"
        CHOICE="${CHOICE,,}"
        if [[ "${CHOICE}" == "n" || "${CHOICE}" == "none" ]]; then
            CHOSEN=""
            break
        elif [[ -n "${LABEL_MAP[${CHOICE}]+x}" ]]; then
            CHOSEN="${LABEL_MAP[${CHOICE}]}"
            break
        else
            warn "Invalid choice '${CHOICE}' — enter one of: ${!LABEL_MAP[*]} n"
        fi
    done

    echo
    if [[ -n "${CHOSEN}" ]]; then
        ok "Selected: $(basename "${CHOSEN}")"
    else
        info "Skipping: ${label}"
    fi
}

pick_build() {
    PICKED_BUILD="$1"
    PICKED_WHY="$3"
    if [[ -z "${PICKED_BUILD}" && -f "$2" ]]; then
        if grep -qE '^VERSION[[:space:]]*=[[:space:]]*"[^"]*-pi02w"' "$2" 2>/dev/null; then
            PICKED_BUILD="pi02w"
        else
            PICKED_BUILD="full"
        fi
        PICKED_WHY="the installed copy"
    fi
    if [[ -z "${PICKED_BUILD}" ]]; then
        if tr -d '\0' < /proc/device-tree/model 2>/dev/null | grep -qi 'Zero 2'; then
            PICKED_BUILD="pi02w"
        else
            PICKED_BUILD="full"
        fi
        PICKED_WHY="this Pi's model"
    fi
    case "${PICKED_BUILD}" in
        pi02w|full) ;;
        *) die "$3 must be pi02w or full (got '${PICKED_BUILD}')" ;;
    esac
}

check_port() {
    local port="$1"
    local in_use=false
    if ss -tlnp "sport = :${port}" 2>/dev/null | grep -q ":${port}"; then
        in_use=true
    elif netstat -tlnp 2>/dev/null | grep -q ":${port} "; then
        in_use=true
    fi
    if [[ "${in_use}" == "true" ]]; then
        local owner
        owner="$(ss -tlnp "sport = :${port}" 2>/dev/null \
                 | awk 'NR>1 {print $NF}' | head -1 || echo "unknown")"
        warn "Port ${port} is ALREADY IN USE (by: ${owner})"
        warn "The service on this port will fail to start until resolved."
        warn "Check: ss -tlnp | grep ${port}"
    else
        ok "Port ${port} is free"
    fi
}

LAUNCHER_PATH="/usr/local/bin/asl_dvs_launch.py"
write_launcher() {
    cat > "${LAUNCHER_PATH}.tmp" <<'LAUNCHER_EOF'
#!/usr/bin/env python3
import os
import runpy
import sys

_OFF = "/etc/asl_dvs/launch_no_"
_AGAIN = "ASL_DVS_LAUNCH"

if _AGAIN in os.environ:
    if os.environ.pop(_AGAIN) == "arena":
        os.environ.pop("MALLOC_ARENA_MAX", None)
else:
    flags = []
    env = dict(os.environ)
    env[_AGAIN] = ""
    if sys.flags.optimize < 2 and not os.path.exists(_OFF + "optimize"):
        flags.append("-OO")
    if "MALLOC_ARENA_MAX" not in env and not os.path.exists(_OFF + "arena_cap"):
        env["MALLOC_ARENA_MAX"] = "2"
        env[_AGAIN] = "arena"
    if (flags or env[_AGAIN]) and sys.executable:
        try:
            os.execve(sys.executable, [sys.executable] + flags + sys.argv, env)
        except OSError:
            pass

def _trim_loop():
    import time
    time.sleep(60)
    try:
        import ctypes
        trim = ctypes.CDLL("libc.so.6").malloc_trim
    except (ImportError, OSError, AttributeError):
        return
    trim.argtypes = [ctypes.c_size_t]
    while True:
        trim(0)
        time.sleep(300)

if not os.path.exists(_OFF + "trim"):
    import threading
    threading.Thread(target=_trim_loop, name="mem-trim", daemon=True).start()

target = os.path.realpath(sys.argv[1])
name = os.path.splitext(os.path.basename(target))[0]
sys.argv = [target] + sys.argv[2:]
if name.isidentifier():
    sys.path.insert(0, os.path.dirname(target))
    runpy.run_module(name, run_name="__main__", alter_sys=True)
else:
    runpy.run_path(target, run_name="__main__")
LAUNCHER_EOF
    chmod 0755 "${LAUNCHER_PATH}.tmp"
    mv -f "${LAUNCHER_PATH}.tmp" "${LAUNCHER_PATH}"
    ok "Launcher: ${LAUNCHER_PATH}"
}

write_service() {
    local file="$1" desc="$2" bin="$3" sid="$4" launcher="${5:-}"
    cat > "${file}" <<EOF
[Unit]
Description=${desc}
After=network.target asterisk.service analog_bridge.service
Wants=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 ${launcher:+${launcher} }${bin}
Restart=on-failure
RestartSec=5
User=root
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${sid}
TimeoutStopSec=45

[Install]
WantedBy=multi-user.target
EOF
}

UP_TO_DATE_SKIP=false
uptodate_check() {
    local label="$1" chosen="$2" installed_bin="$3"
    UP_TO_DATE_SKIP=false
    [[ -z "${chosen}" || ! -f "${installed_bin}" ]] && return
    if cmp -s "${chosen}" "${installed_bin}"; then
        warn "${label} — selected file is identical to the installed version"
        if [[ "${NONINTERACTIVE}" == "true" ]]; then
            info "Non-interactive: skipping ${label} — already up to date"
            UP_TO_DATE_SKIP=true
            return
        fi
        while true; do
            read -r -p "  Reinstall anyway? [y/N]: " _ans </dev/tty
            _ans="${_ans,,}"
            case "${_ans}" in
                y|yes) ok "Proceeding with reinstall"; return ;;
                n|no|"") info "Skipping ${label} — already up to date"; UP_TO_DATE_SKIP=true; return ;;
                *) warn "Enter y or n" ;;
            esac
        done
    fi
}


CONF_CALLSIGN=""
CONF_NODE=""
CONF_LABEL=""

prompt_callsign() {
    local cs raw
    while true; do
        read -r -p "  Callsign (e.g. KD8PGK): " raw </dev/tty
        cs="${raw^^}"
        cs="${cs//[^A-Z0-9\/\-\.]/}"
        cs="${cs:0:9}"
        if [[ -n "${cs}" ]]; then
            CONF_CALLSIGN="${cs}"
            ok "Callsign: ${CONF_CALLSIGN}"
            return
        fi
        warn "Callsign cannot be empty — letters and numbers only, max 9 chars"
    done
}

prompt_node() {
    local nd raw
    while true; do
        read -r -p "  ASL Node number (digits only, e.g. 652701): " raw </dev/tty
        nd="${raw//[^0-9]/}"
        if [[ -n "${nd}" ]]; then
            CONF_NODE="${nd}"
            ok "Node: ${CONF_NODE}"
            return
        fi
        warn "Node number must be numeric and non-empty"
    done
}

prompt_label() {
    local lbl
    read -r -p "  Display label [AllStarLink Node]: " lbl </dev/tty
    CONF_LABEL="${lbl:-AllStarLink Node}"
    CONF_LABEL="${CONF_LABEL:0:40}"
    ok "Label: ${CONF_LABEL}"
}

resolve_identity() {
    local need_label="${1:-false}"
    if [[ "${NONINTERACTIVE}" == "true" ]]; then
        if [[ -z "${AUTO_CALLSIGN:-}" || -z "${AUTO_NODE:-}" ]]; then
            die "Non-interactive first-run setup requires AUTO_CALLSIGN and AUTO_NODE environment variables (e.g. export AUTO_CALLSIGN=KD8PGK AUTO_NODE=652701 before running this script, or run it interactively once first)."
        fi
        CONF_CALLSIGN="${AUTO_CALLSIGN^^}"
        CONF_CALLSIGN="${CONF_CALLSIGN//[^A-Z0-9\/\-\.]/}"
        CONF_CALLSIGN="${CONF_CALLSIGN:0:9}"
        CONF_NODE="${AUTO_NODE//[^0-9]/}"
        CONF_LABEL="${AUTO_LABEL:-AllStarLink Node}"
        CONF_LABEL="${CONF_LABEL:0:40}"
        if [[ "${need_label}" == "true" ]]; then
            ok "Non-interactive: callsign=${CONF_CALLSIGN} node=${CONF_NODE} label=\"${CONF_LABEL}\""
        else
            ok "Non-interactive: callsign=${CONF_CALLSIGN} node=${CONF_NODE}"
        fi
    else
        prompt_callsign
        prompt_node
        [[ "${need_label}" == "true" ]] && prompt_label
    fi
}

write_dash_seed() {
    {
        printf '# asl_dvs.conf — seed config written by installer\n'
        printf '[CONFIG]\n'
        printf 'asl_node=%s\n' "${CONF_NODE}"
        printf 'callsign=%s\n' "${CONF_CALLSIGN}"
    } > "${DASH_CONF}"
    ok "Seed config written: ${DASH_CONF}"
}

write_sysmon_seed() {
    local _smc="${SYSMON_CONF_DIR}/sysmon.conf"
    {
        printf '# sysmon.conf — seed config written by installer\n'
        printf '[identity]\n'
        printf 'callsign = %s\n' "${CONF_CALLSIGN}"
        printf 'node = %s\n'     "${CONF_NODE}"
        printf 'label = %s\n'    "${CONF_LABEL}"
    } > "${_smc}"
    ok "Seed config written: ${_smc}"
}

hdr "Preflight"

if [[ "${EUID}" -ne 0 ]]; then
    die "Must be run as root.  Use: sudo bash install_asl_dvs_dashboard.sh"
fi
ok "Running as root"

if ! command -v python3 &>/dev/null; then
    die "python3 not found.  Install with: apt install python3"
fi
ok "Python: $(python3 --version 2>&1)"

if ! command -v systemctl &>/dev/null; then
    die "systemctl not found — this installer requires systemd"
fi
ok "systemd available"

hdr "Operation"

_dash_exists=false
_m17dash_exists=false
_sysmon_exists=false
_wifimon_exists=false
_helper_exists=false
_svx_exists=false
systemctl is-active --quiet "${DASH_SERVICE}"    2>/dev/null && _dash_exists=true    || true
systemctl is-active --quiet "${M17DASH_SERVICE}" 2>/dev/null && _m17dash_exists=true || true
systemctl is-active --quiet "${SYSMON_SERVICE}"  2>/dev/null && _sysmon_exists=true  || true
systemctl is-active --quiet "${WIFIMON_SERVICE}" 2>/dev/null && _wifimon_exists=true || true
systemctl is-active --quiet "${HELPER_SERVICE}"  2>/dev/null && _helper_exists=true  || true
systemctl is-active --quiet "${SVX_SERVICE}"     2>/dev/null && _svx_exists=true     || true
[[ -f "${DASH_BIN}"     ]] && _dash_exists=true
[[ -f "${M17DASH_BIN}"  ]] && _m17dash_exists=true
[[ -f "${SYSMON_BIN}"   ]] && _sysmon_exists=true
[[ -f "${WIFIMON_BIN}"  ]] && _wifimon_exists=true
[[ -f "${HELPER_BIN}"   ]] && _helper_exists=true
[[ -f "${SVX_BIN}"      ]] && _svx_exists=true

if [[ "${_dash_exists}" == "true" || "${_m17dash_exists}" == "true" \
      || "${_sysmon_exists}" == "true" \
      || "${_wifimon_exists}" == "true" || "${_helper_exists}" == "true" \
      || "${_svx_exists}" == "true" ]]; then
    echo
    echo "  ${BLD}Existing installation detected:${RST}"
    [[ "${_dash_exists}"     == "true" ]] && echo "  ${GRN}  ✔${RST}  Dashboard      (${DASH_BIN})"
    [[ "${_m17dash_exists}"  == "true" ]] && echo "  ${GRN}  ✔${RST}  M17/Zello dash (${M17DASH_BIN})"
    [[ "${_sysmon_exists}"   == "true" ]] && echo "  ${GRN}  ✔${RST}  SysMon         (${SYSMON_BIN})"
    [[ "${_wifimon_exists}"  == "true" ]] && echo "  ${GRN}  ✔${RST}  wifimon        (${WIFIMON_BIN})"
    [[ "${_helper_exists}"   == "true" ]] && echo "  ${GRN}  ✔${RST}  44helper       (${HELPER_BIN})"
    [[ "${_svx_exists}"      == "true" ]] && echo "  ${GRN}  ✔${RST}  SVX Dashboard  (${SVX_BIN})"
    echo
    if [[ "${NONINTERACTIVE}" == "true" ]]; then
        MODE="update"
        info "Non-interactive: existing installation detected — defaulting to 'update' (config preserved, services restarted)"
    else
        echo "  ${BLD}[i]${RST}  Install / reinstall  ${CYN}(replaces binaries; existing config preserved)${RST}"
        echo "  ${BLD}[u]${RST}  Update binaries only  ${CYN}(preserves config; restarts services)${RST}"
        echo "  ${BLD}[q]${RST}  Quit"
        echo
        MODE=""
        while true; do
            read -r -p "  Choose operation [i/u/q]: " MODE </dev/tty
            MODE="${MODE,,}"
            case "${MODE}" in
                i|install) MODE="install"; break ;;
                u|update)  MODE="update";  break ;;
                q|quit)    echo; info "Aborted by user."; exit 0 ;;
                *) warn "Enter 'i' to install, 'u' to update, or 'q' to quit" ;;
            esac
        done
    fi
else
    info "No existing installation found — proceeding with fresh install"
    MODE="install"
fi

ok "Mode: ${MODE}"

retire_watchdog() {
    local units=() bins=() u b
    shopt -s nullglob
    for u in /etc/systemd/system/asl_dvs_watchdog*.timer \
             /etc/systemd/system/asl_dvs_watchdog*.service; do
        units+=("$(basename "${u}")")
    done
    bins=(/usr/local/bin/asl_dvs_watchdog*.sh)
    shopt -u nullglob
    if [[ ${#units[@]} -eq 0 && ${#bins[@]} -eq 0 ]]; then
        return 0
    fi
    hdr "Retiring asl_dvs_watchdog"
    for u in "${units[@]}"; do
        systemctl disable --now "${u}" 2>/dev/null || true
        rm -f "/etc/systemd/system/${u}"
        ok "Removed ${u}"
    done
    for b in "${bins[@]}"; do
        rm -f "${b}"
        ok "Removed ${b}"
    done
    systemctl daemon-reload
    systemctl reset-failed 'asl_dvs_watchdog*' 2>/dev/null || true
    info "The dashboard's own systemd watchdog (Restart=always, WatchdogSec=30) covers it."
}
retire_watchdog


hdr "Dashboard — file discovery"
CHOSEN=""
pick_build "${DASH_VARIANT:-}" "${DASH_BIN}" "DASH_VARIANT"
DASH_VARIANT="${PICKED_BUILD}"
if [[ "${DASH_VARIANT}" == "pi02w" ]]; then
    info "Dashboard build: Pi Zero 2 W (asl_dvs_dashboard_pi02w*.py), from ${PICKED_WHY}"
    stage_and_select "asl_dvs_dashboard_pi02w*.py" "Dashboard (Pi Zero 2 W)" "${DASH_LIB_DIR}" || true
else
    info "Dashboard build: full (asl_dvs_dashboard*.py without _pi02w), from ${PICKED_WHY}"
    stage_and_select "asl_dvs_dashboard*.py" "Dashboard" "${DASH_LIB_DIR}" "asl_dvs_dashboard_pi02w*.py" || true
fi
DASH_CHOSEN="${CHOSEN}"
[[ -z "${DASH_CHOSEN}" ]] && warn "No ${DASH_VARIANT} Dashboard build found -- set DASH_VARIANT=pi02w or =full to choose the other build."

if [[ -n "${DASH_CHOSEN}" ]]; then
    info "Checking syntax…"
    python3 -m py_compile "${DASH_CHOSEN}" \
        || die "Syntax error in $(basename "${DASH_CHOSEN}") — install aborted"
    ok "Syntax OK"
fi

hdr "M17/Zello dashboard — file discovery"
CHOSEN=""
stage_and_select "asl_dvs_m17_dashboard*.py" "M17/Zello dashboard" "${M17DASH_LIB_DIR}" || true
M17DASH_CHOSEN="${CHOSEN}"

if [[ -n "${M17DASH_CHOSEN}" ]]; then
    info "Checking syntax…"
    python3 -m py_compile "${M17DASH_CHOSEN}" \
        || die "Syntax error in $(basename "${M17DASH_CHOSEN}") — install aborted"
    ok "Syntax OK"
fi

hdr "SysMon — file discovery"
pick_build "${SYSMON_VARIANT:-}" "${SYSMON_BIN}" "SYSMON_VARIANT"
SYSMON_VARIANT="${PICKED_BUILD}"
case "${SYSMON_VARIANT}" in
    pi02w) info "SysMon build: Pi Zero 2 W (sysmon_pi02w*.py), from ${PICKED_WHY}" ;;
    full)  info "SysMon build: full (sysmon*.py without _pi02w), from ${PICKED_WHY}" ;;
esac
CHOSEN=""
if [[ "${SYSMON_VARIANT}" == "pi02w" ]]; then
    stage_and_select "sysmon_pi02w*.py" "SysMon (Pi Zero 2 W)" "${SYSMON_LIB_DIR}" || true
else
    stage_and_select "sysmon*.py" "SysMon" "${SYSMON_LIB_DIR}" "sysmon_pi02w*.py" || true
fi
SYSMON_CHOSEN="${CHOSEN}"
[[ -z "${SYSMON_CHOSEN}" ]] && warn "No ${SYSMON_VARIANT} SysMon build found -- set SYSMON_VARIANT=pi02w or =full to choose the other build."

if [[ -n "${SYSMON_CHOSEN}" ]]; then
    info "Checking syntax…"
    python3 -m py_compile "${SYSMON_CHOSEN}" \
        || die "Syntax error in $(basename "${SYSMON_CHOSEN}") — install aborted"
    ok "Syntax OK"
fi

hdr "wifimon — file discovery"
CHOSEN=""
stage_and_select "wifimon*.py" "wifimon" "${WIFIMON_LIB_DIR}" || true
WIFIMON_CHOSEN="${CHOSEN}"

if [[ -n "${WIFIMON_CHOSEN}" ]]; then
    info "Checking syntax…"
    python3 -m py_compile "${WIFIMON_CHOSEN}" \
        || die "Syntax error in $(basename "${WIFIMON_CHOSEN}") — install aborted"
    ok "Syntax OK"
fi

hdr "44helper — file discovery"
CHOSEN=""
stage_and_select "asl_dvs_m17_44helper*.py" "44helper" "${HELPER_LIB_DIR}" || true
HELPER_CHOSEN="${CHOSEN}"

if [[ -n "${HELPER_CHOSEN}" ]]; then
    info "Checking syntax…"
    python3 -m py_compile "${HELPER_CHOSEN}" \
        || die "Syntax error in $(basename "${HELPER_CHOSEN}") — install aborted"
    ok "Syntax OK"
fi

hdr "SVX Dashboard — file discovery"
CHOSEN=""
stage_and_select "svx_dashboard*.py" "SVX Dashboard" "${SVX_LIB_DIR}" || true
SVX_CHOSEN="${CHOSEN}"

if [[ -n "${SVX_CHOSEN}" ]]; then
    info "Checking syntax…"
    python3 -m py_compile "${SVX_CHOSEN}" \
        || die "Syntax error in $(basename "${SVX_CHOSEN}") — install aborted"
    ok "Syntax OK"
fi

if [[ -z "${DASH_CHOSEN}" && -z "${M17DASH_CHOSEN}" && -z "${SYSMON_CHOSEN}" \
      && -z "${WIFIMON_CHOSEN}" && -z "${HELPER_CHOSEN}" && -z "${SVX_CHOSEN}" ]]; then
    die "Nothing to install — no dashboard, M17/Zello dashboard, sysmon, wifimon, 44helper, or SVX dashboard files found."
fi

hdr "Up-to-date check"

uptodate_check "Dashboard" "${DASH_CHOSEN}"    "${DASH_BIN}"
[[ "${UP_TO_DATE_SKIP}" == "true" ]] && DASH_CHOSEN=""

uptodate_check "M17/Zello dashboard" "${M17DASH_CHOSEN}" "${M17DASH_BIN}"
[[ "${UP_TO_DATE_SKIP}" == "true" ]] && M17DASH_CHOSEN=""

uptodate_check "SysMon"    "${SYSMON_CHOSEN}"  "${SYSMON_BIN}"
[[ "${UP_TO_DATE_SKIP}" == "true" ]] && SYSMON_CHOSEN=""

uptodate_check "wifimon"   "${WIFIMON_CHOSEN}" "${WIFIMON_BIN}"
[[ "${UP_TO_DATE_SKIP}" == "true" ]] && WIFIMON_CHOSEN=""

uptodate_check "44helper"  "${HELPER_CHOSEN}"  "${HELPER_BIN}"
[[ "${UP_TO_DATE_SKIP}" == "true" ]] && HELPER_CHOSEN=""

uptodate_check "SVX Dashboard" "${SVX_CHOSEN}" "${SVX_BIN}"
[[ "${UP_TO_DATE_SKIP}" == "true" ]] && SVX_CHOSEN=""

if [[ -z "${DASH_CHOSEN}" && -z "${M17DASH_CHOSEN}" && -z "${SYSMON_CHOSEN}" \
      && -z "${WIFIMON_CHOSEN}" && -z "${HELPER_CHOSEN}" && -z "${SVX_CHOSEN}" ]]; then
    ok "All selected files are already up to date — nothing to install."
    exit 0
fi

hdr "Port checks"
[[ -n "${DASH_CHOSEN}"    ]] && { info "Dashboard port ${DASH_PORT}:"; check_port "${DASH_PORT}"; }
if [[ -n "${M17DASH_CHOSEN}" ]]; then
    if [[ -n "${DASH_CHOSEN}" ]]; then
        warn "Both Dashboard and M17/Zello dashboard are selected — they share port ${M17DASH_PORT} and will conflict if both end up running."
    else
        info "M17/Zello dashboard port ${M17DASH_PORT}:"; check_port "${M17DASH_PORT}"
    fi
fi
[[ -n "${SYSMON_CHOSEN}"  ]] && { info "SysMon port ${SYSMON_PORT}:";  check_port "${SYSMON_PORT}"; }
[[ -n "${HELPER_CHOSEN}"  ]] && { info "44helper port ${HELPER_PORT}:"; check_port "${HELPER_PORT}"; }
[[ -n "${SVX_CHOSEN}"     ]] && { info "SVX Dashboard port ${SVX_PORT}:"; check_port "${SVX_PORT}"; }

hdr "Stopping existing services"

stop_if_installing() {
    local svc="$1" chosen="$2"
    if [[ -z "${chosen}" ]]; then
        info "Skipping stop of ${svc} — not being reinstalled"
        return
    fi
    if systemctl is-active --quiet "${svc}" 2>/dev/null; then
        info "Stopping ${svc}…"
        systemctl stop "${svc}"
        ok "Stopped ${svc}"
    else
        info "${svc} not running"
    fi
}

stop_if_installing "${DASH_SERVICE}"    "${DASH_CHOSEN}"
stop_if_installing "${SYSMON_SERVICE}"  "${SYSMON_CHOSEN}"

if [[ -n "${DASH_CHOSEN}" ]]; then
    hdr "Installing Dashboard"

    install -m 0755 "${DASH_CHOSEN}" "${DASH_BIN}"
    ok "Installed: ${DASH_BIN}"
    info "Source : $(basename "${DASH_CHOSEN}")"

    mkdir -p "${DASH_CONF_DIR}"
    ok "Config dir: ${DASH_CONF_DIR}"

    if [[ "${MODE}" == "install" ]]; then
        if [[ -f "${DASH_CONF}" ]]; then
            ok "Config already exists: ${DASH_CONF}"
            info "Dashboard config unchanged"
        elif [[ -f "${LEGACY_CONF}" ]]; then
            info "Migrating legacy config from ${LEGACY_CONF}…"
            TS="$(date +%Y%m%d_%H%M%S)"
            BAK_COUNT=0
            for bak in "${LEGACY_CONF}".*.bak; do
                [[ -f "${bak}" ]] || continue
                cp -- "${bak}" "${DASH_CONF_DIR}/$(basename "${bak}")"
                (( BAK_COUNT++ )) || true
            done
            cp -- "${LEGACY_CONF}" "${DASH_CONF}"
            cp -- "${DASH_CONF}" "${DASH_CONF}.${TS}.bak"
            ok "Migrated → ${DASH_CONF}"
            [[ "${BAK_COUNT}" -gt 0 ]] && ok "Moved ${BAK_COUNT} legacy .bak file(s)"
            info "Original files in ${LEGACY_CONF%/*}/ left untouched"
        else
            hdr "Dashboard — first-run configuration"
            echo "  ${BLD}Enter your callsign and node number for the dashboard:${RST}"; echo
            resolve_identity false; write_dash_seed
        fi
    else
        info "Update mode — config preserved: ${DASH_CONF}"
    fi

    info "Writing service unit…"
    _dash_launcher=""
    if [[ "${DASH_VARIANT}" == "pi02w" ]]; then
        write_launcher
        _dash_launcher="${LAUNCHER_PATH}"
    fi
    write_service "${DASH_SERVICE_FILE}" \
        "ASL-DVS Node Control Dashboard" \
        "${DASH_BIN}" \
        "${DASH_SERVICE}" \
        "${_dash_launcher}"
    ok "Service unit: ${DASH_SERVICE_FILE}"
fi

if [[ -n "${M17DASH_CHOSEN}" ]]; then
    hdr "Installing M17/Zello dashboard"
    info "Delegating to: python3 $(basename "${M17DASH_CHOSEN}") --install"
    python3 "${M17DASH_CHOSEN}" --install \
        || die "M17/Zello dashboard --install failed — see output above"
    ok "M17/Zello dashboard installed, enabled, and restarted"
fi

if [[ -n "${SYSMON_CHOSEN}" ]]; then
    hdr "Installing SysMon"

    install -m 0755 "${SYSMON_CHOSEN}" "${SYSMON_BIN}"
    ok "Installed: ${SYSMON_BIN}"
    info "Source : $(basename "${SYSMON_CHOSEN}")"

    mkdir -p "${SYSMON_CONF_DIR}"
    ok "Config dir: ${SYSMON_CONF_DIR}"

    _sysmon_conf_file="${SYSMON_CONF_DIR}/sysmon.conf"
    if [[ "${MODE}" == "install" && ! -f "${_sysmon_conf_file}" ]]; then
        hdr "SysMon — first-run configuration"
        echo "  ${BLD}Enter callsign, node number, and display label for SysMon:${RST}"; echo
        resolve_identity true; write_sysmon_seed
    else
        [[ -f "${_sysmon_conf_file}" ]] && info "Config exists: ${_sysmon_conf_file}"
        info "SysMon config unchanged"
    fi

    info "Writing service unit…"
    _sysmon_launcher=""
    if [[ "${SYSMON_VARIANT}" == "pi02w" ]]; then
        write_launcher
        _sysmon_launcher="${LAUNCHER_PATH}"
    fi
    write_service "${SYSMON_SERVICE_FILE}" \
        "ASL-DVS System Monitor" \
        "${SYSMON_BIN}" \
        "${SYSMON_SERVICE}" \
        "${_sysmon_launcher}"
    ok "Service unit: ${SYSMON_SERVICE_FILE}"
fi

if [[ -n "${WIFIMON_CHOSEN}" ]]; then
    hdr "Installing wifimon"
    info "Delegating to: python3 $(basename "${WIFIMON_CHOSEN}") --install"
    python3 "${WIFIMON_CHOSEN}" --install \
        || die "wifimon --install failed — see output above"
    ok "wifimon installed, enabled, and restarted"
fi

if [[ -n "${HELPER_CHOSEN}" ]]; then
    hdr "Installing 44helper"
    info "Delegating to: python3 $(basename "${HELPER_CHOSEN}") --install"
    python3 "${HELPER_CHOSEN}" --install \
        || die "44helper --install failed — see output above"
    ok "44helper installed, enabled, and restarted"
fi

if [[ -n "${SVX_CHOSEN}" ]]; then
    hdr "Installing SVX Dashboard"
    info "Delegating to: python3 $(basename "${SVX_CHOSEN}") --install"
    python3 "${SVX_CHOSEN}" --install \
        || die "SVX Dashboard --install failed — see output above"
    ok "SVX Dashboard installed, enabled, and restarted"
fi

hdr "Enabling and starting services"

systemctl daemon-reload
ok "systemd daemon reloaded"

for svc_entry in \
    "${DASH_SERVICE}:${DASH_CHOSEN}" \
    "${SYSMON_SERVICE}:${SYSMON_CHOSEN}"; do
    svc="${svc_entry%%:*}"
    chosen="${svc_entry##*:}"
    [[ -z "${chosen}" ]] && continue
    systemctl enable "${svc}" || warn "${svc} enable failed — check unit file"
    ok "${svc} enabled (start on boot)"
    systemctl restart "${svc}" || warn "${svc} did not (re)start — check: journalctl -u ${svc} -n 30 --no-pager"
    info "${svc} restarted"
done

hdr "Startup verification"
info "Waiting for services to stabilise…"
sleep 3

for svc_entry in \
    "${DASH_SERVICE}:${DASH_CHOSEN}:${DASH_PORT}" \
    "${SYSMON_SERVICE}:${SYSMON_CHOSEN}:${SYSMON_PORT}"; do
    svc="${svc_entry%%:*}"
    rest="${svc_entry#*:}"
    chosen="${rest%%:*}"
    port="${rest##*:}"
    [[ -z "${chosen}" ]] && continue

    if systemctl is-active --quiet "${svc}"; then
        ok "${svc} is RUNNING"
    else
        warn "${svc} did not start cleanly"
        systemctl status "${svc}" --no-pager -l || true
    fi

    if ss -tlnp "sport = :${port}" 2>/dev/null | grep -q ":${port}"; then
        ok "Listening on port ${port}"
    else
        warn "Not yet listening on port ${port} — may still be initialising"
        warn "Re-check:  ss -tlnp | grep ${port}"
    fi
done

for svc_entry in \
    "${M17DASH_SERVICE}:${M17DASH_CHOSEN}:${M17DASH_PORT}" \
    "${WIFIMON_SERVICE}:${WIFIMON_CHOSEN}:" \
    "${HELPER_SERVICE}:${HELPER_CHOSEN}:${HELPER_PORT}" \
    "${SVX_SERVICE}:${SVX_CHOSEN}:${SVX_PORT}"; do
    svc="${svc_entry%%:*}"
    rest="${svc_entry#*:}"
    chosen="${rest%%:*}"
    port="${rest##*:}"
    [[ -z "${chosen}" ]] && continue

    if systemctl is-active --quiet "${svc}"; then
        ok "${svc} is RUNNING"
    else
        warn "${svc} did not start cleanly"
        systemctl status "${svc}" --no-pager -l || true
    fi

    [[ -z "${port}" ]] && continue
    if ss -tlnp "sport = :${port}" 2>/dev/null | grep -q ":${port}"; then
        ok "Listening on port ${port}"
    else
        warn "Not yet listening on port ${port} — may still be initialising"
        warn "Re-check:  ss -tlnp | grep ${port}"
    fi
done

hdr "Access URLs"

HOSTNAME_SHORT="$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo raspberrypi)"
HOSTNAME_FQDN="$(hostname -f 2>/dev/null || echo "")"

mapfile -t IP_ADDRS < <(
    ip -4 addr show 2>/dev/null \
    | awk '/inet / && !/127\.0\.0\.1/ {gsub(/\/.*/, "", $2); print $2}' \
    || hostname -I 2>/dev/null | tr ' ' '\n' | grep -v '^$' | grep -v '^127\.'
)

print_urls() {
    local name="$1" port="$2" chosen="$3"
    [[ -z "${chosen}" ]] && return
    echo
    echo "  ${BLD}${name}${RST}  ($(basename "${chosen}"))"
    sep
    echo "  Hostname  :  http://${HOSTNAME_SHORT}.local:${port}"
    [[ -n "${HOSTNAME_FQDN}" && "${HOSTNAME_FQDN}" != "${HOSTNAME_SHORT}" ]] && \
        echo "  FQDN      :  http://${HOSTNAME_FQDN}:${port}"
    if [[ "${#IP_ADDRS[@]}" -gt 0 ]]; then
        for ip in "${IP_ADDRS[@]}"; do
            echo "  Network   :  ${BLD}${GRN}http://${ip}:${port}${RST}"
        done
    else
        warn "Could not determine IP — check: hostname -I"
    fi
    echo "  Localhost :  http://localhost:${port}"
    sep
}

print_urls "ASL-DVS Node Control Dashboard"      "${DASH_PORT}"    "${DASH_CHOSEN}"
print_urls "ASL-DVS-M17 Node Control Dashboard"  "${M17DASH_PORT}" "${M17DASH_CHOSEN}"
print_urls "ASL-DVS System Monitor"              "${SYSMON_PORT}"  "${SYSMON_CHOSEN}"
print_urls "44Net Helper"                        "${HELPER_PORT}"  "${HELPER_CHOSEN}"
print_urls "SVX Dashboard"                        "${SVX_PORT}"     "${SVX_CHOSEN}"

if [[ -n "${WIFIMON_CHOSEN}" ]]; then
    echo
    echo "  ${BLD}wifimon${RST}  ($(basename "${WIFIMON_CHOSEN}"))"
    sep
    info "No web UI — runs as a background watchdog."
    info "To add/import WiFi networks: sudo python3 ${WIFIMON_BIN} --setup-wifi"
    sep
fi

echo
echo "  ${BLD}Service commands:${RST}"
[[ -n "${DASH_CHOSEN}"     ]] && echo "    Dashboard      :  systemctl {status|restart|stop} ${DASH_SERVICE}"
[[ -n "${M17DASH_CHOSEN}"  ]] && echo "    M17/Zello dash :  systemctl {status|restart|stop} ${M17DASH_SERVICE}"
[[ -n "${SYSMON_CHOSEN}"   ]] && echo "    SysMon         :  systemctl {status|restart|stop} ${SYSMON_SERVICE}"
[[ -n "${WIFIMON_CHOSEN}"  ]] && echo "    wifimon        :  systemctl {status|restart|stop} ${WIFIMON_SERVICE}"
[[ -n "${HELPER_CHOSEN}"   ]] && echo "    44helper       :  systemctl {status|restart|stop} ${HELPER_SERVICE}"
[[ -n "${SVX_CHOSEN}"      ]] && echo "    SVX Dashboard  :  systemctl {status|restart|stop} ${SVX_SERVICE}"
echo "    Logs      :  journalctl -u <service> -f"
echo
