#!/usr/bin/env bash
# install_all.sh  v7.7.0  (2026-11-14)

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
SUITE=false
DOWNLOAD_ONLY=false
STRICT_STABLE=false
CORE=false
AUTO_PICK=false
GIT_DECLINED=false
APT_UPDATED=false
ACTION=""
TOOLS_LIST=""
BUILD_ARG=""
STEPS_ARG=""
RESET_ARG=""
RESET_ONLY=false
MANUALS=true
for _arg in "$@"; do
    case "${_arg}" in
        --non-interactive|--auto|-y) NONINTERACTIVE=true ;;
        --offline|--no-download) DOWNLOAD=false ;;
        --suite) SUITE=true ;;
        --core) CORE=true ;;
        --with-termon) INSTALL_TERMON=1 ;;
        --download-only) DOWNLOAD_ONLY=true ;;
        --action=*) ACTION="${_arg#*=}" ;;
        --tools=*) TOOLS_LIST="${_arg#*=}" ;;
        --build=*) BUILD_ARG="${_arg#*=}" ;;
        --steps=*) STEPS_ARG="${_arg#*=}" ;;
        --reset) RESET_ARG="on" ;;
        --no-reset) RESET_ARG="off" ;;
        --reset-only) RESET_ONLY=true ;;
        --no-manuals) MANUALS=false ;;
    esac
done
if [[ ! -t 0 ]]; then
    NONINTERACTIVE=true
fi
ACTION="${ACTION,,}"
case "${ACTION}" in
    ""|first|upgrade|replace|components) ;;
    reset) RESET_ONLY=true; ACTION="" ;;
    *) echo "--action must be first, upgrade, replace or components (got '${ACTION}')" >&2; exit 1 ;;
esac
TOOLS_LIST="${TOOLS_LIST,,}"
TOOLS_LIST="${TOOLS_LIST// /}"
if [[ -n "${TOOLS_LIST}" ]]; then
    for _t in ${TOOLS_LIST//,/ }; do
        case "${_t}" in
            instmon|dashboard|sysmon|wifimon|44helper|manuals|none) ;;
            nodetalker) INSTALL_NODETALKER=1 ;;
            noderecorder) INSTALL_NODERECORDER=1 ;;
            pibrary) INSTALL_PIBRARY=1 ;;
            termon) INSTALL_TERMON=1 ;;
            *) echo "--tools: unknown item '${_t}' (use instmon, dashboard, sysmon, wifimon, 44helper, nodetalker, noderecorder, pibrary, termon, manuals)" >&2; exit 1 ;;
        esac
    done
    [[ -z "${ACTION}" ]] && ACTION="components"
    if [[ "${ACTION}" != "components" ]]; then
        echo "--tools goes with --action=components" >&2
        exit 1
    fi
fi
BUILD_ARG="${BUILD_ARG,,}"
case "${BUILD_ARG}" in
    "") ;;
    pi02w|full)
        DASH_VARIANT="${DASH_VARIANT:-${BUILD_ARG}}"
        SYSMON_VARIANT="${SYSMON_VARIANT:-${BUILD_ARG}}"
        ;;
    *) echo "--build must be pi02w or full (got '${BUILD_ARG}')" >&2; exit 1 ;;
esac
STEPS_ARG="${STEPS_ARG^^}"
STEPS_ARG="${STEPS_ARG//[^A-F]/}"
if [[ "${RESET_ONLY}" == "true" && "${DOWNLOAD_ONLY}" == "true" ]]; then
    echo "--reset-only and --download-only cannot be used together" >&2
    exit 1
fi
if [[ -n "${STEPS_ARG}" && -z "${ACTION}" && "${NONINTERACTIVE}" == "true" ]]; then
    echo "--steps needs --action (first, upgrade, replace or components)" >&2
    exit 1
fi
ASL_DVS_ETC="${ASL_DVS_ETC:-/etc/asl_dvs}"
RUN_DIR="${ASL_DVS_RUN_DIR:-/run}"
MODEL_FILE="${ASL_DVS_MODEL_FILE:-/proc/device-tree/model}"
START_WAIT="${ASL_DVS_START_WAIT:-20}"
HEAVY_PAUSE="${ASL_DVS_HEAVY_PAUSE:-3}"

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
DASH_CONF_DIR="${ASL_DVS_ETC}"
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
NODELISTEN_CONF="${ASL_DVS_ETC}/nodetalker.conf"
NODELISTEN_PATTERN="nodetalker*.py|nodelisten*.py"
if [[ ! -e "${NODELISTEN_BIN}" && -e "${NODELISTEN_LEGACY_BIN}" ]]; then
    NODELISTEN_BIN="${NODELISTEN_LEGACY_BIN}"
fi
if [[ ! -e "${NODELISTEN_CONF}" && -e "${ASL_DVS_ETC}/nodelisten.conf" ]]; then
    NODELISTEN_CONF="${ASL_DVS_ETC}/nodelisten.conf"
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
    if [[ "${AUTO_PICK}" == "true" ]]; then
        CHOSEN="${SORTED[0]}"
        ok "Full install: newest ${label} — $(basename "${CHOSEN}")"
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

apt_install() {
    if ! command -v apt-get &>/dev/null; then
        return 1
    fi
    if [[ "${APT_UPDATED}" != "true" ]]; then
        apt-get update -qq || return 1
        APT_UPDATED=true
    fi
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@"
}

ensure_git() {
    local ans
    command -v git &>/dev/null && return 0
    if [[ "${GIT_DECLINED}" == "true" ]]; then
        return 1
    fi
    if ! command -v apt-get &>/dev/null; then
        warn "apt-get not found — install git by hand, or copy the files onto the Pi"
        return 1
    fi
    if [[ "${NONINTERACTIVE}" == "true" ]]; then
        info "git is not installed — installing it to download from GitHub…"
    else
        read -r -p "  git is needed to download from GitHub and is not installed. Install it with apt? [Y/n]: " ans </dev/tty
        case "${ans,,}" in
            n|no)
                GIT_DECLINED=true
                info "git not installed — only the files on this Pi are used"
                return 1
                ;;
        esac
    fi
    if apt_install git && command -v git &>/dev/null; then
        ok "git installed: $(git --version 2>&1)"
        return 0
    fi
    warn "Could not install git (no network?)"
    return 1
}

