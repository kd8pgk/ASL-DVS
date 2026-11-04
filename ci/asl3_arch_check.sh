#!/usr/bin/env bash
set -u

BASE="${ASL3_REPO:-https://repo.allstarlink.org/repository}"
PKGS="asl3-appliance asl3-appliance-pc asl3-appliance-pi asl3-pi-appliance asl3-asterisk app_rpt"
SUITES="${ASL3_SUITES:-trixie bookworm}"
ARCHES="${ASL3_ARCHES:-arm64 amd64}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fetch_index() {
    local url="$1" out="$2"
    if curl -fsS --max-time 60 -o "$out.raw" "$url" 2>/dev/null; then
        case "$url" in
            *.xz)  xz -dc "$out.raw" > "$out" ;;
            *.gz)  gzip -dc "$out.raw" > "$out" ;;
            *)     mv "$out.raw" "$out" ;;
        esac
        rm -f "$out.raw"
        return 0
    fi
    return 1
}

status=0
printf '%-10s %-8s %-22s %-6s %s\n' SUITE ARCH PACKAGE ARCH VERSION
for suite in $SUITES; do
    for arch in $ARCHES; do
        idx="$TMP/$suite-$arch.Packages"
        got=0
        for url in \
            "$BASE/asl3-debian-$suite/dists/$suite/main/binary-$arch/Packages.gz" \
            "$BASE/asl3-debian-$suite/dists/$suite/main/binary-$arch/Packages.xz" \
            "$BASE/asl3-debian-$suite/dists/$suite/main/binary-$arch/Packages"; do
            if fetch_index "$url" "$idx"; then got=1; break; fi
        done
        if [ "$got" -ne 1 ]; then
            printf '%-10s %-8s %s\n' "$suite" "$arch" "NO INDEX (repo unreachable, or path differs: set ASL3_REPO)"
            status=1
            continue
        fi
        for pkg in $PKGS; do
            awk -v want="$pkg" -v s="$suite" -v a="$arch" '
                /^Package: /      { name = substr($0, 10); arch_p = ""; ver = "" }
                /^Architecture: /  { arch_p = substr($0, 15) }
                /^Version: /       { ver = substr($0, 10) }
                /^$/ {
                    if (name == want) { printf "%-10s %-8s %-22s %-6s %s\n", s, a, name, arch_p, ver; found = 1 }
                    name = ""
                }
                END {
                    if (name == want) { printf "%-10s %-8s %-22s %-6s %s\n", s, a, name, arch_p, ver; found = 1 }
                    if (!found) printf "%-10s %-8s %-22s %-6s %s\n", s, a, want, "-", "not published"
                }' "$idx"
        done
    done
done
exit "$status"
