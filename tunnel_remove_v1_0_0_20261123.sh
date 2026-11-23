#!/usr/bin/env bash
# tunnel_remove.sh  v1.0.0  (2026-11-23)

set -uo pipefail

[[ "${EUID}" -eq 0 ]] || { echo "Run with sudo: sudo bash $(basename "$0")" >&2; exit 1; }

for unit in wg-quick@wg0.service 44net-tunnel.service; do
    systemctl stop "${unit}" >/dev/null 2>&1 || true
    systemctl disable "${unit}" >/dev/null 2>&1 || true
done

if ip link show wg0 >/dev/null 2>&1; then
    wg-quick down wg0 >/dev/null 2>&1 || ip link delete wg0 >/dev/null 2>&1 || true
fi

echo "Tunnel stopped and disabled. /etc/wireguard/wg0.conf was kept, so it can be started again."
