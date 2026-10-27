# Config getter (confgetter) changelog

Current file: `confgetter_v1_0_0_20261027.sh`. Newest entries first.

## 1.0.0 (2026-10-27)

- **New tool.** `confgetter.sh` gathers the node's config into one Markdown
  file to hand to Claude for finding errors and for building a standard
  full-system config. It reads and never changes anything.
- **What it copies:** Asterisk / ASL3 (stock files that still match the
  package default are listed but not copied), Allmon3, DVSwitch
  (Analog_Bridge, MMDVM_Bridge and the gateways), USRP2M17, SvxLink, the
  Node Controller tools' config, firewalld zones and services, WireGuard /
  44Net Connect, sysctl, fail2ban and sshd drop-ins, network and Wi-Fi
  settings, plus the units of the stack (`systemctl cat`).
- **Command output:** OS and uptime, disk and memory, failed units, package
  versions, firewall rules, `wg show`, addresses, routes and policy rules,
  the Asterisk version and local nodes, and the version of each installed
  tool.
- **Secrets stay on the node.** Passwords, keys, tokens and secrets are
  replaced with `<redacted:xxxxxxxx>`, a hash salted per snapshot, so the
  same value gives the same tag inside one file. There is no option to keep
  them. Secret files (`local_api.key`, Ampersand `auth.txt`, cloudflared
  credentials, key files, `/etc/shadow` and the like) are never copied. A
  symlink that points outside the config folders is not followed.
- **Limits:** files over 200 KB are cut, binaries are skipped, and the
  snapshot stays under 1.5 MB. The newest 10 snapshots are kept.
- **Output:** `confgetter_<host>_<YYYYmmdd-HHMMSS>.md`, mode 0600, in
  `/etc/asl_dvs/instmon_library/snapshots` (or `--out DIR`); `--keep N`
  sets how many are kept. instmon runs it from its Config getter card.