check_prereqs() {
    local rows=() row cmd pkg why ans
    local missing=() pkgs=()
    if [[ "${DOWNLOAD}" == "true" ]]; then
        rows+=("git|git|downloads from GitHub")
    fi
    if [[ "${DOWNLOAD_ONLY}" != "true" ]]; then
        rows+=("ss|iproute2|the port checks")
        rows+=("openssl|openssl|the HTTPS pages of Node Talker, Node Recorder and Terminal Monitor")
    fi
    for row in "${rows[@]}"; do
        IFS='|' read -r cmd pkg why <<< "${row}"
        if command -v "${cmd}" &>/dev/null; then
            continue
        fi
        if [[ "${NONINTERACTIVE}" == "true" ]]; then
            if [[ "${cmd}" != "git" ]]; then
                warn "${cmd} is not installed (needed for ${why}) — install it with: apt install ${pkg}"
            fi
            continue
        fi
        missing+=("${cmd} — needed for ${why}")
        pkgs+=("${pkg}")
    done
    if [[ ${#pkgs[@]} -eq 0 ]]; then
        if [[ "${NONINTERACTIVE}" != "true" ]]; then
            ok "Needed programs are installed"
        fi
        return 0
    fi
    echo
    echo "  ${BLD}Not installed on this Pi:${RST}"
    for row in "${missing[@]}"; do
        echo "    ${row}"
    done
    echo
    if ! command -v apt-get &>/dev/null; then
        warn "apt-get not found — install by hand: ${pkgs[*]}"
        return 0
    fi
    read -r -p "  Install ${pkgs[*]} with apt? [Y/n]: " ans </dev/tty
    case "${ans,,}" in
        n|no)
            for pkg in "${pkgs[@]}"; do
                if [[ "${pkg}" == "git" ]]; then
                    GIT_DECLINED=true
                fi
            done
            warn "Not installed: ${pkgs[*]} — carrying on without"
            return 0
            ;;
    esac
    if apt_install "${pkgs[@]}"; then
        ok "Installed: ${pkgs[*]}"
    else
        warn "Could not install ${pkgs[*]} (no network?) — carrying on without"
    fi
    return 0
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
            "${ASL_DVS_GIT_URL:-https://github.com/${GH_REPO}.git}" "${FETCH_REPO}" 2>/dev/null; then
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
        elif [[ "${STRICT_STABLE}" == "true" ]]; then
            warn "${label} has no stable build yet — not downloaded (ASL_DVS_CHANNEL=testing fetches the newest)"
            return 1
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

syntax_ok() {
    python3 -I -c 'import sys; compile(open(sys.argv[1],"rb").read(), sys.argv[1], "exec")' "$1"
}

is_zero2() {
    tr -d '\0' 2>/dev/null < "${MODEL_FILE}" | grep -qi 'Zero 2'
}

bin_build() {
    [[ -f "$1" ]] || return 0
    if grep -qE '^VERSION[[:space:]]*=[[:space:]]*"[^"]*-pi02w"' "$1" 2>/dev/null; then
        echo "pi02w"
    else
        echo "full"
    fi
}

FORCE_FETCH=false
ACTION_LABEL=""
FETCHED_FILE=""
fetch_if_missing() {
    local key="$1" label="$2" installed="$3" pattern="$4" exclude="$5" lib_dir="$6" build="${7:-}" installed_bin="${8:-}" ans new_ver old_ver
    if [[ "${FORCE_FETCH}" == "true" && "${DOWNLOAD}" == "true" ]]; then
        info "${ACTION_LABEL}: getting the ${GH_CHANNEL} build of ${label} from GitHub"
        fetch_tool "${key}" "${label}" "${pattern}" "${exclude}" "${lib_dir}" "${build}" || true
        return 0
    fi
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
        if is_zero2; then
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

REINSTALL=false
NO_DOWNGRADE=false
downgrade_check() {
    local label="$1" chosen="$2" installed_bin="$3" new_ver old_ver
    UP_TO_DATE_SKIP=false
    [[ "${NO_DOWNGRADE}" == "true" && -n "${chosen}" && -f "${installed_bin}" ]] || return 0
    new_ver="$(file_version "${chosen}")"
    old_ver="$(file_version "${installed_bin}")"
    if [[ -n "${new_ver}" && -n "${old_ver}" ]] && version_older "${new_ver}" "${old_ver}"; then
        warn "${label}: $(basename "${chosen}") (${new_ver}) is older than the installed ${old_ver} — skipped, never downgraded"
        UP_TO_DATE_SKIP=true
    fi
    return 0
}

UP_TO_DATE_SKIP=false
uptodate_check() {
    local label="$1" chosen="$2" installed_bin="$3"
    UP_TO_DATE_SKIP=false
    [[ -z "${chosen}" || ! -f "${installed_bin}" ]] && return
    if cmp -s "${chosen}" "${installed_bin}"; then
        warn "${label} — selected file is identical to the installed version"
        if [[ "${REINSTALL}" == "true" ]]; then
            info "Full replace: reinstalling ${label} anyway"
            return
        fi
        if [[ "${NONINTERACTIVE}" == "true" || "${ACTION}" == "upgrade" ]]; then
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

USER_STOPPED_FILE="${ASL_DVS_USER_STOPPED:-${ASL_DVS_ETC}/instmon_user_stopped.json}"
QUIET_STATE_FILE="${ASL_DVS_QUIET_STATE:-${ASL_DVS_ETC}/instmon_quiesce_state.json}"
declare -A HELD=()

svc_active() {
    [[ "$(systemctl is-active "$1" 2>/dev/null || true)" == "active" ]]
}

json_has_service() {
    if [[ ! -f "$1" ]]; then
        return 1
    fi
    python3 -I -c 'import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
svc = sys.argv[2]
table = data.get("services") if isinstance(data, dict) else None
if isinstance(table, dict):
    sys.exit(0 if svc in table else 1)
rows = data.get("stopped") if isinstance(data, dict) else None
if isinstance(rows, list):
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) > 2 and row[2] in (svc, svc + ".service"):
            sys.exit(0)
sys.exit(1)' "$1" "$2"
}

declare -A RS_WAS_ACTIVE=()
user_stopped() {
    local svc="$1"
    if svc_active "${svc}" || [[ -n "${RS_WAS_ACTIVE[${svc}]+x}" ]]; then
        return 1
    fi
    if json_has_service "${USER_STOPPED_FILE}" "${svc}"; then
        return 0
    fi
    if json_has_service "${QUIET_STATE_FILE}" "${svc}"; then
        return 1
    fi
    [[ "$(systemctl is-enabled "${svc}" 2>/dev/null || true)" == "disabled" ]]
}

hold_begin() {
    local svc="$1" exists="$2"
    if [[ "${exists}" != "true" ]]; then
        return 0
    fi
    if user_stopped "${svc}"; then
        HELD["${svc}"]="enabled"
        if [[ "$(systemctl is-enabled "${svc}" 2>/dev/null || true)" == "disabled" ]]; then
            HELD["${svc}"]="disabled"
        fi
        info "${svc} was stopped by you — it will be left stopped after the install"
    fi
    return 0
}

hold_end() {
    local svc="$1" label="$2" other="${3:-}" s
    if [[ -z "${HELD[${svc}]+x}" ]]; then
        return 0
    fi
    for s in "${svc}" "${other}"; do
        if [[ -z "${s}" ]]; then
            continue
        fi
        systemctl stop "${s}" 2>/dev/null || true
        if [[ "${HELD[${svc}]}" == "disabled" ]]; then
            systemctl disable "${s}" 2>/dev/null || true
        fi
    done
    ok "${label} installed and left stopped, as you had it"
    return 0
}

OPT_KEYS=(noderecorder pibrary termon)
declare -A OPT_LABEL=([noderecorder]="Node Recorder" [pibrary]="Pibrary" [termon]="Terminal Monitor")
declare -A OPT_BIN=([noderecorder]="/usr/local/bin/noderecorder.py" [pibrary]="/usr/local/bin/pibrary.py" [termon]="/usr/local/bin/termon.py")
declare -A OPT_SERVICE=([noderecorder]="noderecorder" [pibrary]="pibrary" [termon]="termon")
declare -A OPT_PORT=([noderecorder]=8995 [pibrary]=9000 [termon]=7878)
declare -A OPT_SCHEME=([noderecorder]="https" [pibrary]="http" [termon]="https")
declare -A OPT_PATTERN=([noderecorder]="noderecorder*.py" [pibrary]="pibrary*.py" [termon]="termon*.py")
declare -A OPT_LIB=([noderecorder]="${INSTMON_LIBRARY_DIR}/noderecorder" [pibrary]="${INSTMON_LIBRARY_DIR}/pibrary" [termon]="${INSTMON_LIBRARY_DIR}/termon")
declare -A OPT_ASK=(
    [noderecorder]="Node Recorder is optional: it records this node's audio on a schedule (port 8995)."
    [pibrary]="Pibrary is optional: a media library for a USB or SD drive (port 9000)."
    [termon]="Terminal Monitor is optional: top, htop or btop and a shell in the browser (port 7878). It gives a root shell to anyone on your LAN who knows the password."
)
declare -A OPT_EXISTS=() OPT_CHOSEN=()

opt_is_installed() {
    local key="$1"
    if [[ -f "${OPT_BIN[${key}]}" ]]; then
        return 0
    fi
    svc_active "${OPT_SERVICE[${key}]}"
}

opt_wanted() {
    local key="$1" var="INSTALL_${1^^}"
    if [[ "${!var:-}" =~ ^([1yY]|yes|YES|true|TRUE)$ ]]; then
        return 0
    fi
    if [[ "${SUITE}" == "true" && "${key}" != "termon" ]]; then
        return 0
    fi
    return 1
}

opt_any_chosen() {
    local k
    for k in "${OPT_KEYS[@]}"; do
        if [[ -n "${OPT_CHOSEN[${k}]:-}" ]]; then
            return 0
        fi
    done
    return 1
}

discover_optional() {
    local key="$1" label exists=false want=true ans
    label="${OPT_LABEL[${key}]}"
    if opt_is_installed "${key}"; then
        exists=true
    fi
    OPT_EXISTS["${key}"]="${exists}"
    hdr "${label} — file discovery"
    CHOSEN=""
    if [[ "${exists}" != "true" ]]; then
        if opt_wanted "${key}"; then
            info "${label} was asked for (INSTALL_${key^^}=1, --suite or --with-termon)"
        elif [[ "${DOWNLOAD}" != "true" ]] && ! any_file "${OPT_PATTERN[${key}]}" "${OPT_LIB[${key}]}"; then
            want=false
            info "No ${OPT_PATTERN[${key}]} file found — ${label} (optional) skipped"
        elif [[ "${NONINTERACTIVE}" == "true" ]]; then
            want=false
            info "${label} is optional and not installed — skipped (set INSTALL_${key^^}=1 to install it)"
        else
            echo "  ${OPT_ASK[${key}]}"
            read -r -p "  Install ${label}? [y/N]: " ans </dev/tty
            case "${ans,,}" in
                y|yes) ;;
                *) want=false; info "Skipping ${label}" ;;
            esac
        fi
    fi
    if [[ "${want}" == "true" ]]; then
        STRICT_STABLE=true
        fetch_if_missing "${key}" "${label}" "${exists}" "${OPT_PATTERN[${key}]}" "" "${OPT_LIB[${key}]}" "" "${OPT_BIN[${key}]}"
        STRICT_STABLE=false
        stage_and_select "${OPT_PATTERN[${key}]}" "${label}" "${OPT_LIB[${key}]}" || true
    fi
    OPT_CHOSEN["${key}"]="${CHOSEN}"
    if [[ -n "${CHOSEN}" ]]; then
        info "Checking syntax…"
        syntax_ok "${CHOSEN}" \
            || die "Syntax error in $(basename "${CHOSEN}") — install aborted"
        ok "Syntax OK"
    fi
    return 0
}

REG_KEYS=(dashboard sysmon wifimon 44helper pibrary nodetalker noderecorder termon instmon)
LEGACY=false
ONLY_INSTALLED=false
STEP_C=false
STEP_D=false
RESET_DONE=false
HW_BUILD="full"
HW_TEXT="full-size Pi"
BACKUP_DIR="${ASL_DVS_BACKUP_DIR:-${ASL_DVS_ETC}/install_backup}"
DOCS_DIR="${INSTMON_LIBRARY_DIR}/docs"
DOCS_MAX_BYTES=$((64 * 1024 * 1024))
MAN_RE='^ASL-DVS_[A-Za-z0-9._-]*_(Manual|Guide)\.pdf$'
MAN_DELETED_FILE="${ASL_DVS_ETC}/instmon_manuals_deleted.json"
MAN_FETCHED_FILE="${ASL_DVS_ETC}/instmon_manuals_fetched"
MAN_LIST=()
MAN_DELETED=()
MAN_BYTES=0
MAN_STATE=""
MAN_RESTORE=false
F_FAILED=()
declare -A RS_TOUCHED=() RS_SKIP=() HC_HELD=()
HC_REASON=""

reg_label() {
    case "$1" in
        dashboard) echo "Dashboard" ;;
        sysmon) echo "SysMon" ;;
        wifimon) echo "wifimon" ;;
        44helper) echo "44helper" ;;
        nodetalker) echo "Node Talker" ;;
        instmon) echo "instmon" ;;
        noderecorder|pibrary|termon) echo "${OPT_LABEL[$1]}" ;;
    esac
}

reg_svc() {
    case "$1" in
        dashboard) echo "${DASH_SERVICE}" ;;
        sysmon) echo "${SYSMON_SERVICE}" ;;
        wifimon) echo "${WIFIMON_SERVICE}" ;;
        44helper) echo "${HELPER_SERVICE}" ;;
        nodetalker)
            if [[ "${NODELISTEN_SERVICE}" == "nodetalker" && ! -f /etc/systemd/system/nodetalker.service \
                  && -f /etc/systemd/system/nodelisten.service ]]; then
                echo "nodelisten"
            else
                echo "${NODELISTEN_SERVICE}"
            fi
            ;;
        instmon) echo "${INSTMON_SERVICE}" ;;
        noderecorder|pibrary|termon) echo "${OPT_SERVICE[$1]}" ;;
    esac
}

reg_bin() {
    case "$1" in
        dashboard) echo "${DASH_BIN}" ;;
        sysmon) echo "${SYSMON_BIN}" ;;
        wifimon) echo "${WIFIMON_BIN}" ;;
        44helper) echo "${HELPER_BIN}" ;;
        nodetalker) echo "${NODELISTEN_BIN}" ;;
        instmon) echo "${INSTMON_BIN}" ;;
        noderecorder|pibrary|termon) echo "${OPT_BIN[$1]}" ;;
    esac
}

conf_port() {
    sed -n 's/^[[:space:]]*port[[:space:]]*=[[:space:]]*\([0-9]\{4,5\}\)[[:space:]]*$/\1/p' "$1" 2>/dev/null | head -1 || true
}

