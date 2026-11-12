#!/usr/bin/env bash
# bootstrap.sh  v1.0.0  (2026-11-12)

set -euo pipefail

main() {
    local repo channel raw lib min work file="" rev="main" commit="" blob="" entry dest got
    repo="${ASL_DVS_REPO:-kd8pgk/ASL-DVS}"
    channel="${ASL_DVS_CHANNEL:-stable}"
    raw="${ASL_DVS_RAW_URL:-https://raw.githubusercontent.com/${repo}}"
    lib="${INSTMON_LIBRARY_DIR:-/etc/asl_dvs/instmon_library}"
    min="7.6.0"

    say()  { echo "  → $*"; }
    fail() { echo "  ✘ $*" >&2; exit 1; }

    case "${channel,,}" in
        stable) channel="stable" ;;
        testing|main) channel="testing" ;;
        *) fail "ASL_DVS_CHANNEL must be stable or testing (got '${channel}')" ;;
    esac

    if [[ "${EUID}" -ne 0 ]]; then
        fail "Must be run as root.  Use: curl -fsSL ${raw}/main/bootstrap.sh | sudo bash"
    fi

    if command -v curl &>/dev/null; then
        fetch() { curl -fsSL --retry 2 -o "$2" "$1"; }
    elif command -v wget &>/dev/null; then
        fetch() { wget -q -O "$2" "$1"; }
    else
        fail "curl or wget is needed.  Install one with: apt install curl"
    fi

    work="$(mktemp -d /tmp/asl_dvs_bootstrap.XXXXXX)"
    trap "rm -rf -- '${work}'" EXIT

    echo
    echo "══ Node Controller bootstrap"
    say "Repository: ${repo} (${channel} channel)"

    if [[ "${channel}" == "stable" ]] && fetch "${raw}/main/channels/stable.json" "${work}/stable.json" 2>/dev/null; then
        entry="$(tr -d '\n\r\t ' < "${work}/stable.json" | grep -o '"install_all":{[^}]*}' | head -1 || true)"
        file="$(printf '%s' "${entry}" | sed -n 's/.*"file":"\([A-Za-z0-9._-]*\)".*/\1/p')"
        commit="$(printf '%s' "${entry}" | sed -n 's/.*"commit":"\([0-9a-f]*\)".*/\1/p')"
        blob="$(printf '%s' "${entry}" | sed -n 's/.*"blob":"\([0-9a-f]*\)".*/\1/p')"
        if [[ ! "${file}" =~ ^install_all_v[0-9_]+\.sh$ || ! "${commit}" =~ ^[0-9a-f]{40}([0-9a-f]{24})?$ ]]; then
            file=""
        else
            got="$(printf '%s' "${file}" | sed -E 's/^install_all_v([0-9]+)_([0-9]+)_([0-9]+).*/\1.\2.\3/')"
            if [[ "$(printf '%s\n%s\n' "${min}" "${got}" | sort -V | head -1)" != "${min}" ]]; then
                say "The stable installer (${got}) is older than ${min}, the first that installs the whole suite — using the newest"
                file=""
            else
                rev="${commit}"
            fi
        fi
    fi

    if [[ -z "${file}" ]]; then
        rev="main"
        blob=""
        fetch "${raw}/main/README.md" "${work}/README.md" 2>/dev/null \
            || fail "Could not reach ${raw} — check the network and try again"
        file="$(grep -o 'install_all_v[0-9_]*\.sh' "${work}/README.md" | sort -V | tail -1 || true)"
        [[ -n "${file}" ]] || fail "No installer is named in the repository's README"
    fi

    say "Downloading ${file}"
    fetch "${raw}/${rev}/${file}" "${work}/${file}" 2>/dev/null \
        || fail "Download of ${file} failed"
    if [[ "$(head -c 2 "${work}/${file}")" != "#!" ]] || ! sed -n '2p' "${work}/${file}" | grep -q '^# install_all\.sh  *v[0-9]'; then
        fail "${file} is not an installer — not run"
    fi
    if [[ ${#blob} -eq 40 ]] && command -v sha1sum &>/dev/null; then
        got="$( { printf 'blob %s\0' "$(wc -c < "${work}/${file}" | tr -d ' ')"; cat "${work}/${file}"; } | sha1sum | cut -d' ' -f1)"
        [[ "${got}" == "${blob}" ]] || fail "${file} does not match the stable list — not run"
    fi
    bash -n "${work}/${file}" || fail "${file} failed the syntax check — not run"

    dest="${work}/${file}"
    if mkdir -p "${lib}/scripts" 2>/dev/null && cp -- "${work}/${file}" "${lib}/scripts/${file}" 2>/dev/null; then
        chmod 644 "${lib}/scripts/${file}"
        dest="${lib}/scripts/${file}"
        say "Saved to ${dest}"
    fi

    say "Starting the installer"
    if [[ ! -t 0 ]] && { : < /dev/tty; } 2>/dev/null; then
        bash "${dest}" "$@" < /dev/tty
    else
        bash "${dest}" "$@"
    fi
}

main "$@"
