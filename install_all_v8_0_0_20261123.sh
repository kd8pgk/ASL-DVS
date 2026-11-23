#!/usr/bin/env bash
# install_all.sh  v8.0.0  (2026-11-23)

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

[[ "${EUID}" -eq 0 ]] || die "Run with sudo: sudo bash $(basename "$0")"

NONINTERACTIVE=false
DOWNLOAD=true
BUILD_ARG=""
for _arg in "$@"; do
    case "${_arg}" in
        --non-interactive|--auto|-y) NONINTERACTIVE=true ;;
        --offline|--no-download) DOWNLOAD=false ;;
        --build=*) BUILD_ARG="${_arg#*=}" ;;
        --core|--no-manuals|--with-termon|--reset|--no-reset|--reset-only|--download-only|--action=*|--tools=*|--steps=*)
            warn "${_arg} is no longer used by the installer; it is ignored" ;;
        *) die "Unknown option '${_arg}'. Use --build=pi02w or --build=full, --offline, or --non-interactive." ;;
    esac
done
if [[ ! -t 0 ]]; then
    NONINTERACTIVE=true
fi
BUILD_ARG="${BUILD_ARG,,}"
case "${BUILD_ARG}" in
    ""|pi02w|full) ;;
    *) die "--build must be pi02w or full (got '${BUILD_ARG}')" ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASL_DVS_ETC="${ASL_DVS_ETC:-/etc/asl_dvs}"
INSTMON_LIBRARY_DIR="${INSTMON_LIBRARY_DIR:-${ASL_DVS_ETC}/instmon_library}"
MODEL_FILE="${ASL_DVS_MODEL_FILE:-/proc/device-tree/model}"
GH_REPO="${ASL_DVS_REPO:-kd8pgk/ASL-DVS}"
GH_CHANNEL="${ASL_DVS_CHANNEL:-stable}"
case "${GH_CHANNEL}" in
    stable) GH_CHANNEL="stable" ;;
    testing|main) GH_CHANNEL="testing" ;;
    *) die "ASL_DVS_CHANNEL must be stable or testing" ;;
esac
STRICT_STABLE=false
FETCH_DIR=""
FETCH_REPO=""
FETCH_STATE=""
FETCHED_FILE=""
DOWNLOADED=()
trap '[[ -n "${FETCH_DIR}" ]] && rm -rf -- "${FETCH_DIR}"' EXIT

is_zero2() {
    tr -d '\0' 2>/dev/null < "${MODEL_FILE}" | grep -qi 'Zero 2'
}

if [[ -n "${BUILD_ARG}" ]]; then
    BUILD="${BUILD_ARG}"
    BUILD_WHY="from --build"
elif is_zero2; then
    BUILD="pi02w"
    BUILD_WHY="this Pi is a Zero 2 W"
else
    BUILD="full"
    BUILD_WHY="this Pi is not a Zero 2 W"
fi

ensure_git() {
    command -v git >/dev/null 2>&1 && return 0
    info "Installing git (needed to download from GitHub)…"
    if DEBIAN_FRONTEND=noninteractive apt-get install -y -q git >/dev/null 2>&1; then
        ok "git installed"
        return 0
    fi
    warn "git could not be installed"
    return 1
}

locate_newest() {
    local pattern="$1" lib_dir="$2" d hit
    for d in "${SCRIPT_DIR}" "${lib_dir}"; do
        [[ -d "${d}" ]] || continue
        hit="$(find "${d}" -maxdepth 1 -type f -name "${pattern}" -print 2>/dev/null | sort -V | tail -1)"
        if [[ -n "${hit}" ]]; then
            echo "${hit}"
            return 0
        fi
    done
    return 1
}