reg_port() {
    local p
    case "$1" in
        dashboard) echo "${DASH_PORT}" ;;
        sysmon) echo "${SYSMON_PORT}" ;;
        wifimon) echo "${WIFIMON_PORT}" ;;
        44helper) echo "${HELPER_PORT}" ;;
        instmon) echo "${INSTMON_PORT}" ;;
        nodetalker)
            p="$(conf_port "${NODELISTEN_CONF}")"
            echo "${p:-${NODELISTEN_PORT}}"
            ;;
        termon)
            p="$(conf_port "${ASL_DVS_ETC}/termon.conf")"
            echo "${p:-${OPT_PORT[termon]}}"
            ;;
        noderecorder|pibrary) echo "${OPT_PORT[$1]}" ;;
    esac
}

reg_conf() {
    case "$1" in
        dashboard) echo "${DASH_CONF}" ;;
        sysmon) echo "${SYSMON_CONF_DIR}/sysmon.conf" ;;
        nodetalker) echo "${NODELISTEN_CONF}" ;;
        termon) echo "${ASL_DVS_ETC}/termon.conf" ;;
        *) echo "" ;;
    esac
}

reg_installed() {
    [[ -f "$(reg_bin "$1")" ]] && return 0
    svc_active "$(reg_svc "$1")"
}

reg_chosen() {
    case "$1" in
        dashboard) echo "${DASH_CHOSEN:-}" ;;
        sysmon) echo "${SYSMON_CHOSEN:-}" ;;
        wifimon) echo "${WIFIMON_CHOSEN:-}" ;;
        44helper) echo "${HELPER_CHOSEN:-}" ;;
        nodetalker) echo "${NODELISTEN_CHOSEN:-}" ;;
        instmon) echo "${INSTMON_CHOSEN:-}" ;;
        noderecorder|pibrary|termon) echo "${OPT_CHOSEN[$1]:-}" ;;
    esac
}

reg_unchoose() {
    case "$1" in
        dashboard) DASH_CHOSEN="" ;;
        sysmon) SYSMON_CHOSEN="" ;;
        wifimon) WIFIMON_CHOSEN="" ;;
        44helper) HELPER_CHOSEN="" ;;
        nodetalker) NODELISTEN_CHOSEN="" ;;
        instmon) INSTMON_CHOSEN="" ;;
        noderecorder|pibrary|termon) OPT_CHOSEN["$1"]="" ;;
    esac
}

is_heavy() {
    [[ "$1" == "nodetalker" || "$1" == "noderecorder" ]]
}

small_pi() {
    [[ "${HW_BUILD}" == "pi02w" || "${DASH_VARIANT:-}" == "pi02w" ]]
}

tool_allowed() {
    local key="$1" exists="$2"
    if [[ -n "${TOOLS_LIST}" ]]; then
        if [[ ",${TOOLS_LIST}," == *",${key},"* ]]; then
            return 0
        fi
        info "$(reg_label "${key}"): not in --tools — left out"
        return 1
    fi
    if [[ "${ONLY_INSTALLED}" == "true" && "${exists}" != "true" ]]; then
        info "$(reg_label "${key}") is not installed — a full upgrade does not add it (use Full replace or Component install)"
        return 1
    fi
    return 0
}

caller_is_instmon() {
    local pid="$$" n=0 cmd
    if [[ "${ASL_DVS_CALLER:-}" == "instmon" ]]; then
        return 0
    fi
    if grep -qs '/instmon\.service' "/proc/$$/cgroup"; then
        return 0
    fi
    while [[ "${pid}" =~ ^[0-9]+$ && "${pid}" -gt 1 && ${n} -lt 20 ]]; do
        cmd="$(tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null || true)"
        if [[ "${cmd}" == *instmon*.py* ]]; then
            return 0
        fi
        pid="$(sed -E 's/^.*\) [A-Za-z] ([0-9]+) .*$/\1/' "/proc/${pid}/stat" 2>/dev/null || echo 1)"
        n=$((n + 1))
    done
    return 1
}

port_busy() {
    ss -tln "sport = :$1" 2>/dev/null | grep -q ":$1"
}

port_owner() {
    ss -tlnp "sport = :$1" 2>/dev/null | awk 'NR>1 {print $NF}' | head -1 || true
}

conf_damaged() {
    python3 -I -c 'import sys
data = open(sys.argv[1], "rb").read()
sys.exit(0 if b"\0" in data else 1)' "$1" 2>/dev/null
}

