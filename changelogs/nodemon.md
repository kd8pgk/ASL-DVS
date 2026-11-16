# Node Monitor (nodemon) changelog

Current file: `nodemon_v0_1_0_20261116.py`. Newest entries first.

## 0.1.0 (2026-11-16)

- **New tool.** Node Monitor is an Allmon3-style status page for the node, in Node Controller's look. It is read-only in this version. It stands alone for now: the installer and instmon do not know it yet, so install it with `sudo python3 nodemon_v0_1_0_20261116.py --install`.
- **Port 7777**, plain HTTP, LAN only. Log in with the root password. Sessions follow the common standard model (12 hours idle).
- **Main node tab:** whether the node is up and loaded in Asterisk, its **ASL3 registration** (from `rpt show registrations`), and every link on the node with its state, mode (transceive or monitor), direction and time connected.
- **Connections tab:** the main node's links in one table, and a table of the gateways.
- **Private nodes tab:** one card for each private node (1000 to 1999) in rpt.conf, with its links and, for the bridge nodes, what the gateway behind it is tuned to. A node that is in rpt.conf but not loaded in Asterisk says so.
- **Log tab:** Node Monitor's own events.
- **Link state comes from Asterisk's manager interface (AMI).** It reads the login from `/etc/asterisk/manager.conf` and polls the loaded nodes, the registrations and each node's links every 3 seconds (`poll_sec` in `/etc/asl_dvs/nodemon.conf`, 1 to 30). If Asterisk cannot be read, the page says so and shows nothing as connected.
- **Gateways are read from their own status, never guessed.** DVSwitch from Analog_Bridge's status file (`/tmp/ABInfo_*.json`), M17 from USRP2M17's settings and its unit, SvxLink from its log (reflector login, selected talkgroup, link on or off). When a source cannot be read the row says "unknown", not "not connected".
- **Nodes** are told apart by the USRP ports in rpt.conf: 34001 DVSwitch, 34008 M17, 34000 SvxLink, 34018 Node Talker's transmit node.
- Settings in `/etc/asl_dvs/nodemon.conf`: `port`, `poll_sec`, `allow_wan` (off) and `main_node` (blank: the first public node in rpt.conf).
- Not in this version: link commands (the drop-down menus), the installer and instmon entries, and HTTPS.
