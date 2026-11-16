# Node Monitor (nodemon) changelog

Current file: `nodemon_v0_3_0_20261116.py`. Newest entries first.

## 0.3.0 (2026-11-16)

A **System** bar at the bottom of the page, like Node Controller's: Disconnect All, Reboot and Shutdown. This is a release: there are three new actions.

- **Disconnect All** drops every link on the main node (ilink 6) and asks first. If Node Talker's transmit node (the one on USRP port 34018, 1921 by default) was linked, it is linked again a second later, as Node Controller does, so Node Talker keeps working. It does not restart any service, unlike Node Controller's Disconnect All; the Command row's "Disconnect all links" does the same without the relinking.
- **Reboot** and **Shutdown** ask first, then run `reboot` or `shutdown -h now` a second after the reply is sent, as Node Recorder does. They need root, and are logged with the address that asked.
- **When the node goes away** the page now says "Node Monitor is not answering" and keeps trying, instead of staying frozen.
- The three buttons need the login and the same guards as every other action.

## 0.2.0 (2026-11-16)

Link commands. Every node card (the main node and each private node that is up) now has a **Command** row of drop-down menus.

- **Every ilink operation of rpt.conf is offered**, in groups, with plain labels:
  - **Connect:** transceive (3), monitor only (2), local monitor only (8).
  - **Disconnect:** a link (1), all links (6), reconnect the links dropped by Disconnect all (16).
  - **Permanent links:** transceive (13), monitor only (12), local monitor only (18), disconnect a permanent link (11).
  - **Other:** enter command mode on a link (4), send a text message to a node or, with 0, to all links (9).
  - **Announce on the air:** system status (5), last node to key up (7), full system status (15), MDC test (17). These make the node transmit, so they ask first.
  - ilink 10 is left out: rpt.conf marks it as unused.
- **The node to link** is typed or picked from a list of the nodes already linked and the other nodes on this server.
- **Asks first** for Disconnect all, the permanent-link commands and the ones that transmit on the air.
- **The result is the next poll, not the command's reply.** Asterisk answers a successful command with nothing, so the page says "Sent" and refreshes the link table at once and again 1.5 seconds later; the table shows what really happened. Asterisk's own text is shown when it refuses (for example an unknown node).
- **Checked before Asterisk sees it.** The server builds the command line only from a node on this server, a listed operation number, a numeric target and a plain-text message, and refuses a node linking to itself. Commands need the login, the same X-Requested-With guard as every other action, and are not open to the internet.
- **Every command is written to the Log tab** and the journal with the address it came from and the exact line sent.
- Not changed: the text message (ilink 9) is sent as the rpt command line, but Asterisk gives no reply to it, so Node Monitor cannot show that the other node got it.

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
