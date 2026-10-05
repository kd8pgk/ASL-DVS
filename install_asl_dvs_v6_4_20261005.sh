#!/usr/bin/env bash
#
# install_asl_dvs_dashboard.sh  v6.4  (2026-10-05)
# Installs or updates:
#   ASL-DVS Node Control Dashboard  (port 8989)
#   ASL-DVS-M17 Node Control Dashboard (M17/Zello fork, port 8989)
#   ASL-DVS SysMon                  (port 9999)
#   wifimon  — WiFi/voltage watchdog (no web UI, no port)
#   44helper — 44Net Connect / firewall / router dashboard (port 9997)
#   SVX Dashboard — standalone SVXLink node controller (port 8991)
#   (asl_dvs_watchdog is retired as of v6.4 -- an installed copy is
#    removed, see the v6.4 note below)
#
#   Dashboard and its M17/Zello fork are two separate builds of the SAME
#   role — pick whichever one file you actually deploy on a given node,
#   not both. They share port 8989 and (not by accident) the exact same
#   config file, /etc/asl_dvs/asl_dvs.conf; running both at once on one
#   node will fight over the port. This installer will happily stage and
#   install both if both are found, but it does not stop you from doing
#   that, so don't unless you've moved one to a different port yourself.
#
# Usage:
#   sudo bash install_asl_dvs_dashboard.sh
#   sudo bash install_asl_dvs_dashboard.sh --non-interactive   (or --auto, -y)
#
# Searches the current directory, common locations, AND the instmon
# web installer's staging library for:
#   asl_dvs_dashboard*.py
#   sysmon*.py
#   wifimon*.py
#   asl_dvs_m17_44helper*.py
# Each component is optional — any subset may be installed.
#
# v5.3: Added the instmon library subfolders to the discovery search
# path (${INSTMON_LIBRARY_DIR:-/etc/asl_dvs/instmon_library}/dashboard
# and .../sysmon), so files staged via instmon's "Upload & stage"
# button show up here too, without needing to be copied to /tmp or
# /root by hand first. Override the library root with the
# INSTMON_LIBRARY_DIR env var if instmon is configured with a
# non-default path on this node.
#
# v5.4: Added a non-interactive mode. Previously every `read -r -p
# ... </dev/tty` prompt would just hang forever when this script was
# run from a backgrounded subprocess with no attached terminal --
# exactly what instmon's "Run Script" button does (Python's
# subprocess.Popen gives it no tty). Non-interactive mode is
# auto-detected whenever stdin isn't a terminal (covers the instmon
# case with zero cooperation needed from the caller), and can also be
# forced manually with --non-interactive / --auto / -y for testing.
# In this mode:
#   - version selection always takes the newest staged file
#   - "reinstall anyway?" on an up-to-date file defaults to skip (n)
#   - operation mode defaults to "update" if an existing install is
#     found, "install" otherwise (never prompts, never quits)
#   - first-run callsign/node/label prompts are replaced by the
#     AUTO_CALLSIGN / AUTO_NODE / AUTO_LABEL environment variables.
#     If a first-run config is needed and AUTO_CALLSIGN or AUTO_NODE
#     is missing, the script dies with a clear message instead of
#     hanging -- there's no safe default identity to invent.
#
# v6.0: Added wifimon and 44helper as installable components, so this
# is now the single entry point for the whole fleet instead of just
# dashboard+sysmon.
#
#   DESIGN NOTE — dashboard/sysmon vs. wifimon/44helper install path:
#   Dashboard and sysmon are installed the original way: this script
#   copies the binary and writes the systemd unit itself (write_service()
#   below). wifimon and 44helper are NOT installed that way — instead
#   this script shells out to each script's own embedded
#   `python3 <file> --install`. Reason: those two already ship a correct,
#   self-contained installer (own bin path — /usr/local/bin for wifimon,
#   /opt/44helper for 44helper — own service unit content, e.g. wifimon's
#   Nice/OOMScoreAdjust priorities), and reimplementing that in bash would
#   mean maintaining two copies of each unit file that could drift apart.
#   Both self-installers were audited safe for unattended use: 44helper's
#   --install has no interactive input() calls anywhere in its path;
#   wifimon's install_service() only reaches an interactive prompt when
#   stdin is a tty (guarded internally), so it never hangs when this
#   script runs non-interactively. Both self-installers' `enable --now`
#   bug (the same STFU-visibility-class bug found in the dashboard —
#   re-running --install was a no-op on an already-active service,
#   leaving the old process in memory) is fixed as of wifimon v4.4,
#   asl_dvs_dashboard v7.777, sysmon v6.5.4, and 44helper v0.0.11 — this
#   installer's own "install all, including silent auto-install" promise
#   depends on that fix, so treat any of the four falling below those
#   versions as a blocker, not a cosmetic issue.
#
#   wifimon has no web UI/port; its config (WiFi networks/PSKs) is
#   intentionally NOT seeded by this installer — that stays wifimon's
#   own job via --setup-wifi, run manually after install. 44helper's
#   config also self-initializes with defaults on first run; no identity
#   seeding needed for either (AUTO_CALLSIGN/AUTO_NODE only apply to
#   dashboard/sysmon, unchanged from v5.4).
#
# v6.1: Added asl_dvs_watchdog as a fifth delegated self-installer,
#   same pattern as wifimon/44helper — this script never writes its
#   unit files directly, it shells out to the watchdog's own
#   `bash <file> --install`. Unlike wifimon/44helper the watchdog has
#   no persistent daemon of its own (it's a oneshot + timer pair), so
#   there's no equivalent of the "enable --now is a no-op on an
#   already-active unit" bug class to worry about here — every timer
#   firing re-execs whatever binary currently sits at
#   /usr/local/bin/asl_dvs_watchdog.sh, so a fresh --install always
#   takes effect on the very next check regardless of what was running
#   before. No identity seeding needed (no config file at all).
#
# v6.2: Added the M17/Zello dashboard fork (asl_dvs_m17_dashboard.py) as
#   a sixth delegated self-installer, now that it ships its own
#   --install/--uninstall (as of its own v7.753-zello) instead of the
#   old manual-cp-only deploy path. It follows the exact same delegation
#   pattern as wifimon/44helper/watchdog above: this script only
#   discovers, stages, and syntax-checks the file, then shells out to
#   `python3 <file> --install`, which does its own copy + symlink +
#   service unit (Type=notify, WatchdogSec=30) + enable + restart. No
#   identity seeding here either — it shares asl_dvs.conf with the
#   regular dashboard and reads/writes it the same way that dashboard
#   does, so if a seed config was already written for one fork the other
#   picks it straight up with no separate prompt.
#
# v6.3: Added SVX Dashboard (svx_dashboard.py) as a seventh delegated
#   self-installer, same pattern as wifimon/44helper/M17-dash above: this
#   script only discovers, stages, and syntax-checks the file, then shells
#   out to `python3 <file> --install`, which does its own copy + symlink +
#   service unit + enable + restart (see svx_dashboard's own
#   install_service()). Own, separate config file (not the shared
#   asl_dvs.conf), so no identity seeding. Port 8991 — deliberately chosen
#   to avoid instmon's own 8990, which svx_dashboard's PORT constant used
#   to collide with before that was fixed upstream.
#
# v6.4: asl_dvs_watchdog retired.  The dashboard's own unit already has
#   Restart=always + WatchdogSec=30 (systemd restarts it if it dies or
#   hangs), so the external curl watchdog added little, and v2.2 of it
#   restarted a healthy v9.x dashboard every ~50 s because /api/status
#   now needs a login.  This installer no longer finds, stages or
#   installs asl_dvs_watchdog*.sh; instead, on every run, it stops,
#   disables and deletes any installed watchdog timer/service (including
#   instance-suffixed ones) and /usr/local/bin/asl_dvs_watchdog*.sh.
#   Staged copies in the instmon library are left alone and ignored.