reset_stop() {
    local k svc i n
    local -a order=()
    hdr "[D] Reset: services and sign-ins"
    for (( i=${#REG_KEYS[@]}-1; i>=0; i-- )); do
        order+=("${REG_KEYS[${i}]}")
    done
    for k in "${order[@]}"; do
        reg_installed "${k}" || continue
        svc="$(reg_svc "${k}")"
        if [[ "${k}" == "instmon" ]] && caller_is_instmon; then
            info "instmon is running this installer — left running"
            RS_SKIP["${k}"]="caller"
            continue
        fi
        if json_has_service "${QUIET_STATE_FILE}" "${svc}"; then
            info "${svc} is paused by Quiet System — left as it is (instmon resumes it)"
            RS_SKIP["${k}"]="quiet"
            continue
        fi
        RS_TOUCHED["${k}"]=1
        if svc_active "${svc}"; then
            RS_WAS_ACTIVE["${svc}"]=1
            info "Stopping ${svc}"
            systemctl stop "${svc}" 2>/dev/null || true
        elif user_stopped "${svc}"; then
            HELD["${svc}"]="enabled"
            if [[ "$(systemctl is-enabled "${svc}" 2>/dev/null || true)" == "disabled" ]]; then
                HELD["${svc}"]="disabled"
            fi
            info "${svc} was stopped by you — it stays stopped"
        fi
    done
    for k in "${order[@]}"; do
        [[ -n "${RS_TOUCHED[${k}]+x}" ]] || continue
        svc="$(reg_svc "${k}")"
        n=0
        while svc_active "${svc}" && [[ ${n} -lt 10 ]]; do
            sleep 1
            n=$((n + 1))
        done
        if svc_active "${svc}"; then
            warn "${svc} came back by itself — stopping it again"
            systemctl stop "${svc}" 2>/dev/null || true
        fi
        systemctl reset-failed "${svc}" 2>/dev/null || true
    done
    ok "Failed marks cleared"
    if ! svc_active "$(reg_svc dashboard)" && ! svc_active "${SYSMON_SERVICE}"; then
        if [[ -e "${RUN_DIR}/asl_dvs/auth_session.json" ]]; then
            rm -f -- "${RUN_DIR}/asl_dvs/auth_session.json"
            ok "Cleared the shared sign-ins of the Dashboard and SysMon"
        fi
    else
        warn "The Dashboard or SysMon is still running — their shared sign-ins were kept"
    fi
    if ! svc_active "${HELPER_SERVICE}" && [[ -e "${RUN_DIR}/44helper/sessions.json" ]]; then
        rm -f -- "${RUN_DIR}/44helper/sessions.json"
        ok "Cleared 44helper's saved sign-ins"
    fi
    if ! svc_active "${OPT_SERVICE[termon]}"; then
        for i in "${RUN_DIR}/termon.lock" "${RUN_DIR}/termon/termon.lock"; do
            if [[ -e "${i}" ]]; then
                rm -f -- "${i}"
                ok "Removed the stale lock ${i}"
            fi
        done
    fi
    RESET_DONE=true
    if [[ ${#RS_TOUCHED[@]} -gt 0 ]]; then
        ok "Everyone is signed out — sign in again on each page once it is back"
    fi
    return 0
}

health_check() {
    local k="$1" file="$2" label port conf n owner
    label="$(reg_label "${k}")"
    HC_REASON=""
    if [[ -n "${file}" && "${file}" == *.py && -f "${file}" ]] && ! syntax_ok "${file}" 2>/dev/null; then
        HC_REASON="$(basename "${file}") failed the syntax check"
    fi
    port="$(reg_port "${k}")"
    if [[ -z "${HC_REASON}" && -n "${port}" ]] && command -v ss &>/dev/null; then
        n=0
        while port_busy "${port}" && [[ ${n} -lt 5 ]]; do
            sleep 1
            n=$((n + 1))
        done
        if port_busy "${port}"; then
            owner="$(port_owner "${port}")"
            HC_REASON="port ${port} is in use by ${owner:-another program} (check: ss -tlnp | grep ${port})"
        fi
    fi
    conf="$(reg_conf "${k}")"
    if [[ -z "${HC_REASON}" && -n "${conf}" && -e "${conf}" ]]; then
        if [[ -d "${conf}" || ! -r "${conf}" ]]; then
            HC_REASON="${conf} cannot be read"
        elif conf_damaged "${conf}"; then
            HC_REASON="${conf} is damaged (not a text file) — left in place for you to check"
        elif [[ "${k}" == "dashboard" ]] && ! { grep -q '^[[:space:]]*asl_node[[:space:]]*=' "${conf}" && grep -q '^[[:space:]]*callsign[[:space:]]*=' "${conf}"; }; then
            warn "${label}: ${conf} has no asl_node or callsign line — check it on the Dashboard's page"
        fi
    fi
    if [[ -n "${HC_REASON}" ]]; then
        warn "${label}: held — ${HC_REASON}"
        HC_HELD["${k}"]="${HC_REASON}"
        return 1
    fi
    ok "${label}: file, port and config checked"
    return 0
}

start_verify() {
    local k svc port chosen n label
    if [[ "${LEGACY}" == "true" ]]; then
        hdr "Startup verification"
    else
        hdr "[F] Start and check"
        systemctl daemon-reload 2>/dev/null || true
    fi
    info "Waiting for services to stabilise…"
    sleep 3
    for k in "${REG_KEYS[@]}"; do
        chosen="$(reg_chosen "${k}")"
        if [[ -z "${chosen}" && -z "${RS_TOUCHED[${k}]+x}" && -z "${HC_HELD[${k}]+x}" ]]; then
            continue
        fi
        if [[ "${k}" == "nodetalker" && -n "${chosen}" ]]; then
            svc="${NODELISTEN_SERVICE}"
        else
            svc="$(reg_svc "${k}")"
        fi
        port="$(reg_port "${k}")"
        label="$(reg_label "${k}")"
        if [[ -n "${HELD[${svc}]+x}" ]]; then
            ok "${svc} is stopped, as you had it"
            continue
        fi
        if [[ -n "${HC_HELD[${k}]+x}" ]]; then
            warn "${svc} held — not started: ${HC_HELD[${k}]}"
            continue
        fi
        if [[ "${LEGACY}" != "true" ]] && ! svc_active "${svc}"; then
            if is_heavy "${k}" && small_pi; then
                sleep "${HEAVY_PAUSE}"
            fi
            systemctl reset-failed "${svc}" 2>/dev/null || true
            info "Starting ${svc}"
            timeout 30 systemctl start "${svc}" 2>/dev/null || true
            n=0
            while ! svc_active "${svc}" && [[ ${n} -lt ${START_WAIT} ]]; do
                sleep 1
                n=$((n + 1))
            done
        fi
        if svc_active "${svc}"; then
            ok "${svc} is RUNNING"
        else
            warn "${svc} did not start cleanly"
            F_FAILED+=("${svc}")
            systemctl status "${svc}" --no-pager -l 2>/dev/null || true
            if [[ "${LEGACY}" != "true" ]] && command -v journalctl &>/dev/null; then
                info "Last lines of its log:"
                timeout 10 journalctl -u "${svc}" -n 15 --no-pager 2>/dev/null | sed 's/^/      /' || true
            fi
            continue
        fi
        [[ -z "${port}" ]] && continue
        if ss -tlnp "sport = :${port}" 2>/dev/null | grep -q ":${port}"; then
            ok "Listening on port ${port}"
        else
            warn "Not yet listening on port ${port} — may still be initialising"
            warn "Re-check:  ss -tlnp | grep ${port}"
        fi
    done
    return 0
}

status_table() {
    local k svc state note
    echo
    echo "  ${BLD}$1${RST}"
    for k in "${REG_KEYS[@]}"; do
        reg_installed "${k}" || continue
        svc="$(reg_svc "${k}")"
        state="$(systemctl is-active "${svc}" 2>/dev/null || true)"
        note=""
        [[ -n "${HELD[${svc}]+x}" ]] && note="stopped, as you had it"
        [[ -n "${HC_HELD[${k}]+x}" ]] && note="held: ${HC_HELD[${k}]}"
        [[ "${RS_SKIP[${k}]:-}" == "quiet" ]] && note="paused by Quiet System"
        [[ "${RS_SKIP[${k}]:-}" == "caller" ]] && note="running this installer"
        printf '    %-18s %-10s %s\n' "$(reg_label "${k}")" "${state:-unknown}" "${note}"
    done
    echo
}

run_reset_only() {
    local k any=false ans
    hdr "Reset only"
    for k in "${REG_KEYS[@]}"; do
        if reg_installed "${k}"; then
            any=true
        fi
    done
    if [[ "${any}" != "true" ]]; then
        die "Nothing is installed on this node — nothing to reset."
    fi
    info "Stops the installed tools, clears failed marks and sign-ins, checks each one and starts it again."
    info "Nothing is installed or downloaded; configs, manuals and the root password are not touched."
    status_table "Before:"
    if [[ "${NONINTERACTIVE}" != "true" ]]; then
        read -r -p "  Reset now? Everyone is signed out. [Y/n]: " ans </dev/tty
        case "${ans,,}" in
            n|no|q|quit) echo; info "Aborted by user."; exit 0 ;;
        esac
    fi
    reset_stop
    hdr "[E] Checks before each start"
    for k in "${REG_KEYS[@]}"; do
        [[ -n "${RS_TOUCHED[${k}]+x}" ]] || continue
        [[ -n "${HELD[$(reg_svc "${k}")]+x}" ]] && continue
        if health_check "${k}" "$(reg_bin "${k}")" && ! systemctl cat "$(reg_svc "${k}")" &>/dev/null; then
            warn "$(reg_label "${k}"): held — its unit file is missing (reinstall it)"
            HC_HELD["${k}"]="its unit file is missing (reinstall it)"
        fi
    done
    start_verify
    status_table "After:"
    if [[ ${#F_FAILED[@]} -gt 0 ]]; then
        warn "Did not start: ${F_FAILED[*]}"
        exit 1
    fi
    ok "Reset done"
    exit 0
}

detect_hardware() {
    local model dash_b sys_b eff ans
    hdr "Hardware"
    model="$(tr -d '\0' 2>/dev/null < "${MODEL_FILE}" || true)"
    if is_zero2; then
        HW_BUILD="pi02w"
        HW_TEXT="Pi Zero 2 W"
    fi
    info "This Pi: ${model:-model not known}"
    dash_b="$(bin_build "${DASH_BIN}")"
    sys_b="$(bin_build "${SYSMON_BIN}")"
    if [[ -n "${BUILD_ARG}" && "${BUILD_ARG}" != "${HW_BUILD}" ]]; then
        warn "--build=${BUILD_ARG} on a ${HW_TEXT}: the ${BUILD_ARG} builds are used, as asked"
    elif [[ -z "${DASH_VARIANT:-}${SYSMON_VARIANT:-}" ]] \
         && { [[ -n "${dash_b}" && "${dash_b}" != "${HW_BUILD}" ]] || [[ -n "${sys_b}" && "${sys_b}" != "${HW_BUILD}" ]]; }; then
        warn "The installed Dashboard or SysMon is the ${dash_b:-${sys_b}} build, but this Pi is a ${HW_TEXT}"
        if [[ "${NONINTERACTIVE}" == "true" || "${RESET_ONLY}" == "true" ]]; then
            info "The installed build is kept (--build=${HW_BUILD} switches it)"
        else
            read -r -p "  Switch the Dashboard and SysMon to the ${HW_TEXT} build? [y/N]: " ans </dev/tty
            case "${ans,,}" in
                y|yes)
                    DASH_VARIANT="${HW_BUILD}"
                    SYSMON_VARIANT="${HW_BUILD}"
                    ok "Switching to the ${HW_TEXT} build"
                    ;;
                *) info "The installed build is kept" ;;
            esac
        fi
    fi
    eff="${DASH_VARIANT:-${dash_b:-${HW_BUILD}}}"
    if [[ "${eff}" == "pi02w" ]]; then
        ok "Dashboard and SysMon: Pi Zero 2 W builds (nodecontrol_pi02w, sysmon_pi02w)"
    else
        ok "Dashboard and SysMon: full builds"
    fi
    return 0
}

manuals_scan() {
    local mode type blob size path name dest deleted
    MAN_LIST=()
    MAN_DELETED=()
    MAN_BYTES=0
    if [[ "${DOWNLOAD}" != "true" ]]; then
        MAN_STATE="offline"
        return 1
    fi
    if ! open_repo; then
        MAN_STATE="no GitHub"
        return 1
    fi
    deleted="$(python3 -I -c 'import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    data = []
for n in data if isinstance(data, list) else []:
    if isinstance(n, str):
        print(n)' "${MAN_DELETED_FILE}" 2>/dev/null || true)"
    while read -r mode type blob size path; do
        [[ "${type}" == "blob" && "${path}" == docs/* ]] || continue
        name="${path#docs/}"
        [[ "${name}" =~ ${MAN_RE} ]] || continue
        [[ "${size}" =~ ^[0-9]+$ && "${size}" -gt 0 && "${size}" -le ${DOCS_MAX_BYTES} ]] || continue
        dest="${DOCS_DIR}/${name}"
        if [[ -f "${dest}" ]]; then
            [[ "$(git hash-object "${dest}" 2>/dev/null)" == "${blob}" ]] && continue
            MAN_LIST+=("${blob} ${size} ${name} changed")
        elif grep -qxF -- "${name}" <<< "${deleted}"; then
            MAN_DELETED+=("${blob} ${size} ${name} restored")
            continue
        else
            MAN_LIST+=("${blob} ${size} ${name} new")
        fi
        MAN_BYTES=$((MAN_BYTES + size))
        : "${mode}"
    done < <(git -C "${FETCH_REPO}" ls-tree -l HEAD docs/ 2>/dev/null)
    MAN_STATE="ok"
    return 0
}

manuals_install() {
    local row blob size name why tmp got=() failed=0
    hdr "[C] Manuals"
    if [[ "${MAN_STATE}" != "ok" ]]; then
        info "Manuals skipped (${MAN_STATE:-not checked})"
        return 0
    fi
    local -a rows=("${MAN_LIST[@]}")
    if [[ "${MAN_RESTORE}" == "true" ]]; then
        rows+=("${MAN_DELETED[@]}")
    elif [[ ${#MAN_DELETED[@]} -gt 0 ]]; then
        info "${#MAN_DELETED[@]} manual(s) you deleted in instmon are left out"
    fi
    mkdir -p "${DOCS_DIR}" || { warn "Could not make ${DOCS_DIR} — manuals skipped"; return 0; }
    for row in "${rows[@]}"; do
        read -r blob size name why <<< "${row}"
        tmp="$(mktemp "${FETCH_DIR}/doc.XXXXXX")"
        if ! GIT_TERMINAL_PROMPT=0 git -C "${FETCH_REPO}" show "HEAD:docs/${name}" > "${tmp}" 2>/dev/null; then
            warn "Manual ${name}: download failed"
            rm -f -- "${tmp}"
            failed=$((failed + 1))
            continue
        fi
        if [[ "$(git hash-object "${tmp}")" != "${blob}" ]]; then
            warn "Manual ${name}: the download does not match GitHub's file list — not saved"
            rm -f -- "${tmp}"
            failed=$((failed + 1))
            continue
        fi
        if [[ "$(head -c 5 "${tmp}")" != "%PDF-" ]]; then
            warn "Manual ${name}: not a PDF file — not saved"
            rm -f -- "${tmp}"
            failed=$((failed + 1))
            continue
        fi
        chmod 644 "${tmp}"
        mv -f -- "${tmp}" "${DOCS_DIR}/${name}"
        got+=("${name}")
        ok "Manual ${name} (${why}, $((size / 1024)) KB)"
    done
    if [[ ${#got[@]} -gt 0 && -f "${MAN_DELETED_FILE}" ]]; then
        python3 -I -c 'import json, os, sys
path = sys.argv[1]
try:
    data = json.load(open(path))
except Exception:
    sys.exit(0)
if not isinstance(data, list):
    sys.exit(0)
keep = sorted(n for n in data if isinstance(n, str) and n not in set(sys.argv[2:]))
tmp = path + ".tmp"
with open(tmp, "w") as fh:
    json.dump(keep, fh)
os.replace(tmp, path)' "${MAN_DELETED_FILE}" "${got[@]}" 2>/dev/null || true
    fi
    if mkdir -p "${ASL_DVS_ETC}" 2>/dev/null; then
        date '+%Y-%m-%d %H:%M' > "${MAN_FETCHED_FILE}" 2>/dev/null || true
    fi
    if [[ ${failed} -gt 0 ]]; then
        warn "Manuals: ${#got[@]} saved to ${DOCS_DIR}, ${failed} failed"
    else
        ok "Manuals: ${#got[@]} saved to ${DOCS_DIR}"
    fi
    return 0
}

backup_files() {
    local k bin chosen dest ts ver n=0
    hdr "[A] Back up"
    ts="$(date +%Y%m%d_%H%M%S)"
    dest="${BACKUP_DIR}/${ts}"
    for k in "${REG_KEYS[@]}"; do
        chosen="$(reg_chosen "${k}")"
        bin="$(reg_bin "${k}")"
        [[ -n "${chosen}" && -f "${bin}" ]] || continue
        mkdir -p "${dest}" || { warn "Could not make ${dest} — no backup"; return 0; }
        ver="$(file_version "${bin}")"
        cp -p -- "${bin}" "${dest}/$(basename "${bin}" .py)${ver:+_${ver}}.py"
        n=$((n + 1))
    done
    if [[ ${n} -eq 0 ]]; then
        info "Nothing installed is replaced — nothing to back up"
        return 0
    fi
    ok "Backed up ${n} installed file(s) → ${dest}/"
    local -a old=()
    mapfile -t old < <(find "${BACKUP_DIR}" -mindepth 1 -maxdepth 1 -type d -name '20*' 2>/dev/null | sort -r | tail -n +4)
    for d in "${old[@]}"; do
        rm -rf -- "${d}"
    done
    return 0
}

set_steps() {
    case "${ACTION}" in
        first|replace) STEP_C="${MANUALS}" ;;
        upgrade) STEP_C=false ;;
        components)
            STEP_C=false
            if [[ ",${TOOLS_LIST}," == *",manuals,"* ]]; then
                STEP_C="${MANUALS}"
            fi
            ;;
    esac
    if [[ "${NONINTERACTIVE}" == "true" ]]; then
        STEP_D=false
        if [[ "${RESET_ARG}" == "on" ]]; then
            STEP_D=true
        fi
    else
        STEP_D=true
        if [[ "${RESET_ARG}" == "off" ]]; then
            STEP_D=false
        fi
    fi
    if [[ -n "${STEPS_ARG}" ]]; then
        STEP_C=false
        STEP_D=false
        [[ "${STEPS_ARG}" == *C* ]] && STEP_C="${MANUALS}"
        [[ "${STEPS_ARG}" == *D* ]] && STEP_D=true
        if [[ "${STEPS_ARG}" != *A* || "${STEPS_ARG}" != *B* || "${STEPS_ARG}" != *E* || "${STEPS_ARG}" != *F* ]]; then
            info "--steps: [A] back up, [B] install, [E] check and [F] start always run; only [C] and [D] can be left out"
        fi
    fi
    if [[ "${ACTION}" == "replace" && "${STEP_D}" != "true" && "${NONINTERACTIVE}" == "true" \
          && "${RESET_ARG}" != "off" && -z "${STEPS_ARG}" ]]; then
        die "--action=replace without a terminal needs --reset (everyone is signed out) or --no-reset (not recommended: a replace without the reset is the usual cause of a bad start)"
    fi
    if [[ "${ACTION}" == "replace" && "${STEP_D}" != "true" ]]; then
        warn "Full replace without [D] RESET — the usual cause of a bad start"
    fi
    if [[ "${DOWNLOAD}" != "true" && "${STEP_C}" == "true" ]]; then
        info "Offline: [C] manuals are skipped"
    fi
    return 0
}

plan_names() {
    local k chosen out=""
    for k in "${REG_KEYS[@]}"; do
        chosen="$(reg_chosen "${k}")"
        [[ -n "${chosen}" ]] || continue
        out+="${out:+, }$(reg_label "${k}") ($(basename "${chosen}"))"
    done
    echo "${out:-nothing}"
}

plan_left_out() {
    local k out=""
    for k in "${REG_KEYS[@]}"; do
        [[ -z "$(reg_chosen "${k}")" ]] || continue
        out+="${out:+, }$(reg_label "${k}")"
    done
    echo "${out}"
}

show_plan() {
    local build="full" verb left
    small_pi && build="Pi Zero 2 W"
    [[ -n "${DASH_VARIANT:-}" ]] && { [[ "${DASH_VARIANT}" == "pi02w" ]] && build="Pi Zero 2 W" || build="full"; }
    case "${ACTION}" in
        first) verb="Install" ;;
        upgrade) verb="Upgrade" ;;
        replace) verb="Replace" ;;
        *) verb="Install" ;;
    esac
    hdr "Plan: ${ACTION_LABEL} (${build} builds, ${GH_CHANNEL} channel)"
    echo "  [A] Back up    installed files that are replaced → ${BACKUP_DIR}/"
    echo "  [B] ${verb}$(printf '%*s' $((11 - ${#verb})) '')$(plan_names)"
    if [[ "${STEP_C}" == "true" ]]; then
        if [[ "${MAN_STATE}" == "ok" ]]; then
            echo "  [C] Manuals    ${#MAN_LIST[@]} to download ($(( (MAN_BYTES + 1048575) / 1048576 )) MB) → ${DOCS_DIR}/"
        else
            echo "  [C] Manuals    skipped (${MAN_STATE:-not checked})"
        fi
    else
        echo "   -  [C] Manuals left out"
    fi
    if [[ "${STEP_D}" == "true" ]]; then
        echo "  [D] RESET      stop the tools, clear failed marks and sign-ins (everyone signs in again)$([[ "${ACTION}" == "replace" ]] && echo '  ← required for a replace')"
    else
        echo "   -  [D] RESET left out$([[ "${ACTION}" == "replace" ]] && echo ' — not recommended for a replace')"
    fi
    echo "  [E] Check      file, port and config of each tool before it starts"
    echo "  [F] Start      in order, then check each one is running"
    left="$(plan_left_out)"
    if [[ -n "${left}" ]]; then
        echo "  Left out: ${left}"
    fi
    echo
}

repeat_line() {
    local -a args=(--non-interactive "--action=${ACTION}")
    local k list="" script prefix=""
    if [[ -n "${DASH_VARIANT:-}" ]]; then
        args+=("--build=${DASH_VARIANT}")
    fi
    if [[ "${ACTION}" == "components" ]]; then
        for k in "${REG_KEYS[@]}"; do
            [[ -n "$(reg_chosen "${k}")" ]] && list+="${list:+,}${k}"
        done
        [[ "${STEP_C}" == "true" ]] && list+="${list:+,}manuals"
        args+=("--tools=${list:-none}")
    fi
    if [[ "${STEP_D}" == "true" ]]; then
        args+=(--reset)
    else
        args+=(--no-reset)
    fi
    if [[ "${STEP_C}" != "true" && "${ACTION}" != "upgrade" && "${ACTION}" != "components" ]]; then
        args+=(--no-manuals)
    fi
    [[ "${DOWNLOAD}" != "true" ]] && args+=(--offline)
    [[ "${CORE}" == "true" ]] && args+=(--core)
    if [[ "${ACTION}" != "components" && -n "${OPT_CHOSEN[termon]:-}" ]]; then
        args+=(--with-termon)
    fi
    [[ "${GH_CHANNEL}" == "testing" ]] && prefix="ASL_DVS_CHANNEL=testing "
    script="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null || echo "${BASH_SOURCE[0]}")"
    echo "  To repeat this without questions:"
    echo "    sudo ${prefix}bash ${script} ${args[*]}"
    echo
}

confirm_plan() {
    local ans letters ch typed i
    if [[ "${ACTION}" == "components" && "${NONINTERACTIVE}" != "true" ]]; then
        if [[ "${DOWNLOAD}" == "true" && "${MANUALS}" == "true" && -z "${STEPS_ARG}" ]]; then
            read -r -p "  Download the manuals too? [y/N]: " ans </dev/tty
            case "${ans,,}" in
                y|yes) STEP_C=true ;;
            esac
        fi
        if [[ "${_any_installed}" == "true" && -z "${RESET_ARG}" && -z "${STEPS_ARG}" ]]; then
            read -r -p "  Reset the services and sign everyone out first? [Y/n]: " ans </dev/tty
            case "${ans,,}" in
                n|no) STEP_D=false ;;
            esac
        elif [[ "${_any_installed}" != "true" && -z "${RESET_ARG}" ]]; then
            STEP_D=false
        fi
    fi
    if [[ "${STEP_C}" == "true" && -z "${MAN_STATE}" ]]; then
        manuals_scan || true
        if [[ "${ACTION}" == "replace" && ${#MAN_DELETED[@]} -gt 0 && "${NONINTERACTIVE}" != "true" ]]; then
            read -r -p "  Restore the ${#MAN_DELETED[@]} manual(s) you deleted in instmon? [y/N]: " ans </dev/tty
            case "${ans,,}" in
                y|yes) MAN_RESTORE=true; MAN_LIST+=("${MAN_DELETED[@]}") ;;
            esac
        fi
    fi
    if [[ "${NONINTERACTIVE}" == "true" ]]; then
        show_plan
        return 0
    fi
    while true; do
        show_plan
        repeat_line
        read -r -p "  Go ahead? [Y/n, or letters to leave out, e.g. C]: " ans </dev/tty
        case "${ans,,}" in
            ""|y|yes) return 0 ;;
            n|no|q|quit) echo; info "Aborted by user."; exit 0 ;;
        esac
        letters="${ans^^}"
        letters="${letters//[^A-F]/}"
        if [[ -z "${letters}" ]]; then
            warn "Enter y to go ahead, n to quit, or step letters to leave out (C or D)"
            continue
        fi
        for (( i=0; i<${#letters}; i++ )); do
            ch="${letters:${i}:1}"
            case "${ch}" in
                C) STEP_C=false; info "[C] Manuals left out" ;;
                D)
                    if [[ "${ACTION}" == "replace" ]]; then
                        echo "  Replacing without the reset is the usual cause of a bad start."
                        read -r -p "  Type skip to leave [D] out anyway: " typed </dev/tty
                        if [[ "${typed,,}" == "skip" ]]; then
                            STEP_D=false
                            warn "[D] RESET left out"
                        else
                            info "[D] RESET kept"
                        fi
                    else
                        STEP_D=false
                        info "[D] RESET left out"
                    fi
                    ;;
                A) warn "[A] always runs with [B]" ;;
                B) warn "[B] is the install itself — enter n to quit instead" ;;
                E) warn "[E] always runs before [F]" ;;
                F) warn "[F] always runs: it starts and checks each tool" ;;
            esac
        done
    done
}

show_menu() {
    local ans def
    if [[ "${FRESH}" == "true" ]]; then
        def=1
        echo "  ${BLD}Nothing is installed on this node yet.${RST}"
    else
        def=2
    fi
    if [[ "${DOWNLOAD}" == "true" ]]; then
        echo "  Files that are not on this Pi are downloaded from GitHub (${GH_CHANNEL} channel)."
    else
        echo "  Offline: only the files on this Pi are used."
    fi
    echo
    echo "  ${BLD}[1]${RST}  Full first install   ${CYN}the whole suite and the manuals$([[ "${def}" == 1 ]] && echo '  (default)')${RST}"
    echo "  ${BLD}[2]${RST}  Full upgrade         ${CYN}installed tools to the newest build; config kept, nothing added$([[ "${def}" == 2 ]] && echo '  (default)')${RST}"
    echo "  ${BLD}[3]${RST}  Full replace         ${CYN}reinstall every tool, complete the suite, refresh the manuals, reset${RST}"
    echo "  ${BLD}[4]${RST}  Component install    ${CYN}choose tool by tool${RST}"
    echo "  ${BLD}[5]${RST}  Reset only           ${CYN}restart the services and sign everyone out; nothing installed${RST}"
    echo "  ${BLD}[q]${RST}  Quit"
    echo "  Terminal Monitor is never part of a full install; it is asked about on its own."
    echo
    while true; do
        read -r -p "  Choose [1-5/q] (Enter = ${def}): " ans </dev/tty
        ans="${ans,,}"
        case "${ans}" in
            "") ans="${def}" ;;
            y|yes) ans="${def}" ;;
            i|install) ans=3 ;;
            u|update) ans=2 ;;
            c|choose) ans=4 ;;
            r|reset) ans=5 ;;
            n|no|q|quit) echo; info "Aborted by user."; exit 0 ;;
        esac
        case "${ans}" in
            1)
                if [[ "${FRESH}" != "true" ]]; then
                    warn "Tools are already installed here — choose 2 (upgrade) or 3 (replace)"
                    continue
                fi
                ACTION="first"
                ;;
            2|3|5)
                if [[ "${FRESH}" == "true" ]]; then
                    warn "Nothing is installed yet — choose 1 (full first install) or 4 (component install)"
                    continue
                fi
                case "${ans}" in
                    2) ACTION="upgrade" ;;
                    3) ACTION="replace" ;;
                    5) RESET_ONLY=true ;;
                esac
                ;;
            4) ACTION="components" ;;
            *) warn "Enter 1, 2, 3, 4, 5 or q"; continue ;;
        esac
        return 0
    done
}

apply_action() {
    case "${ACTION}" in
        first)
            MODE="install"
            ACTION_LABEL="Full first install"
            [[ "${CORE}" == "true" ]] || SUITE=true
            AUTO_PICK=true
            ;;
        upgrade)
            MODE="update"
            ACTION_LABEL="Full upgrade"
            AUTO_PICK=true
            FORCE_FETCH=true
            ONLY_INSTALLED=true
            NO_DOWNGRADE=true
            ;;
        replace)
            MODE="install"
            ACTION_LABEL="Full replace"
            [[ "${CORE}" == "true" ]] || SUITE=true
            AUTO_PICK=true
            FORCE_FETCH=true
            REINSTALL=true
            NO_DOWNGRADE=true
            ;;
        components)
            MODE="install"
            ACTION_LABEL="Component install"
            ;;
    esac
    ok "Action: ${ACTION_LABEL}"
    set_steps
}

hdr "Preflight"

if [[ "${EUID}" -ne 0 ]]; then
    die "Must be run as root.  Use: sudo bash install_all.sh"
fi
ok "Running as root"

if ! command -v python3 &>/dev/null; then
    if [[ "${NONINTERACTIVE}" == "true" ]] || ! command -v apt-get &>/dev/null; then
        die "python3 not found.  Install with: apt install python3"
    fi
    read -r -p "  python3 is needed and is not installed. Install it with apt? [Y/n]: " _py_ans </dev/tty
    case "${_py_ans,,}" in
        n|no) die "python3 not found.  Install with: apt install python3" ;;
    esac
    apt_install python3 || true
    command -v python3 &>/dev/null || die "Could not install python3 (no network?)"
fi
ok "Python: $(python3 --version 2>&1)"

if ! command -v systemctl &>/dev/null; then
    die "systemctl not found — this installer requires systemd"
fi
ok "systemd available"

check_prereqs

detect_hardware

if [[ "${RESET_ONLY}" == "true" ]]; then
    run_reset_only
fi

if [[ "${DOWNLOAD_ONLY}" == "true" ]]; then
    hdr "Download only"
    if [[ "${DOWNLOAD}" != "true" ]]; then
        die "--download-only needs the network; do not use it with --offline"
    fi
    info "Channel: ${GH_CHANNEL}. Files for tools that are not installed are fetched into the library."
    info "Nothing is installed, enabled or started, and installed tools are left alone."
    STRICT_STABLE=true
    download_row() {
        local key="$1" label="$2" bin="$3" svc="$4" pattern="$5" exclude="$6" libdir="$7" build="$8"
        if [[ -f "${bin}" ]] || svc_active "${svc}"; then
            info "${label} is installed — not downloaded (update it with this installer or instmon)"
        elif any_file "${pattern}" "${libdir}" "${exclude}" true; then
            info "${label}: a file is already in the library — not downloaded again"
        else
            fetch_tool "${key}" "${label}" "${pattern}" "${exclude}" "${libdir}" "${build}" || true
        fi
        return 0
    }
    pick_build "${DASH_VARIANT:-}" "${DASH_BIN}" "DASH_VARIANT"
    if [[ "${PICKED_BUILD}" == "pi02w" ]]; then
        info "Dashboard build: Pi Zero 2 W, from ${PICKED_WHY}"
        download_row "nodecontrol_pi02w" "Dashboard (Pi Zero 2 W)" "${DASH_BIN}" "${DASH_SERVICE}" "nodecontrol_pi02w*.py|asl_dvs_dashboard_pi02w*.py" "" "${DASH_LIB_DIR}" pi02w
    else
        info "Dashboard build: full, from ${PICKED_WHY}"
        download_row "nodecontrol" "Dashboard" "${DASH_BIN}" "${DASH_SERVICE}" "nodecontrol*.py|asl_dvs_dashboard*.py" "nodecontrol_pi02w*.py|asl_dvs_dashboard_pi02w*.py" "${DASH_LIB_DIR}" full
    fi
    pick_build "${SYSMON_VARIANT:-}" "${SYSMON_BIN}" "SYSMON_VARIANT"
    if [[ "${PICKED_BUILD}" == "pi02w" ]]; then
        info "SysMon build: Pi Zero 2 W, from ${PICKED_WHY}"
        download_row "sysmon_pi02w" "SysMon (Pi Zero 2 W)" "${SYSMON_BIN}" "${SYSMON_SERVICE}" "sysmon_pi02w*.py" "" "${SYSMON_LIB_DIR}" pi02w
    else
        info "SysMon build: full, from ${PICKED_WHY}"
        download_row "sysmon" "SysMon" "${SYSMON_BIN}" "${SYSMON_SERVICE}" "sysmon*.py" "sysmon_pi02w*.py" "${SYSMON_LIB_DIR}" full
    fi
    download_row "wifimon" "wifimon" "${WIFIMON_BIN}" "${WIFIMON_SERVICE}" "wifimon*.py" "" "${WIFIMON_LIB_DIR}" ""
    download_row "44helper" "44helper" "${HELPER_BIN}" "${HELPER_SERVICE}" "44helper*.py|asl_dvs_m17_44helper*.py" "" "${HELPER_LIB_DIR}" ""
    download_row "nodetalker" "Node Talker" "${NODELISTEN_BIN}" "${NODELISTEN_SERVICE}" "${NODELISTEN_PATTERN}" "" "${NODELISTEN_LIB_DIR}" ""
    for _k in "${OPT_KEYS[@]}"; do
        download_row "${_k}" "${OPT_LABEL[${_k}]}" "${OPT_BIN[${_k}]}" "${OPT_SERVICE[${_k}]}" "${OPT_PATTERN[${_k}]}" "" "${OPT_LIB[${_k}]}" ""
    done
    echo
    if [[ ${#DOWNLOADED[@]} -gt 0 ]]; then
        hdr "Downloaded from GitHub"
        for _d in "${DOWNLOADED[@]}"; do ok "${_d}"; done
    else
        info "Nothing needed downloading."
    fi
    if [[ "${FETCH_STATE}" == "failed" ]]; then
        die "Could not reach GitHub — nothing was downloaded."
    fi
    ok "Download only: nothing was installed or started. Install from the Available card in instmon, or run this installer without --download-only."
    exit 0
fi

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
_opt_exists=false
for _k in "${OPT_KEYS[@]}"; do
    if opt_is_installed "${_k}"; then
        _opt_exists=true
    fi
done

_any_installed=false
FRESH=true
if [[ "${_dash_exists}" == "true" || "${_sysmon_exists}" == "true" \
      || "${_wifimon_exists}" == "true" || "${_helper_exists}" == "true" \
      || "${_nodelisten_exists}" == "true" || "${_opt_exists}" == "true" ]]; then
    _any_installed=true
    FRESH=false
fi
if [[ -n "${ACTION}" ]]; then
    if [[ "${ACTION}" == "first" && "${FRESH}" != "true" ]]; then
        die "--action=first: tools are already installed here — use --action=upgrade or --action=replace"
    fi
    if [[ ( "${ACTION}" == "upgrade" || "${ACTION}" == "replace" ) && "${FRESH}" == "true" ]]; then
        die "--action=${ACTION}: nothing is installed here yet — use --action=first"
    fi
elif [[ "${NONINTERACTIVE}" == "true" || ( "${FRESH}" == "true" && ( "${CORE}" == "true" || "${SUITE}" == "true" ) ) ]]; then
    LEGACY=true
fi

if [[ "${FRESH}" != "true" ]]; then
    echo
    echo "  ${BLD}Existing installation detected:${RST}"
    [[ "${_dash_exists}"     == "true" ]] && echo "  ${GRN}  ✔${RST}  Dashboard      (${DASH_BIN})"
    [[ "${_sysmon_exists}"   == "true" ]] && echo "  ${GRN}  ✔${RST}  SysMon         (${SYSMON_BIN})"
    [[ "${_wifimon_exists}"  == "true" ]] && echo "  ${GRN}  ✔${RST}  wifimon        (${WIFIMON_BIN})"
    [[ "${_helper_exists}"   == "true" ]] && echo "  ${GRN}  ✔${RST}  44helper       (${HELPER_BIN})"
    [[ "${_nodelisten_exists}" == "true" ]] && echo "  ${GRN}  ✔${RST}  Node Talker    (${NODELISTEN_BIN})"
    for _k in "${OPT_KEYS[@]}"; do
        if opt_is_installed "${_k}"; then
            echo "  ${GRN}  ✔${RST}  ${OPT_LABEL[${_k}]}  (${OPT_BIN[${_k}]})"
        fi
    done
    echo
    if [[ "${LEGACY}" == "true" ]]; then
        MODE="update"
        info "Non-interactive: existing installation detected — defaulting to 'update' (config preserved, services restarted)"
    fi
elif [[ "${LEGACY}" == "true" ]]; then
    info "No existing installation found — proceeding with fresh install"
    MODE="install"
    _suite_list="Dashboard, SysMon, wifimon, 44helper, Node Talker, Node Recorder and Pibrary"
    if [[ "${CORE}" == "true" ]]; then
        SUITE=false
        info "--core: the Dashboard, SysMon, wifimon and 44helper; the optional tools only when asked for"
    elif [[ "${SUITE}" == "true" ]]; then
        info "--suite: installing the whole suite (${_suite_list})"
    else
        SUITE=true
        info "Fresh node: installing the whole suite (${_suite_list}); --core installs only the core tools"
    fi
else
    info "No existing installation found"
fi

if [[ "${LEGACY}" != "true" ]]; then
    if [[ -z "${ACTION}" ]]; then
        echo
        show_menu
        if [[ "${RESET_ONLY}" == "true" ]]; then
            run_reset_only
        fi
    fi
    apply_action
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
if [[ ! -f "${INSTMON_BIN}" ]] && { [[ -z "${TOOLS_LIST}" ]] || tool_allowed instmon false; }; then
    hdr "instmon — file discovery"
    info "instmon is not installed — it will be installed too"
    CHOSEN=""
    fetch_if_missing "instmon" "instmon" false "instmon*.py" "" "${INSTMON_LIB_DIR}"
    stage_and_select "instmon*.py" "instmon" "${INSTMON_LIB_DIR}" || true
    INSTMON_CHOSEN="${CHOSEN}"
    if [[ -n "${INSTMON_CHOSEN}" ]]; then
        info "Checking syntax…"
        syntax_ok "${INSTMON_CHOSEN}" \
            || die "Syntax error in $(basename "${INSTMON_CHOSEN}") — install aborted"
        ok "Syntax OK"
    fi
fi

hdr "Dashboard — file discovery"
CHOSEN=""
PICKED_BUILD=""
if tool_allowed dashboard "${_dash_exists}"; then
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
fi
DASH_CHOSEN="${CHOSEN}"
[[ -z "${DASH_CHOSEN}" && -n "${PICKED_BUILD:-}" ]] && warn "No ${DASH_VARIANT} Dashboard build found -- set DASH_VARIANT=pi02w or =full to choose the other build."

if [[ -n "${DASH_CHOSEN}" ]]; then
    info "Checking syntax…"
    syntax_ok "${DASH_CHOSEN}" \
        || die "Syntax error in $(basename "${DASH_CHOSEN}") — install aborted"
    ok "Syntax OK"
fi

hdr "SysMon — file discovery"
CHOSEN=""
PICKED_BUILD=""
if tool_allowed sysmon "${_sysmon_exists}"; then
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
fi
SYSMON_CHOSEN="${CHOSEN}"
[[ -z "${SYSMON_CHOSEN}" && -n "${PICKED_BUILD:-}" ]] && warn "No ${SYSMON_VARIANT} SysMon build found -- set SYSMON_VARIANT=pi02w or =full to choose the other build."

if [[ -n "${SYSMON_CHOSEN}" ]]; then
    info "Checking syntax…"
    syntax_ok "${SYSMON_CHOSEN}" \
        || die "Syntax error in $(basename "${SYSMON_CHOSEN}") — install aborted"
    ok "Syntax OK"
fi

hdr "wifimon — file discovery"
CHOSEN=""
if tool_allowed wifimon "${_wifimon_exists}"; then
    fetch_if_missing "wifimon" "wifimon" "${_wifimon_exists}" "wifimon*.py" "" "${WIFIMON_LIB_DIR}" "" "${WIFIMON_BIN}"
    stage_and_select "wifimon*.py" "wifimon" "${WIFIMON_LIB_DIR}" || true
fi
WIFIMON_CHOSEN="${CHOSEN}"

if [[ -n "${WIFIMON_CHOSEN}" ]]; then
    info "Checking syntax…"
    syntax_ok "${WIFIMON_CHOSEN}" \
        || die "Syntax error in $(basename "${WIFIMON_CHOSEN}") — install aborted"
    ok "Syntax OK"
fi

hdr "44helper — file discovery"
CHOSEN=""
if tool_allowed 44helper "${_helper_exists}"; then
    fetch_if_missing "44helper" "44helper" "${_helper_exists}" "44helper*.py|asl_dvs_m17_44helper*.py" "" "${HELPER_LIB_DIR}" "" "${HELPER_BIN}"
    stage_and_select "44helper*.py|asl_dvs_m17_44helper*.py" "44helper" "${HELPER_LIB_DIR}" || true
fi
HELPER_CHOSEN="${CHOSEN}"

if [[ -n "${HELPER_CHOSEN}" ]]; then
    info "Checking syntax…"
    syntax_ok "${HELPER_CHOSEN}" \
        || die "Syntax error in $(basename "${HELPER_CHOSEN}") — install aborted"
    ok "Syntax OK"
fi

hdr "Node Talker — file discovery"
CHOSEN=""
_nl_want=true
if ! tool_allowed nodetalker "${_nodelisten_exists}"; then
    _nl_want=false
fi
if [[ "${_nl_want}" == "true" && "${_nodelisten_exists}" != "true" ]]; then
    if [[ "${DOWNLOAD}" != "true" ]] && ! any_file "${NODELISTEN_PATTERN}" "${NODELISTEN_LIB_DIR}"; then
        _nl_want=false
        info "No nodetalker*.py file found — Node Talker (optional) skipped"
    elif [[ "${NONINTERACTIVE}" == "true" || "${SUITE}" == "true" ]]; then
        if [[ "${SUITE}" == "true" ]]; then
            INSTALL_NODELISTEN=1
        fi
        if [[ "${INSTALL_NODELISTEN:-}" =~ ^([1yY]|yes|YES|true|TRUE)$ ]]; then
            info "INSTALL_NODETALKER or --suite is set — installing Node Talker"
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
    syntax_ok "${NODELISTEN_CHOSEN}" \
        || die "Syntax error in $(basename "${NODELISTEN_CHOSEN}") — install aborted"
    ok "Syntax OK"
fi

for _k in "${OPT_KEYS[@]}"; do
    if opt_is_installed "${_k}"; then
        _ex=true
    else
        _ex=false
    fi
    if tool_allowed "${_k}" "${_ex}"; then
        discover_optional "${_k}"
    else
        OPT_EXISTS["${_k}"]="${_ex}"
        OPT_CHOSEN["${_k}"]=""
    fi
done

if [[ ${#DOWNLOADED[@]} -gt 0 ]]; then
    hdr "Downloaded from GitHub"
    for _d in "${DOWNLOADED[@]}"; do ok "${_d}"; done
fi

if [[ -z "${INSTMON_CHOSEN}" && -z "${DASH_CHOSEN}" && -z "${SYSMON_CHOSEN}" \
      && -z "${WIFIMON_CHOSEN}" && -z "${HELPER_CHOSEN}" && -z "${NODELISTEN_CHOSEN}" ]] && ! opt_any_chosen; then
    if [[ "${DOWNLOAD}" != "true" ]]; then
        die "Nothing to install — no instmon, dashboard, sysmon, wifimon, 44helper, Node Talker, Node Recorder, Pibrary or Terminal Monitor files found (offline: nothing downloaded)."
    elif [[ "${FETCH_STATE}" == "failed" ]]; then
        die "Nothing to install — no files found here, and the download from GitHub failed."
    fi
    die "Nothing to install — no instmon, dashboard, sysmon, wifimon, 44helper, Node Talker, Node Recorder, Pibrary or Terminal Monitor files found."
fi

hdr "Up-to-date check"

downgrade_check "Dashboard" "${DASH_CHOSEN}" "${DASH_BIN}"
[[ "${UP_TO_DATE_SKIP}" == "true" ]] && DASH_CHOSEN=""
uptodate_check "Dashboard" "${DASH_CHOSEN}"    "${DASH_BIN}"
[[ "${UP_TO_DATE_SKIP}" == "true" ]] && DASH_CHOSEN=""

downgrade_check "SysMon" "${SYSMON_CHOSEN}" "${SYSMON_BIN}"
[[ "${UP_TO_DATE_SKIP}" == "true" ]] && SYSMON_CHOSEN=""
uptodate_check "SysMon"    "${SYSMON_CHOSEN}"  "${SYSMON_BIN}"
[[ "${UP_TO_DATE_SKIP}" == "true" ]] && SYSMON_CHOSEN=""

downgrade_check "wifimon" "${WIFIMON_CHOSEN}" "${WIFIMON_BIN}"
[[ "${UP_TO_DATE_SKIP}" == "true" ]] && WIFIMON_CHOSEN=""
uptodate_check "wifimon"   "${WIFIMON_CHOSEN}" "${WIFIMON_BIN}"
[[ "${UP_TO_DATE_SKIP}" == "true" ]] && WIFIMON_CHOSEN=""

downgrade_check "44helper" "${HELPER_CHOSEN}" "${HELPER_BIN}"
[[ "${UP_TO_DATE_SKIP}" == "true" ]] && HELPER_CHOSEN=""
uptodate_check "44helper"  "${HELPER_CHOSEN}"  "${HELPER_BIN}"
[[ "${UP_TO_DATE_SKIP}" == "true" ]] && HELPER_CHOSEN=""

downgrade_check "Node Talker" "${NODELISTEN_CHOSEN}" "${NODELISTEN_BIN}"
[[ "${UP_TO_DATE_SKIP}" == "true" ]] && NODELISTEN_CHOSEN=""
uptodate_check "Node Talker" "${NODELISTEN_CHOSEN}" "${NODELISTEN_BIN}"
[[ "${UP_TO_DATE_SKIP}" == "true" ]] && NODELISTEN_CHOSEN=""

for _k in "${OPT_KEYS[@]}"; do
    downgrade_check "${OPT_LABEL[${_k}]}" "${OPT_CHOSEN[${_k}]:-}" "${OPT_BIN[${_k}]}"
    if [[ "${UP_TO_DATE_SKIP}" == "true" ]]; then
        OPT_CHOSEN["${_k}"]=""
    fi
    uptodate_check "${OPT_LABEL[${_k}]}" "${OPT_CHOSEN[${_k}]:-}" "${OPT_BIN[${_k}]}"
    if [[ "${UP_TO_DATE_SKIP}" == "true" ]]; then
        OPT_CHOSEN["${_k}"]=""
    fi
done

if [[ -z "${INSTMON_CHOSEN}" && -z "${DASH_CHOSEN}" && -z "${SYSMON_CHOSEN}" \
      && -z "${WIFIMON_CHOSEN}" && -z "${HELPER_CHOSEN}" && -z "${NODELISTEN_CHOSEN}" ]] && ! opt_any_chosen; then
    ok "All selected files are already up to date — nothing to install."
    if [[ "${LEGACY}" != "true" ]]; then
        info "To restart the services and sign everyone out without installing, use --reset-only (or [5] in the menu)"
    fi
    exit 0
fi

if [[ "${LEGACY}" != "true" ]]; then
    confirm_plan
    backup_files
    if [[ "${STEP_D}" == "true" ]]; then
        reset_stop
    fi
fi

if [[ "${RESET_DONE}" == "true" ]]; then
    hdr "[E] Checks before each start"
    for _k in "${REG_KEYS[@]}"; do
        _c="$(reg_chosen "${_k}")"
        [[ -n "${_c}" ]] || continue
        if [[ -n "${HELD[$(reg_svc "${_k}")]+x}" ]]; then
            continue
        fi
        if ! health_check "${_k}" "${_c}"; then
            warn "$(reg_label "${_k}") is not installed this time; the installed copy is left as it was"
            reg_unchoose "${_k}"
        fi
    done
else
    hdr "Port checks"
    [[ -n "${INSTMON_CHOSEN}" ]] && { info "instmon port ${INSTMON_PORT}:"; check_port "${INSTMON_PORT}"; }
    [[ -n "${DASH_CHOSEN}"    ]] && { info "Dashboard port ${DASH_PORT}:"; check_port "${DASH_PORT}"; }
    [[ -n "${SYSMON_CHOSEN}"  ]] && { info "SysMon port ${SYSMON_PORT}:";  check_port "${SYSMON_PORT}"; }
    [[ -n "${HELPER_CHOSEN}"  ]] && { info "44helper port ${HELPER_PORT}:"; check_port "${HELPER_PORT}"; }
    if [[ -n "${NODELISTEN_CHOSEN}" && "${_nodelisten_exists}" != "true" ]]; then
        _nl_port="$(conf_port "${NODELISTEN_CONF}")"
        NODELISTEN_PORT="${_nl_port:-${NODELISTEN_PORT}}"
        info "Node Talker port ${NODELISTEN_PORT}:"; check_port "${NODELISTEN_PORT}"
    fi

    for _k in "${OPT_KEYS[@]}"; do
        if [[ -n "${OPT_CHOSEN[${_k}]:-}" && "${OPT_EXISTS[${_k}]:-false}" != "true" ]]; then
            info "${OPT_LABEL[${_k}]} port ${OPT_PORT[${_k}]}:"
            check_port "${OPT_PORT[${_k}]}"
        fi
    done
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

    _dash_svc0="${DASH_SERVICE}"
    hold_begin "${_dash_svc0}" "${_dash_exists}"
    info "Delegating to: python3 $(basename "${DASH_CHOSEN}") --install"
    python3 "${DASH_CHOSEN}" --install \
        || die "Dashboard --install failed — see output above"
    DASH_SERVICE="$(dash_service)"
    hold_end "${_dash_svc0}" "Dashboard" "${DASH_SERVICE}"
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

    hold_begin "${SYSMON_SERVICE}" "${_sysmon_exists}"
    info "Delegating to: python3 $(basename "${SYSMON_CHOSEN}") --install"
    python3 "${SYSMON_CHOSEN}" --install \
        || die "SysMon --install failed — see output above"
    ok "SysMon installed, enabled, and restarted"
    hold_end "${SYSMON_SERVICE}" "SysMon"
fi

if [[ -n "${WIFIMON_CHOSEN}" ]]; then
    hdr "Installing wifimon"
    hold_begin "${WIFIMON_SERVICE}" "${_wifimon_exists}"
    info "Delegating to: python3 $(basename "${WIFIMON_CHOSEN}") --install"
    python3 "${WIFIMON_CHOSEN}" --install \
        || die "wifimon --install failed — see output above"
    ok "wifimon installed, enabled, and restarted"
    hold_end "${WIFIMON_SERVICE}" "wifimon"
fi

if [[ -n "${HELPER_CHOSEN}" ]]; then
    hdr "Installing 44helper"
    hold_begin "${HELPER_SERVICE}" "${_helper_exists}"
    info "Delegating to: python3 $(basename "${HELPER_CHOSEN}") --install"
    python3 "${HELPER_CHOSEN}" --install \
        || die "44helper --install failed — see output above"
    ok "44helper installed, enabled, and restarted"
    hold_end "${HELPER_SERVICE}" "44helper"
fi

if [[ -n "${NODELISTEN_CHOSEN}" ]]; then
    hdr "Installing Node Talker"
    if [[ "${RESET_DONE}" == "true" ]] && small_pi; then
        sleep "${HEAVY_PAUSE}"
    fi
    if [[ "$(basename "${NODELISTEN_CHOSEN}")" == nodelisten* ]]; then
        NODELISTEN_SERVICE="nodelisten"
        if [[ -f /etc/systemd/system/nodetalker.service && -e /usr/local/bin/nodetalker.py ]]; then
            warn "$(basename "${NODELISTEN_CHOSEN}") is Node Listen, the older name: uninstalling Node Talker first so the two don't both run"
            python3 /usr/local/bin/nodetalker.py --uninstall \
                || die "Node Talker --uninstall failed — see output above"
        fi
    fi
    _nl_svc0="${NODELISTEN_SERVICE}"
    hold_begin "${_nl_svc0}" "${_nodelisten_exists}"
    info "Delegating to: python3 $(basename "${NODELISTEN_CHOSEN}") --install"
    python3 "${NODELISTEN_CHOSEN}" --install \
        || die "Node Talker --install failed — see output above"
    ok "Node Talker installed, enabled, and restarted"
    hold_end "${_nl_svc0}" "Node Talker" "${NODELISTEN_SERVICE}"
    for _nl_c in "${ASL_DVS_ETC}/nodetalker.conf" "${ASL_DVS_ETC}/nodelisten.conf"; do
        [[ -e "${_nl_c}" ]] && { NODELISTEN_CONF="${_nl_c}"; break; }
    done
    _nl_port="$(sed -n 's/^[[:space:]]*port[[:space:]]*=[[:space:]]*\([0-9]\{4,5\}\)[[:space:]]*$/\1/p' "${NODELISTEN_CONF}" 2>/dev/null | head -1 || true)"
    NODELISTEN_PORT="${_nl_port:-${NODELISTEN_PORT}}"
fi

for _k in "${OPT_KEYS[@]}"; do
    if [[ -z "${OPT_CHOSEN[${_k}]:-}" ]]; then
        continue
    fi
    _label="${OPT_LABEL[${_k}]}"
    hdr "Installing ${_label}"
    if [[ "${RESET_DONE}" == "true" ]] && is_heavy "${_k}" && small_pi; then
        sleep "${HEAVY_PAUSE}"
    fi
    hold_begin "${OPT_SERVICE[${_k}]}" "${OPT_EXISTS[${_k}]:-false}"
    info "Delegating to: python3 $(basename "${OPT_CHOSEN[${_k}]}") --install"
    python3 "${OPT_CHOSEN[${_k}]}" --install \
        || die "${_label} --install failed — see output above"
    ok "${_label} installed, enabled, and restarted"
    hold_end "${OPT_SERVICE[${_k}]}" "${_label}"
    if [[ "${_k}" == "termon" ]]; then
        _tm_port="$(sed -n 's/^[[:space:]]*port[[:space:]]*=[[:space:]]*\([0-9]\{4,5\}\)[[:space:]]*$/\1/p' "${ASL_DVS_ETC}/termon.conf" 2>/dev/null | head -1 || true)"
        OPT_PORT["termon"]="${_tm_port:-${OPT_PORT[termon]}}"
    fi
done

if [[ "${LEGACY}" != "true" && "${STEP_C}" == "true" ]]; then
    manuals_install
fi

start_verify

hdr "Access URLs"

HOSTNAME_SHORT="$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo raspberrypi)"
HOSTNAME_FQDN="$(hostname -f 2>/dev/null || echo "")"

mapfile -t IP_ADDRS < <(
    ip -4 addr show 2>/dev/null \
    | awk '/inet / && !/127\.0\.0\.1/ {gsub(/\/.*/, "", $2); print $2}' \
    || hostname -I 2>/dev/null | tr ' ' '\n' | grep -v '^$' | grep -v '^127\.'
)

print_urls() {
    local name="$1" port="$2" chosen="$3" scheme="${4:-http}"
    [[ -z "${chosen}" ]] && return
    echo
    echo "  ${BLD}${name}${RST}  ($(basename "${chosen}"))"
    sep
    echo "  Hostname  :  ${scheme}://${HOSTNAME_SHORT}.local:${port}"
    [[ -n "${HOSTNAME_FQDN}" && "${HOSTNAME_FQDN}" != "${HOSTNAME_SHORT}" ]] && \
        echo "  FQDN      :  ${scheme}://${HOSTNAME_FQDN}:${port}"
    if [[ "${#IP_ADDRS[@]}" -gt 0 ]]; then
        for ip in "${IP_ADDRS[@]}"; do
            echo "  Network   :  ${BLD}${GRN}${scheme}://${ip}:${port}${RST}"
        done
    else
        warn "Could not determine IP — check: hostname -I"
    fi
    echo "  Localhost :  ${scheme}://localhost:${port}"
    sep
}

print_urls "instmon"                             "${INSTMON_PORT}" "${INSTMON_CHOSEN}"
print_urls "Node Control Dashboard"           "${DASH_PORT}"    "${DASH_CHOSEN}"
print_urls "System Monitor"                   "${SYSMON_PORT}"  "${SYSMON_CHOSEN}"
print_urls "44Net Helper"                        "${HELPER_PORT}"  "${HELPER_CHOSEN}"
print_urls "wifimon"                             "${WIFIMON_PORT}" "${WIFIMON_CHOSEN}"
print_urls "Node Talker"                         "${NODELISTEN_PORT}" "${NODELISTEN_CHOSEN}"
for _k in "${OPT_KEYS[@]}"; do
    print_urls "${OPT_LABEL[${_k}]}" "${OPT_PORT[${_k}]}" "${OPT_CHOSEN[${_k}]:-}" "${OPT_SCHEME[${_k}]}"
done

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
for _k in "${OPT_KEYS[@]}"; do
    [[ -n "${OPT_CHOSEN[${_k}]:-}" ]] && echo "    ${OPT_LABEL[${_k}]}  :  systemctl {status|restart|stop} ${OPT_SERVICE[${_k}]}"
done
echo "    Logs      :  journalctl -u <service> -f"
echo
if [[ "${LEGACY}" != "true" ]]; then
    for _k in "${!HC_HELD[@]}"; do
        warn "Held, not started: $(reg_label "${_k}") — ${HC_HELD[${_k}]}"
    done
    if [[ ${#F_FAILED[@]} -gt 0 ]]; then
        warn "Did not start: ${F_FAILED[*]} (see the log lines above)"
    fi
    if [[ "${RESET_DONE}" == "true" ]]; then
        info "Everyone was signed out: sign in again on each page"
    fi
    echo
fi
