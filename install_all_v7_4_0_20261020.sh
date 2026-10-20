#!/usr/bin/env bash
# install_all.sh  v7.4.0  (2026-10-20)

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
DOWNLOAD=true
for _arg in "$@"; do
    case "${_arg}" in
        --non-interactive|--auto|-y) NONINTERACTIVE=true ;;
        --offline|--no-download) DOWNLOAD=false ;;
    esac
done
if [[ ! -t 0 ]]; then
    NONINTERACTIVE=true
fi

DASH_BIN="/usr/local/bin/nodecontrol.py"
DASH_LEGACY_BIN="/usr/local/bin/asl_dvs_dashboard.py"
dash_service() {
    if [[ ! -f /etc/systemd/system/nodecontrol.service && -f /etc/systemd/system/asl_dvs_dashboard.service ]]; then
        echo "asl_dvs_dashboard"
    else
        echo "nodecontrol"
    fi
}
DASH_SERVICE="$(dash_service)"
if [[ -e "${DASH_LEGACY_BIN}" && ( ! -e "${DASH_BIN}" || "${DASH_SERVICE}" == "asl_dvs_dashboard" ) ]]; then
    DASH_BIN="${DASH_LEGACY_BIN}"
fi
DASH_PORT=8989
DASH_CONF_DIR="/etc/asl_dvs"
DASH_CONF="${DASH_CONF_DIR}/asl_dvs.conf"
LEGACY_CONF="/etc/dvswitch/dvswitch.conf"

SYSMON_BIN="/usr/local/bin/sysmon.py"
SYSMON_SERVICE="sysmon"
SYSMON_PORT=9999
SYSMON_CONF_DIR="/etc/sysmon"

WIFIMON_BIN="/usr/local/bin/wifimon.py"
WIFIMON_SERVICE="wifimon"
WIFIMON_PORT=8991

HELPER_BIN="/usr/local/bin/44helper.py"
HELPER_LEGACY_BIN="/opt/44helper/asl_dvs_m17_44helper.py"
HELPER_SERVICE="44helper"
HELPER_PORT=9997
if [[ ! -e "${HELPER_BIN}" && -e "${HELPER_LEGACY_BIN}" ]]; then
    HELPER_BIN="${HELPER_LEGACY_BIN}"
fi

NODELISTEN_BIN="/usr/local/bin/nodetalker.py"
NODELISTEN_LEGACY_BIN="/usr/local/bin/nodelisten.py"
NODELISTEN_SERVICE="nodetalker"
NODELISTEN_PORT=8993
NODELISTEN_CONF="/etc/asl_dvs/nodetalker.conf"
NODELISTEN_PATTERN="nodetalker*.py|nodelisten*.py"
if [[ ! -e "${NODELISTEN_BIN}" && -e "${NODELISTEN_LEGACY_BIN}" ]]; then
    NODELISTEN_BIN="${NODELISTEN_LEGACY_BIN}"
fi
if [[ ! -e "${NODELISTEN_CONF}" && -e /etc/asl_dvs/nodelisten.conf ]]; then
    NODELISTEN_CONF="/etc/asl_dvs/nodelisten.conf"
fi
INSTALL_NODELISTEN="${INSTALL_NODETALKER:-${INSTALL_NODELISTEN:-}}"

INSTMON_LIBRARY_DIR="${INSTMON_LIBRARY_DIR:-/etc/asl_dvs/instmon_library}"
DASH_LIB_DIR="${INSTMON_LIBRARY_DIR}/dashboard"
SYSMON_LIB_DIR="${INSTMON_LIBRARY_DIR}/sysmon"
WIFIMON_LIB_DIR="${INSTMON_LIBRARY_DIR}/wifimon"
HELPER_LIB_DIR="${INSTMON_LIBRARY_DIR}/44helper"
NODELISTEN_LIB_DIR="${INSTMON_LIBRARY_DIR}/nodelisten"
INSTMON_LIB_DIR="${INSTMON_LIBRARY_DIR}/instmon"

INSTMON_BIN="/usr/local/bin/instmon.py"
INSTMON_SERVICE="instmon"
INSTMON_PORT=8990