set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
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

# ── Non-interactive mode ──────────────────────────────────────────────────────
# Auto-detected from stdin not being a tty (the instmon "Run Script"
# case), or forced explicitly for manual testing.
NONINTERACTIVE=false
for _arg in "$@"; do
    case "${_arg}" in
        --non-interactive|--auto|-y) NONINTERACTIVE=true ;;
    esac
done
if [[ ! -t 0 ]]; then
    NONINTERACTIVE=true
fi

# ── Constants ─────────────────────────────────────────────────────────────────
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

# asl_dvs_m17_dashboard (M17/Zello fork) also installs itself via its own
# `--install` (same delegation pattern as wifimon/44helper below)
# — these paths are only used here for existing-install detection and
# up-to-date comparison, never written to directly.
M17DASH_BIN="/usr/local/bin/asl_dvs_m17_dashboard.py"
M17DASH_SERVICE="asl_dvs_m17_dashboard"
M17DASH_PORT=8989

# wifimon and 44helper install themselves via their own `--install` (see
# design note above) — these paths are only used here for existing-install
# detection and up-to-date comparison, never written to directly.
WIFIMON_BIN="/usr/local/bin/wifimon.py"
WIFIMON_SERVICE="wifimon"

HELPER_BIN="/opt/44helper/asl_dvs_m17_44helper.py"
HELPER_SERVICE="44helper"
HELPER_PORT=9997