seed_identity() {
    local cs="" nd="" lbl="" line
    if [[ -f "${DASH_CONF}" && -f "${SYSMON_CONF_DIR}/sysmon.conf" ]]; then
        ok "Callsign and node already set: config kept"
        return 0
    fi
    if [[ -n "${AUTO_CALLSIGN:-}" && -n "${AUTO_NODE:-}" ]]; then
        cs="${AUTO_CALLSIGN^^}"
        cs="${cs//[^A-Z0-9\/\-\.]/}"
        cs="${cs:0:9}"
        nd="${AUTO_NODE//[^0-9]/}"
        lbl="${AUTO_LABEL:-AllStarLink Node}"
        lbl="${lbl:0:40}"
    elif [[ "${NONINTERACTIVE}" != "true" ]]; then
        while true; do
            read -r -p "  Callsign (e.g. KD8PGK), or Enter to set it later in the Dashboard: " line </dev/tty
            [[ -z "${line}" ]] && break
            line="${line^^}"
            if [[ "${line}" =~ ^[A-Z0-9/.-]{3,9}$ ]]; then cs="${line}"; break; fi
            warn "Use 3 to 9 letters, digits, / . or -"
        done
        if [[ -n "${cs}" ]]; then
            while true; do
                read -r -p "  ASL node number (digits only, e.g. 652701): " line </dev/tty
                [[ -z "${line}" ]] && break
                if [[ "${line}" =~ ^[0-9]{1,8}$ ]]; then nd="${line}"; break; fi
                warn "Digits only"
            done
            lbl="AllStarLink Node"
        fi
    fi
    if [[ -z "${cs}" || -z "${nd}" ]]; then
        warn "No callsign or node number set: set them in the Dashboard's Config tab"
        return 0
    fi
    mkdir -p "${ASL_DVS_ETC}" "${SYSMON_CONF_DIR}"
    if [[ ! -f "${DASH_CONF}" ]]; then
        printf '# asl_dvs.conf — seed config written by installer\n[CONFIG]\nasl_node=%s\ncallsign=%s\n' "${nd}" "${cs}" > "${DASH_CONF}"
        ok "Seed config written: ${DASH_CONF}"
    fi
    if [[ ! -f "${SYSMON_CONF_DIR}/sysmon.conf" ]]; then
        printf '# sysmon.conf — seed config written by installer\n[identity]\ncallsign = %s\nnode = %s\nlabel = %s\n' "${cs}" "${nd}" "${lbl}" > "${SYSMON_CONF_DIR}/sysmon.conf"
        ok "Seed config written: ${SYSMON_CONF_DIR}/sysmon.conf"
    fi
}

TOOL_KEY=()
TOOL_LABEL=()
TOOL_PAT=()
TOOL_LIB=()
TOOL_PORT=()
TOOL_BUILD=()
add_tool() {
    TOOL_KEY+=("$1"); TOOL_LABEL+=("$2"); TOOL_PAT+=("$3")
    TOOL_LIB+=("${INSTMON_LIBRARY_DIR}/$4"); TOOL_PORT+=("$5"); TOOL_BUILD+=("$6")
}
if [[ "${BUILD}" == "pi02w" ]]; then
    DASH_PAT="nodecontrol_pi02w_v*.py"; SYSMON_PAT="sysmon_pi02w_v*.py"
else
    DASH_PAT="nodecontrol_v[0-9]*.py"; SYSMON_PAT="sysmon_v[0-9]*.py"
fi
add_tool instmon        "instmon"         "instmon*.py"         instmon        8990 ""
add_tool dashboard      "Dashboard"       "${DASH_PAT}"         dashboard      8989 "${BUILD}"
add_tool sysmon         "SysMon"          "${SYSMON_PAT}"       sysmon         9999 "${BUILD}"
add_tool wifimon        "wifimon"         "wifimon*.py"         wifimon        8991 ""
add_tool 44helper       "44helper"        "44helper*.py"        44helper       9997 ""
add_tool nodetalker     "Node Talker"     "nodetalker_v*.py"    nodetalker     8993 ""
add_tool noderecorder   "Node Recorder"   "noderecorder_v*.py"  noderecorder   8995 ""
add_tool nodemon        "Node Monitor"    "nodemon_v*.py"       nodemon        7777 ""
add_tool pibrary        "Pibrary"         "pibrary_v*.py"       pibrary        9000 ""
add_tool termon         "Terminal Monitor" "termon_v*.py"       termon         7878 ""
add_tool piper_dashboard "Pi-Piper TTS"   "piper_dashboard_v*.py" piper_dashboard 8765 ""

