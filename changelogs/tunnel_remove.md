# tunnel_remove changelog

Current file: `tunnel_remove_v1_0_0_20261123.sh`. Newest entries first.

## 1.0.0 (2026-11-23)

A new tool. It stops and disables the 44Net tunnel and leaves `/etc/wireguard/wg0.conf` in place, so the tunnel can be started again. It is copied into your home folder by the suite installer.

- It stops `wg-quick@wg0.service` and `44net-tunnel.service`, disables both, and brings the `wg0` interface down.
- It needs root (sudo).