GH_REPO="${ASL_DVS_REPO:-kd8pgk/ASL-DVS}"
GH_CHANNEL="${ASL_DVS_CHANNEL:-stable}"
case "${GH_CHANNEL,,}" in
    stable) GH_CHANNEL="stable" ;;
    testing|main) GH_CHANNEL="testing" ;;
    *) echo "ASL_DVS_CHANNEL must be stable or testing (got '${GH_CHANNEL}')" >&2; exit 1 ;;
esac
FETCH_DIR=""
FETCH_REPO=""
FETCH_STATE=""
DOWNLOADED=()
cleanup_fetch() {
    [[ -n "${FETCH_DIR}" && -d "${FETCH_DIR}" ]] && rm -rf -- "${FETCH_DIR}"
    return 0
}
trap cleanup_fetch EXIT

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

    local -a _pats=() _excl=() _find_expr=()
    IFS='|' read -r -a _pats <<< "${pattern}"
    [[ -n "${exclude}" ]] && IFS='|' read -r -a _excl <<< "${exclude}"
    for p in "${_pats[@]}"; do
        [[ ${#_find_expr[@]} -gt 0 ]] && _find_expr+=(-o)
        _find_expr+=(-name "${p}")
    done
    _find_expr=( \( "${_find_expr[@]}" \) )
    for p in "${_excl[@]}"; do
        _find_expr+=(! -name "${p}")
    done

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
        done < <(find "${dir}" -maxdepth 1 "${_find_expr[@]}" -print0 2>/dev/null)
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

any_file() {
    local pattern="$1" lib_dir="${2:-}" exclude="${3:-}" skip_tmp="${4:-false}" d script_dir p
    local -a _pats=() _excl=() _expr=()
    IFS='|' read -r -a _pats <<< "${pattern}"
    [[ -n "${exclude}" ]] && IFS='|' read -r -a _excl <<< "${exclude}"
    for p in "${_pats[@]}"; do
        [[ ${#_expr[@]} -gt 0 ]] && _expr+=(-o)
        _expr+=(-name "${p}")
    done
    _expr=( \( "${_expr[@]}" \) )
    for p in "${_excl[@]}"; do
        _expr+=(! -name "${p}")
    done
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    for d in "${script_dir}" "$(pwd)" "/root" "/home/pi" "/home/${SUDO_USER:-pi}" "/tmp" ${lib_dir:+"${lib_dir}"}; do
        [[ -d "${d}" ]] || continue
        [[ "${skip_tmp}" == "true" && "${d}" == "/tmp" ]] && continue
        [[ -n "$(find "${d}" -maxdepth 1 "${_expr[@]}" -print -quit 2>/dev/null)" ]] && return 0
    done
    return 1
}

name_matches() {
    local name="$1" pattern="$2" exclude="${3:-}" p
    local -a _pats=() _excl=()
    IFS='|' read -r -a _pats <<< "${pattern}"
    [[ -n "${exclude}" ]] && IFS='|' read -r -a _excl <<< "${exclude}"
    for p in "${_excl[@]}"; do
        [[ "${name}" == ${p} ]] && return 1
    done
    for p in "${_pats[@]}"; do
        [[ "${name}" == ${p} ]] && return 0
    done
    return 1
}

ensure_git() {
    command -v git &>/dev/null && return 0
    info "git is not installed — installing it to download from GitHub…"
    if ! command -v apt-get &>/dev/null; then
        warn "apt-get not found — install git by hand, or copy the files onto the Pi"
        return 1
    fi
    if apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git; then
        ok "git installed: $(git --version 2>&1)"
        return 0
    fi
    warn "Could not install git (no network?)"
    return 1
}

open_repo() {
    [[ "${FETCH_STATE}" == "ok" ]] && return 0
    [[ "${FETCH_STATE}" == "failed" ]] && return 1
    FETCH_STATE="failed"
    ensure_git || return 1
    FETCH_DIR="$(mktemp -d /tmp/asl_dvs_fetch.XXXXXX)" || return 1
    FETCH_REPO="${FETCH_DIR}/repo"
    info "Connecting to github.com/${GH_REPO} (${GH_CHANNEL} channel)…"
    if ! GIT_TERMINAL_PROMPT=0 git clone -q --depth 1 --filter=blob:none --no-checkout \
            "https://github.com/${GH_REPO}.git" "${FETCH_REPO}" 2>/dev/null; then
        warn "Could not reach github.com/${GH_REPO} — no files downloaded"
        return 1
    fi
    FETCH_STATE="ok"
    ok "Connected to github.com/${GH_REPO}"
    return 0
}

stable_entry() {
    GIT_TERMINAL_PROMPT=0 git -C "${FETCH_REPO}" show HEAD:channels/stable.json 2>/dev/null \
        | python3 -I -c 'import json,re,sys
try:
    t=(json.load(sys.stdin).get("tools") or {}).get(sys.argv[1]) or {}
except Exception:
    t={}
f,c,b=str(t.get("file","")),str(t.get("commit","")),str(t.get("blob",""))
h=re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")
print(f"{f} {c} {b}" if re.fullmatch(r"[A-Za-z0-9._-]+",f) and not f.startswith("-") and h.fullmatch(c) and h.fullmatch(b) else "")' "$1"
}

fetch_tool() {
    local key="$1" label="$2" pattern="$3" exclude="$4" lib_dir="$5" build="${6:-}"
    local file="" commit="" blob="" rev="HEAD" src="main" entry name tmp
    FETCHED_FILE=""
    open_repo || return 1
    if [[ "${GH_CHANNEL}" == "stable" ]]; then
        entry="$(stable_entry "${key}" || true)"
        if [[ -n "${entry}" ]]; then
            read -r file commit blob <<< "${entry}"
            if ! name_matches "${file}" "${pattern}" "${exclude}"; then
                warn "${label}: the stable list names ${file}, which is not a ${label} file — not downloaded"
                return 1
            elif ! GIT_TERMINAL_PROMPT=0 git -C "${FETCH_REPO}" fetch -q --depth 1 --filter=blob:none origin "${commit}" 2>/dev/null; then
                warn "${label}: could not fetch the stable build (${file}) — not downloaded"
                return 1
            elif [[ "$(git -C "${FETCH_REPO}" rev-parse "${commit}:${file}" 2>/dev/null)" != "${blob}" ]]; then
                warn "${label}: ${file} does not match the stable list — not downloaded"
                return 1
            fi
            rev="${commit}"
            src="stable"
        else
            info "${label} has no stable build yet — using the newest file on main"
        fi
    fi
    if [[ -z "${file}" ]]; then
        rev="HEAD"
        src="main"
        blob=""
        while IFS= read -r name; do
            [[ "${name}" == */* ]] && continue
            name_matches "${name}" "${pattern}" "${exclude}" && file="${name}"
        done < <(git -C "${FETCH_REPO}" ls-tree --name-only HEAD 2>/dev/null | sort -V)
        if [[ -z "${file}" ]]; then
            warn "${label}: no matching file on GitHub"
            return 1
        fi
    fi
    mkdir -p "${lib_dir}" || return 1
    tmp="$(mktemp "${FETCH_DIR}/dl.XXXXXX")"
    if ! GIT_TERMINAL_PROMPT=0 git -C "${FETCH_REPO}" show "${rev}:${file}" > "${tmp}" 2>/dev/null || [[ ! -s "${tmp}" ]]; then
        warn "${label}: download of ${file} failed"
        rm -f -- "${tmp}"
        return 1
    fi
    if [[ -n "${blob}" && "$(git hash-object "${tmp}")" != "${blob}" ]]; then
        warn "${label}: ${file} does not match the stable list — not used"
        rm -f -- "${tmp}"
        return 1
    fi
    if [[ "${file}" == *.py ]] && ! python3 -I -c 'import sys; compile(open(sys.argv[1],"rb").read(), sys.argv[1], "exec")' "${tmp}" 2>/dev/null; then
        warn "${label}: ${file} failed the syntax check — not used"
        rm -f -- "${tmp}"
        return 1
    fi
    if [[ -n "${build}" ]]; then
        if grep -qE '^VERSION[[:space:]]*=[[:space:]]*"[^"]*-pi02w"' "${tmp}"; then
            [[ "${build}" == "pi02w" ]] || { warn "${label}: ${file} is a Pi Zero 2 W build — not used"; rm -f -- "${tmp}"; return 1; }
        else
            [[ "${build}" == "full" ]] || { warn "${label}: ${file} is not a Pi Zero 2 W build — not used"; rm -f -- "${tmp}"; return 1; }
        fi
    fi
    chmod 644 "${tmp}"
    mv -f -- "${tmp}" "${lib_dir}/${file}" || { rm -f -- "${tmp}"; return 1; }
    FETCHED_FILE="${lib_dir}/${file}"
    DOWNLOADED+=("${file} (${src})")
    ok "Downloaded ${file} (${src}) → ${lib_dir}/"
    return 0
}

file_version() {
    [[ -f "$1" ]] || return 0
    sed -n -E 's/^[[:space:]]*(VERSION|APP_VERSION|SCRIPT_VERSION)[[:space:]]*=[[:space:]]*"([^"]+)".*/\2/p' "$1" 2>/dev/null | head -1 || true
}

version_older() {
    python3 -I -c 'import re,sys
def k(v):
    v=re.sub(r"-pi02w$","",v.strip())
    return tuple(int(x) for x in re.findall(r"\d+",v))
a,b=k(sys.argv[1]),k(sys.argv[2])
sys.exit(0 if a and b and a<b else 1)' "$1" "$2"
}

FETCHED_FILE=""
fetch_if_missing() {
    local key="$1" label="$2" installed="$3" pattern="$4" exclude="$5" lib_dir="$6" build="${7:-}" installed_bin="${8:-}" ans new_ver old_ver
    any_file "${pattern}" "${lib_dir}" "${exclude}" true && return 0
    if [[ "${DOWNLOAD}" != "true" ]]; then
        info "No ${label} file found — offline, nothing downloaded"
        return 0
    fi
    if [[ "${installed}" == "true" ]]; then
        if [[ "${NONINTERACTIVE}" == "true" ]]; then
            info "No ${label} file found — installed copy left as it is"
            return 0
        fi
        read -r -p "  No ${label} file found. Download the ${GH_CHANNEL} build from GitHub and update ${label}? [y/N]: " ans </dev/tty
        case "${ans,,}" in
            y|yes) ;;
            *) info "${label} left as it is"; return 0 ;;
        esac
    else
        info "No ${label} file found — downloading it from GitHub"
    fi
    fetch_tool "${key}" "${label}" "${pattern}" "${exclude}" "${lib_dir}" "${build}" || true
    if [[ "${installed}" == "true" && -n "${FETCHED_FILE}" && -n "${installed_bin}" ]]; then
        new_ver="$(file_version "${FETCHED_FILE}")"
        old_ver="$(file_version "${installed_bin}")"
        if [[ -n "${new_ver}" && -n "${old_ver}" ]] && version_older "${new_ver}" "${old_ver}"; then
            warn "${label}: the ${GH_CHANNEL} build (${new_ver}) is older than the installed ${old_ver}"
            read -r -p "  Install the older version? [y/N]: " ans </dev/tty
            case "${ans,,}" in
                y|yes) ok "Proceeding with the older version" ;;
                *)
                    rm -f -- "${FETCHED_FILE}"
                    DOWNLOADED=("${DOWNLOADED[@]:0:${#DOWNLOADED[@]}-1}")
                    info "${label} left at ${old_ver}"
                    ;;
            esac
        fi
    fi
    return 0
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
    die "Must be run as root.  Use: sudo bash install_all.sh"
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
_sysmon_exists=false
_wifimon_exists=false
_helper_exists=false
_nodelisten_exists=false
systemctl is-active --quiet nodecontrol          2>/dev/null && _dash_exists=true    || true
systemctl is-active --quiet asl_dvs_dashboard    2>/dev/null && _dash_exists=true    || true
systemctl is-active --quiet "${SYSMON_SERVICE}"  2>/dev/null && _sysmon_exists=true  || true
systemctl is-active --quiet "${WIFIMON_SERVICE}" 2>/dev/null && _wifimon_exists=true || true
systemctl is-active --quiet "${HELPER_SERVICE}"  2>/dev/null && _helper_exists=true  || true
systemctl is-active --quiet nodetalker           2>/dev/null && _nodelisten_exists=true || true
systemctl is-active --quiet nodelisten           2>/dev/null && _nodelisten_exists=true || true
[[ -f "${DASH_BIN}"     ]] && _dash_exists=true
[[ -f "${SYSMON_BIN}"   ]] && _sysmon_exists=true
[[ -f "${WIFIMON_BIN}"  ]] && _wifimon_exists=true
[[ -f "${HELPER_BIN}"   ]] && _helper_exists=true
[[ -f "${NODELISTEN_BIN}" ]] && _nodelisten_exists=true

if [[ "${_dash_exists}" == "true" || "${_sysmon_exists}" == "true" \
      || "${_wifimon_exists}" == "true" || "${_helper_exists}" == "true" \
      || "${_nodelisten_exists}" == "true" ]]; then
    echo
    echo "  ${BLD}Existing installation detected:${RST}"
    [[ "${_dash_exists}"     == "true" ]] && echo "  ${GRN}  ✔${RST}  Dashboard      (${DASH_BIN})"
    [[ "${_sysmon_exists}"   == "true" ]] && echo "  ${GRN}  ✔${RST}  SysMon         (${SYSMON_BIN})"
    [[ "${_wifimon_exists}"  == "true" ]] && echo "  ${GRN}  ✔${RST}  wifimon        (${WIFIMON_BIN})"
    [[ "${_helper_exists}"   == "true" ]] && echo "  ${GRN}  ✔${RST}  44helper       (${HELPER_BIN})"
    [[ "${_nodelisten_exists}" == "true" ]] && echo "  ${GRN}  ✔${RST}  Node Talker    (${NODELISTEN_BIN})"
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

INSTMON_CHOSEN=""
if [[ ! -f "${INSTMON_BIN}" ]]; then
    hdr "instmon — file discovery"
    info "instmon is not installed — it will be installed too"
    CHOSEN=""
    fetch_if_missing "instmon" "instmon" false "instmon*.py" "" "${INSTMON_LIB_DIR}"
    stage_and_select "instmon*.py" "instmon" "${INSTMON_LIB_DIR}" || true
    INSTMON_CHOSEN="${CHOSEN}"
    if [[ -n "${INSTMON_CHOSEN}" ]]; then
        info "Checking syntax…"
        python3 -m py_compile "${INSTMON_CHOSEN}" \
            || die "Syntax error in $(basename "${INSTMON_CHOSEN}") — install aborted"
        ok "Syntax OK"
    fi
fi

hdr "Dashboard — file discovery"
CHOSEN=""
pick_build "${DASH_VARIANT:-}" "${DASH_BIN}" "DASH_VARIANT"
DASH_VARIANT="${PICKED_BUILD}"
if [[ "${DASH_VARIANT}" == "pi02w" ]]; then
    info "Dashboard build: Pi Zero 2 W (nodecontrol_pi02w*.py), from ${PICKED_WHY}"
    fetch_if_missing "nodecontrol_pi02w" "Dashboard (Pi Zero 2 W)" "${_dash_exists}" "nodecontrol_pi02w*.py|asl_dvs_dashboard_pi02w*.py" "" "${DASH_LIB_DIR}" pi02w "${DASH_BIN}"
    stage_and_select "nodecontrol_pi02w*.py|asl_dvs_dashboard_pi02w*.py" "Dashboard (Pi Zero 2 W)" "${DASH_LIB_DIR}" || true
else
    info "Dashboard build: full (nodecontrol*.py without _pi02w), from ${PICKED_WHY}"
    fetch_if_missing "nodecontrol" "Dashboard" "${_dash_exists}" "nodecontrol*.py|asl_dvs_dashboard*.py" "nodecontrol_pi02w*.py|asl_dvs_dashboard_pi02w*.py" "${DASH_LIB_DIR}" full "${DASH_BIN}"
    stage_and_select "nodecontrol*.py|asl_dvs_dashboard*.py" "Dashboard" "${DASH_LIB_DIR}" "nodecontrol_pi02w*.py|asl_dvs_dashboard_pi02w*.py" || true
fi
DASH_CHOSEN="${CHOSEN}"
[[ -z "${DASH_CHOSEN}" ]] && warn "No ${DASH_VARIANT} Dashboard build found -- set DASH_VARIANT=pi02w or =full to choose the other build."

if [[ -n "${DASH_CHOSEN}" ]]; then
    info "Checking syntax…"
    python3 -m py_compile "${DASH_CHOSEN}" \
        || die "Syntax error in $(basename "${DASH_CHOSEN}") — install aborted"
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
    fetch_if_missing "sysmon_pi02w" "SysMon (Pi Zero 2 W)" "${_sysmon_exists}" "sysmon_pi02w*.py" "" "${SYSMON_LIB_DIR}" pi02w "${SYSMON_BIN}"
    stage_and_select "sysmon_pi02w*.py" "SysMon (Pi Zero 2 W)" "${SYSMON_LIB_DIR}" || true
else
    fetch_if_missing "sysmon" "SysMon" "${_sysmon_exists}" "sysmon*.py" "sysmon_pi02w*.py" "${SYSMON_LIB_DIR}" full "${SYSMON_BIN}"
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
fetch_if_missing "wifimon" "wifimon" "${_wifimon_exists}" "wifimon*.py" "" "${WIFIMON_LIB_DIR}" "" "${WIFIMON_BIN}"
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
fetch_if_missing "44helper" "44helper" "${_helper_exists}" "44helper*.py|asl_dvs_m17_44helper*.py" "" "${HELPER_LIB_DIR}" "" "${HELPER_BIN}"
stage_and_select "44helper*.py|asl_dvs_m17_44helper*.py" "44helper" "${HELPER_LIB_DIR}" || true
HELPER_CHOSEN="${CHOSEN}"

if [[ -n "${HELPER_CHOSEN}" ]]; then
    info "Checking syntax…"
    python3 -m py_compile "${HELPER_CHOSEN}" \
        || die "Syntax error in $(basename "${HELPER_CHOSEN}") — install aborted"
    ok "Syntax OK"
fi

hdr "Node Talker — file discovery"
CHOSEN=""
_nl_want=true
if [[ "${_nodelisten_exists}" != "true" ]]; then
    if [[ "${DOWNLOAD}" != "true" ]] && ! any_file "${NODELISTEN_PATTERN}" "${NODELISTEN_LIB_DIR}"; then
        _nl_want=false
        info "No nodetalker*.py file found — Node Talker (optional) skipped"
    elif [[ "${NONINTERACTIVE}" == "true" ]]; then
        if [[ "${INSTALL_NODELISTEN:-}" =~ ^([1yY]|yes|YES|true|TRUE)$ ]]; then
            info "Non-interactive: INSTALL_NODETALKER is set — installing Node Talker"
        else
            _nl_want=false
            info "Node Talker is optional and not installed — skipped (set INSTALL_NODETALKER=1 to install it)"
        fi
    else
        echo "  Node Talker is optional: it plays this node's audio in a web browser (port ${NODELISTEN_PORT})."
        echo "  It changes nothing in Asterisk until you pick a node on its page."
        read -r -p "  Install Node Talker? [y/N]: " _nl_ans </dev/tty
        case "${_nl_ans,,}" in
            y|yes) ;;
            *) _nl_want=false; info "Skipping Node Talker" ;;
        esac
    fi
fi
if [[ "${_nl_want}" == "true" ]]; then
    fetch_if_missing "nodetalker" "Node Talker" "${_nodelisten_exists}" "${NODELISTEN_PATTERN}" "" "${NODELISTEN_LIB_DIR}" "" "${NODELISTEN_BIN}"
    stage_and_select "${NODELISTEN_PATTERN}" "Node Talker" "${NODELISTEN_LIB_DIR}" || true
fi
NODELISTEN_CHOSEN="${CHOSEN}"

if [[ -n "${NODELISTEN_CHOSEN}" ]]; then
    info "Checking syntax…"
    python3 -m py_compile "${NODELISTEN_CHOSEN}" \
        || die "Syntax error in $(basename "${NODELISTEN_CHOSEN}") — install aborted"
    ok "Syntax OK"
fi

if [[ ${#DOWNLOADED[@]} -gt 0 ]]; then
    hdr "Downloaded from GitHub"
    for _d in "${DOWNLOADED[@]}"; do ok "${_d}"; done
fi

if [[ -z "${INSTMON_CHOSEN}" && -z "${DASH_CHOSEN}" && -z "${SYSMON_CHOSEN}" \
      && -z "${WIFIMON_CHOSEN}" && -z "${HELPER_CHOSEN}" && -z "${NODELISTEN_CHOSEN}" ]]; then
    if [[ "${DOWNLOAD}" != "true" ]]; then
        die "Nothing to install — no instmon, dashboard, sysmon, wifimon, 44helper or Node Talker files found (offline: nothing downloaded)."
    elif [[ "${FETCH_STATE}" == "failed" ]]; then
        die "Nothing to install — no files found here, and the download from GitHub failed."
    fi
    die "Nothing to install — no instmon, dashboard, sysmon, wifimon, 44helper or Node Talker files found."
fi

hdr "Up-to-date check"

uptodate_check "Dashboard" "${DASH_CHOSEN}"    "${DASH_BIN}"
[[ "${UP_TO_DATE_SKIP}" == "true" ]] && DASH_CHOSEN=""

uptodate_check "SysMon"    "${SYSMON_CHOSEN}"  "${SYSMON_BIN}"
[[ "${UP_TO_DATE_SKIP}" == "true" ]] && SYSMON_CHOSEN=""

uptodate_check "wifimon"   "${WIFIMON_CHOSEN}" "${WIFIMON_BIN}"
[[ "${UP_TO_DATE_SKIP}" == "true" ]] && WIFIMON_CHOSEN=""

uptodate_check "44helper"  "${HELPER_CHOSEN}"  "${HELPER_BIN}"
[[ "${UP_TO_DATE_SKIP}" == "true" ]] && HELPER_CHOSEN=""

uptodate_check "Node Talker" "${NODELISTEN_CHOSEN}" "${NODELISTEN_BIN}"
[[ "${UP_TO_DATE_SKIP}" == "true" ]] && NODELISTEN_CHOSEN=""

if [[ -z "${INSTMON_CHOSEN}" && -z "${DASH_CHOSEN}" && -z "${SYSMON_CHOSEN}" \
      && -z "${WIFIMON_CHOSEN}" && -z "${HELPER_CHOSEN}" && -z "${NODELISTEN_CHOSEN}" ]]; then
    ok "All selected files are already up to date — nothing to install."
    exit 0
fi

hdr "Port checks"
[[ -n "${INSTMON_CHOSEN}" ]] && { info "instmon port ${INSTMON_PORT}:"; check_port "${INSTMON_PORT}"; }
[[ -n "${DASH_CHOSEN}"    ]] && { info "Dashboard port ${DASH_PORT}:"; check_port "${DASH_PORT}"; }
[[ -n "${SYSMON_CHOSEN}"  ]] && { info "SysMon port ${SYSMON_PORT}:";  check_port "${SYSMON_PORT}"; }
[[ -n "${HELPER_CHOSEN}"  ]] && { info "44helper port ${HELPER_PORT}:"; check_port "${HELPER_PORT}"; }
if [[ -n "${NODELISTEN_CHOSEN}" && "${_nodelisten_exists}" != "true" ]]; then
    _nl_port="$(sed -n 's/^[[:space:]]*port[[:space:]]*=[[:space:]]*\([0-9]\{4,5\}\)[[:space:]]*$/\1/p' "${NODELISTEN_CONF}" 2>/dev/null | head -1 || true)"
    NODELISTEN_PORT="${_nl_port:-${NODELISTEN_PORT}}"
    info "Node Talker port ${NODELISTEN_PORT}:"; check_port "${NODELISTEN_PORT}"
fi

if [[ -n "${INSTMON_CHOSEN}" ]]; then
    hdr "Installing instmon"
    info "Delegating to: python3 $(basename "${INSTMON_CHOSEN}") --install"
    python3 "${INSTMON_CHOSEN}" --install \
        || die "instmon --install failed — see output above"
    ok "instmon installed, enabled, and restarted"
fi

if [[ -n "${DASH_CHOSEN}" ]]; then
    hdr "Installing Dashboard"

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

    if grep -q 'asl_dvs_dashboard\.service' "${DASH_CHOSEN}" && ! grep -q 'nodecontrol\.service' "${DASH_CHOSEN}" \
       && [[ -f /etc/systemd/system/nodecontrol.service ]]; then
        info "Retiring nodecontrol.service: $(basename "${DASH_CHOSEN}") installs the Dashboard under its old name"
        systemctl disable --now nodecontrol.service 2>/dev/null || true
        rm -f /etc/systemd/system/nodecontrol.service /usr/local/bin/nodecontrol.py
        rm -rf /usr/local/lib/asl_dvs/nodecontrol
        systemctl daemon-reload
    fi

    info "Delegating to: python3 $(basename "${DASH_CHOSEN}") --install"
    python3 "${DASH_CHOSEN}" --install \
        || die "Dashboard --install failed — see output above"
    DASH_SERVICE="$(dash_service)"
    ok "Dashboard installed, enabled, and restarted (${DASH_SERVICE}.service)"
fi

if [[ -n "${SYSMON_CHOSEN}" ]]; then
    hdr "Installing SysMon"

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

    info "Delegating to: python3 $(basename "${SYSMON_CHOSEN}") --install"
    python3 "${SYSMON_CHOSEN}" --install \
        || die "SysMon --install failed — see output above"
    ok "SysMon installed, enabled, and restarted"
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

if [[ -n "${NODELISTEN_CHOSEN}" ]]; then
    hdr "Installing Node Talker"
    if [[ "$(basename "${NODELISTEN_CHOSEN}")" == nodelisten* ]]; then
        NODELISTEN_SERVICE="nodelisten"
        if [[ -f /etc/systemd/system/nodetalker.service && -e /usr/local/bin/nodetalker.py ]]; then
            warn "$(basename "${NODELISTEN_CHOSEN}") is Node Listen, the older name: uninstalling Node Talker first so the two don't both run"
            python3 /usr/local/bin/nodetalker.py --uninstall \
                || die "Node Talker --uninstall failed — see output above"
        fi
    fi
    info "Delegating to: python3 $(basename "${NODELISTEN_CHOSEN}") --install"
    python3 "${NODELISTEN_CHOSEN}" --install \
        || die "Node Talker --install failed — see output above"
    ok "Node Talker installed, enabled, and restarted"
    for _nl_c in /etc/asl_dvs/nodetalker.conf /etc/asl_dvs/nodelisten.conf; do
        [[ -e "${_nl_c}" ]] && { NODELISTEN_CONF="${_nl_c}"; break; }
    done
    _nl_port="$(sed -n 's/^[[:space:]]*port[[:space:]]*=[[:space:]]*\([0-9]\{4,5\}\)[[:space:]]*$/\1/p' "${NODELISTEN_CONF}" 2>/dev/null | head -1 || true)"
    NODELISTEN_PORT="${_nl_port:-${NODELISTEN_PORT}}"
fi

hdr "Startup verification"
info "Waiting for services to stabilise…"
sleep 3

for svc_entry in \
    "${INSTMON_SERVICE}:${INSTMON_CHOSEN}:${INSTMON_PORT}" \
    "${DASH_SERVICE}:${DASH_CHOSEN}:${DASH_PORT}" \
    "${SYSMON_SERVICE}:${SYSMON_CHOSEN}:${SYSMON_PORT}" \
    "${WIFIMON_SERVICE}:${WIFIMON_CHOSEN}:${WIFIMON_PORT}" \
    "${HELPER_SERVICE}:${HELPER_CHOSEN}:${HELPER_PORT}" \
    "${NODELISTEN_SERVICE}:${NODELISTEN_CHOSEN}:${NODELISTEN_PORT}"; do
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

print_urls "instmon"                             "${INSTMON_PORT}" "${INSTMON_CHOSEN}"
print_urls "ASL-DVS Node Control Dashboard"      "${DASH_PORT}"    "${DASH_CHOSEN}"
print_urls "ASL-DVS System Monitor"              "${SYSMON_PORT}"  "${SYSMON_CHOSEN}"
print_urls "44Net Helper"                        "${HELPER_PORT}"  "${HELPER_CHOSEN}"
print_urls "wifimon"                             "${WIFIMON_PORT}" "${WIFIMON_CHOSEN}"
print_urls "Node Talker"                         "${NODELISTEN_PORT}" "${NODELISTEN_CHOSEN}"

if [[ -n "${WIFIMON_CHOSEN}" ]]; then
    info "To add/import WiFi networks: sudo python3 ${WIFIMON_BIN} --setup-wifi"
fi

echo
echo "  ${BLD}Service commands:${RST}"
[[ -n "${INSTMON_CHOSEN}"  ]] && echo "    instmon        :  systemctl {status|restart|stop} ${INSTMON_SERVICE}"
[[ -n "${DASH_CHOSEN}"     ]] && echo "    Dashboard      :  systemctl {status|restart|stop} ${DASH_SERVICE}"
[[ -n "${SYSMON_CHOSEN}"   ]] && echo "    SysMon         :  systemctl {status|restart|stop} ${SYSMON_SERVICE}"
[[ -n "${WIFIMON_CHOSEN}"  ]] && echo "    wifimon        :  systemctl {status|restart|stop} ${WIFIMON_SERVICE}"
[[ -n "${HELPER_CHOSEN}"   ]] && echo "    44helper       :  systemctl {status|restart|stop} ${HELPER_SERVICE}"
[[ -n "${NODELISTEN_CHOSEN}" ]] && echo "    Node Talker    :  systemctl {status|restart|stop} ${NODELISTEN_SERVICE}"
echo "    Logs      :  journalctl -u <service> -f"
echo
