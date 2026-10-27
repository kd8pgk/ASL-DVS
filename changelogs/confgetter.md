# Config getter (confgetter) changelog

Current file: `confgetter_v1_0_2_20261027.sh`. Newest entries first.

## 1.0.2 (2026-10-27)

- **DMR server passwords are redacted.** 1.0.1 only handled the pipe lists
  that have a `name|password|...` header line. The `[DMR_SERVERS]` section
  of the Node Talker and DVSwitch files has no such header, so its passwords
  (the second column) were still in the snapshot. Any section whose name
  contains "server" now has its second column redacted.

## 1.0.1 (2026-10-27)

- **Passwords in pipe-separated lists are redacted.** The DMR server lists
  (`name|password|address:port|url`) in the Node Talker and DVSwitch files
  kept their passwords in 1.0.0. The password column is now replaced under
  the list's header line; the rest of the line is kept.
- **Email addresses are redacted** wherever they appear, including the
  `"email"` key in the Node Talker JSON files.
- **MAC addresses are partly masked:** the first three octets stay (the
  vendor part), the last three become `xx:xx:xx`.
- The check count in the snapshot header counts these too.

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