hdr "Install ASL-DVS suite"
info "Build: ${BUILD} (${BUILD_WHY})"

hdr "Directories"
SYSMON_CONF_DIR="${SYSMON_CONF_DIR:-/etc/sysmon}"
for _d in "${ASL_DVS_ETC}" "${SYSMON_CONF_DIR}" "${INSTMON_LIBRARY_DIR}"; do
    mkdir -p "${_d}" && ok "${_d}"
done
for _i in "${!TOOL_KEY[@]}"; do
    mkdir -p "${TOOL_LIB[${_i}]}" && ok "${TOOL_LIB[${_i}]}"
done


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

TOOL_FILE=()
for _i in "${!TOOL_KEY[@]}"; do TOOL_FILE+=(""); done
FAILED=()
NEED=()

hdr "Files"
for _i in "${!TOOL_KEY[@]}"; do
    _label="${TOOL_LABEL[${_i}]}"
    if _f="$(locate_newest "${TOOL_PAT[${_i}]}" "${TOOL_LIB[${_i}]}")"; then
        if [[ "${_f}" == *.py ]] && ! python3 -I -c 'import sys; compile(open(sys.argv[1],"rb").read(), sys.argv[1], "exec")' "${_f}" 2>/dev/null; then
            warn "${_label}: $(basename "${_f}") failed the syntax check"
            FAILED+=("${_label}")
        else
            TOOL_FILE[${_i}]="${_f}"
            ok "${_label}: $(basename "${_f}")"
        fi
    else
        NEED+=("${_i}")
    fi
done