# svx_dashboard installs itself via its own `--install` (same delegation
# pattern as wifimon/44helper above) — these paths are only used here for
# existing-install detection and up-to-date comparison, never written to
# directly.
SVX_BIN="/usr/local/bin/svx_dashboard.py"
SVX_SERVICE="svx_dashboard"
SVX_PORT=8991

# instmon web installer's staging library — same env-var convention
# instmon.py itself uses (INSTMON_LIBRARY_DIR), so pointing instmon
# at a non-default library root also repoints this script.
INSTMON_LIBRARY_DIR="${INSTMON_LIBRARY_DIR:-/etc/asl_dvs/instmon_library}"
DASH_LIB_DIR="${INSTMON_LIBRARY_DIR}/dashboard"
M17DASH_LIB_DIR="${INSTMON_LIBRARY_DIR}/m17_dashboard"
SYSMON_LIB_DIR="${INSTMON_LIBRARY_DIR}/sysmon"
WIFIMON_LIB_DIR="${INSTMON_LIBRARY_DIR}/wifimon"
HELPER_LIB_DIR="${INSTMON_LIBRARY_DIR}/44helper"
SVX_LIB_DIR="${INSTMON_LIBRARY_DIR}/svx"

LABELS=(a b c d e f g h i j)

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

# stage_and_select PATTERN LABEL [LIB_DIR]
stage_and_select() {
    local pattern="$1"
    local label="$2"
    local lib_dir="${3:-}"

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
        done < <(find "${dir}" -maxdepth 1 -name "${pattern}" -print0 2>/dev/null)
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

write_service() {
    local file="$1" desc="$2" bin="$3" sid="$4"
    cat > "${file}" <<EOF
[Unit]
Description=${desc}
After=network.target asterisk.service analog_bridge.service
Wants=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 ${bin}
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

# ── Config-prompt helpers ─────────────────────────────────────────────────────

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

# resolve_identity NEED_LABEL
# Sets CONF_CALLSIGN / CONF_NODE / CONF_LABEL. In non-interactive mode
# this reads AUTO_CALLSIGN / AUTO_NODE / AUTO_LABEL instead of
# prompting -- dies with a clear message if a first-run config is
# needed and AUTO_CALLSIGN or AUTO_NODE isn't set, since there's no
# safe default identity to invent for a live node.
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

# ══════════════════════════════════════════════════════════════════════════════
# PREFLIGHT
# ══════════════════════════════════════════════════════════════════════════════
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

# ══════════════════════════════════════════════════════════════════════════════
# INSTALL vs UPDATE
# ══════════════════════════════════════════════════════════════════════════════
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

# ══════════════════════════════════════════════════════════════════════════════
# RETIRE asl_dvs_watchdog  (v6.4)
# ══════════════════════════════════════════════════════════════════════════════
# Removes any installed watchdog: every asl_dvs_watchdog*.timer/.service unit
# (instance-suffixed ones too) and /usr/local/bin/asl_dvs_watchdog*.sh.  The
# dashboard's own systemd watchdog (Restart=always, WatchdogSec=30) covers it.
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

# ══════════════════════════════════════════════════════════════════════════════
# DISCOVER + STAGE + SELECT
# ══════════════════════════════════════════════════════════════════════════════

hdr "Dashboard — file discovery"
CHOSEN=""
stage_and_select "asl_dvs_dashboard*.py" "Dashboard" "${DASH_LIB_DIR}" || true
DASH_CHOSEN="${CHOSEN}"

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
CHOSEN=""
stage_and_select "sysmon*.py" "SysMon" "${SYSMON_LIB_DIR}" || true
SYSMON_CHOSEN="${CHOSEN}"

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

# ══════════════════════════════════════════════════════════════════════════════
# UP-TO-DATE CHECK
# ══════════════════════════════════════════════════════════════════════════════
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

# ══════════════════════════════════════════════════════════════════════════════
# PORT CHECKS
# ══════════════════════════════════════════════════════════════════════════════
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
# wifimon has no web UI/port — nothing to check.

# ══════════════════════════════════════════════════════════════════════════════
# STOP RUNNING SERVICES
# ══════════════════════════════════════════════════════════════════════════════
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
# M17/Zello dashboard, wifimon, and 44helper are NOT pre-stopped here —
# their own --install (invoked below) does enable + restart itself, which
# reloads the running code without a separate stop step.

# ══════════════════════════════════════════════════════════════════════════════
# INSTALL DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
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
    write_service "${DASH_SERVICE_FILE}" \
        "ASL-DVS Node Control Dashboard" \
        "${DASH_BIN}" \
        "${DASH_SERVICE}"
    ok "Service unit: ${DASH_SERVICE_FILE}"
fi

# ══════════════════════════════════════════════════════════════════════════════
# INSTALL M17/ZELLO DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
# Delegated to the fork's own --install (same pattern as wifimon/44helper/
# watchdog — see design note at top of file). It copies itself to
# /usr/local/lib/asl_dvs/, symlinks /usr/local/bin/asl_dvs_m17_dashboard.py,
# writes its own service unit (Type=notify, WatchdogSec=30), then does
# enable + restart. It shares asl_dvs.conf with the regular dashboard and
# reads it the same way, so no separate identity seeding is needed here.
if [[ -n "${M17DASH_CHOSEN}" ]]; then
    hdr "Installing M17/Zello dashboard"
    info "Delegating to: python3 $(basename "${M17DASH_CHOSEN}") --install"
    python3 "${M17DASH_CHOSEN}" --install \
        || die "M17/Zello dashboard --install failed — see output above"
    ok "M17/Zello dashboard installed, enabled, and restarted"
fi

# ══════════════════════════════════════════════════════════════════════════════
# INSTALL SYSMON
# ══════════════════════════════════════════════════════════════════════════════
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
    write_service "${SYSMON_SERVICE_FILE}" \
        "ASL-DVS System Monitor" \
        "${SYSMON_BIN}" \
        "${SYSMON_SERVICE}"
    ok "Service unit: ${SYSMON_SERVICE_FILE}"
fi

# ══════════════════════════════════════════════════════════════════════════════
# INSTALL WIFIMON
# ══════════════════════════════════════════════════════════════════════════════
# Delegated to wifimon's own --install (see design note at top of file) —
# it copies itself to /usr/local/bin, writes its own service unit
# (including the Nice/OOMScoreAdjust priorities this script doesn't know
# about), then does enable + restart. Safe unattended: the only
# interactive prompts in wifimon.py are gated on sys.stdin.isatty()
# internally and never reached from install_service().
if [[ -n "${WIFIMON_CHOSEN}" ]]; then
    hdr "Installing wifimon"
    info "Delegating to: python3 $(basename "${WIFIMON_CHOSEN}") --install"
    python3 "${WIFIMON_CHOSEN}" --install \
        || die "wifimon --install failed — see output above"
    ok "wifimon installed, enabled, and restarted"
fi

# ══════════════════════════════════════════════════════════════════════════════
# INSTALL 44HELPER
# ══════════════════════════════════════════════════════════════════════════════
# Same delegation pattern as wifimon — 44helper installs to /opt/44helper
# (not /usr/local/bin), which is another reason to let its own installer
# own that path rather than duplicating it here. Confirmed no input()
# calls anywhere in its --install path, so it's safe unattended.
if [[ -n "${HELPER_CHOSEN}" ]]; then
    hdr "Installing 44helper"
    info "Delegating to: python3 $(basename "${HELPER_CHOSEN}") --install"
    python3 "${HELPER_CHOSEN}" --install \
        || die "44helper --install failed — see output above"
    ok "44helper installed, enabled, and restarted"
fi

# ══════════════════════════════════════════════════════════════════════════════
# INSTALL SVX DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
# Same delegation pattern as wifimon/44helper — svx_dashboard writes its own
# versioned lib dir + symlink + .service (see its install_service()). Own,
# separate config file (not the shared asl_dvs.conf), so no identity to
# seed here. Confirmed no input() calls anywhere in its --install path, so
# it's safe unattended.
if [[ -n "${SVX_CHOSEN}" ]]; then
    hdr "Installing SVX Dashboard"
    info "Delegating to: python3 $(basename "${SVX_CHOSEN}") --install"
    python3 "${SVX_CHOSEN}" --install \
        || die "SVX Dashboard --install failed — see output above"
    ok "SVX Dashboard installed, enabled, and restarted"
fi

# ══════════════════════════════════════════════════════════════════════════════
# ENABLE + START
# ══════════════════════════════════════════════════════════════════════════════
# NOTE: this loop only covers Dashboard and SysMon. The M17/Zello dashboard,
# wifimon and 44helper were already enabled + started
# above by their own --install.
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

# ══════════════════════════════════════════════════════════════════════════════
# STARTUP VERIFICATION
# ══════════════════════════════════════════════════════════════════════════════
hdr "Startup verification"
info "Waiting for services to stabilise…"
sleep 3

# Dashboard + SysMon — check port as well
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

# M17/Zello dashboard (port ${M17DASH_PORT}) + wifimon (no port) + 44helper (port ${HELPER_PORT}) + SVX Dashboard (port ${SVX_PORT})
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

# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
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
# wifimon has no web UI — nothing to print here.

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