if [[ ${#NEED[@]} -gt 0 ]]; then
    if [[ "${DOWNLOAD}" != "true" ]]; then
        for _i in "${NEED[@]}"; do
            warn "${TOOL_LABEL[${_i}]}: no file found and --offline is set"
            FAILED+=("${TOOL_LABEL[${_i}]}")
        done
    else
        hdr "Downloading from GitHub (${GH_CHANNEL})"
        if ensure_git && open_repo; then
            for _i in "${NEED[@]}"; do
                if fetch_tool "${TOOL_KEY[${_i}]}" "${TOOL_LABEL[${_i}]}" "${TOOL_PAT[${_i}]}" "" "${TOOL_LIB[${_i}]}" "${TOOL_BUILD[${_i}]}" && [[ -n "${FETCHED_FILE}" ]]; then
                    TOOL_FILE[${_i}]="${FETCHED_FILE}"
                else
                    warn "${TOOL_LABEL[${_i}]}: not downloaded"
                    FAILED+=("${TOOL_LABEL[${_i}]}")
                fi
            done
        else
            for _i in "${NEED[@]}"; do
                warn "${TOOL_LABEL[${_i}]}: GitHub is not reachable, so it was not downloaded"
                FAILED+=("${TOOL_LABEL[${_i}]}")
            done
        fi
    fi
fi

DASH_CONF="${ASL_DVS_ETC}/asl_dvs.conf"
hdr "Callsign and node"
seed_identity

INSTALLED=()
hdr "Installing"
for _i in "${!TOOL_KEY[@]}"; do
    _f="${TOOL_FILE[${_i}]}"
    [[ -n "${_f}" ]] || continue
    _label="${TOOL_LABEL[${_i}]}"
    info "${_label}: python3 $(basename "${_f}") --install"
    if python3 "${_f}" --install; then
        ok "${_label} installed"
        INSTALLED+=("${_i}")
    else
        warn "${_label} --install failed — see the output above"
        FAILED+=("${_label}")
    fi
done

hdr "Firewall"
FW=""
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
    FW="ufw"
elif command -v firewall-cmd >/dev/null 2>&1 && [[ "$(firewall-cmd --state 2>/dev/null || true)" == "running" ]]; then
    FW="firewalld"
fi
if [[ "${FW}" == "ufw" ]]; then
    info "ufw is active: opening the suite ports"
    for _i in "${INSTALLED[@]+"${INSTALLED[@]}"}"; do
        if ufw allow "${TOOL_PORT[${_i}]}/tcp" >/dev/null 2>&1; then
            ok "ufw: ${TOOL_PORT[${_i}]}/tcp (${TOOL_LABEL[${_i}]})"
        else
            warn "ufw: could not open ${TOOL_PORT[${_i}]}/tcp"
        fi
    done
elif [[ "${FW}" == "firewalld" ]]; then
    _zone="$(firewall-cmd --get-default-zone)"
    info "firewalld is running: opening the suite ports in zone ${_zone}"
    for _i in "${INSTALLED[@]+"${INSTALLED[@]}"}"; do
        if firewall-cmd --permanent --zone="${_zone}" --add-port="${TOOL_PORT[${_i}]}/tcp" >/dev/null 2>&1; then
            ok "firewalld: ${TOOL_PORT[${_i}]}/tcp (${TOOL_LABEL[${_i}]})"
        else
            warn "firewalld: could not open ${TOOL_PORT[${_i}]}/tcp"
            FAILED+=("firewall ${TOOL_PORT[${_i}]}")
        fi
    done
    firewall-cmd --reload >/dev/null 2>&1 && ok "firewalld reloaded (ports are kept after a reboot)"
else
    warn "No firewall is running (neither ufw nor firewalld), so no ports were opened"
fi

hdr "Scripts for your home folder"
HOME_USER="${SUDO_USER:-root}"
HOME_DIR="$(getent passwd "${HOME_USER}" 2>/dev/null | cut -d: -f6 || true)"
if [[ -z "${HOME_DIR}" || ! -d "${HOME_DIR}" ]]; then
    HOME_USER="root"
    HOME_DIR="/root"
fi
HOME_DIR="${ASL_DVS_HOME_DIR:-${HOME_DIR}}"
[[ "${DOWNLOAD}" == "true" ]] && { ensure_git && open_repo || true; }
for _spec in "wifi_menu|wifi_menu_v3_1_20261011.sh|wifi_menu*.sh" "tunnel_remove|tunnel_remove_v1_0_0_20261123.sh|tunnel_remove*.sh"; do
    IFS='|' read -r _key _name _pat <<< "${_spec}"
    if [[ -f "${SCRIPT_DIR}/${_name}" ]]; then
        _src="${SCRIPT_DIR}/${_name}"
    elif [[ "${DOWNLOAD}" == "true" && -n "${FETCH_REPO}" ]] && fetch_tool "${_key}" "${_key}" "${_pat}" "" "${ASL_DVS_ETC}/scripts" "" && [[ -n "${FETCHED_FILE}" ]]; then
        _src="${FETCHED_FILE}"
    else
        warn "${_name} not found — not copied to ${HOME_DIR}"
        FAILED+=("${_name}")
        continue
    fi
    install -m 755 -o "${HOME_USER}" -g "$(id -gn "${HOME_USER}" 2>/dev/null || echo root)" "${_src}" "${HOME_DIR}/$(basename "${_src}")"
    ok "${HOME_DIR}/$(basename "${_src}")"
done

hdr "Done"
if [[ ${#INSTALLED[@]} -gt 0 ]]; then
    ok "${#INSTALLED[@]} tool(s) installed"
fi
if [[ ${#FAILED[@]} -gt 0 ]]; then
    warn "Not finished: ${FAILED[*]}"
    exit 1
fi
ok "The ASL-DVS suite is installed"
