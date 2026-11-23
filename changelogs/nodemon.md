# Node Monitor (nodemon) changelog

Current file: `nodemon_v0_9_2_20261123.py`. Newest entries first.

## 0.9.2 (2026-11-23)

The Overview is tidier and the Linked Nodes tab shows every outside node. This is a release: the page logic changed.

- **Notes column.** It no longer says the node is registered. It names the node's primary link: its first established direct link, preferring one that is not a private node on this machine.
- **Linked to column.** The expandable "Other nodes on the links" list is gone from it; the column shows the direct links only.
- **Linked Nodes tab.** A new card, "Other nodes on the links", lists all the outside nodes linked beyond the main node's direct links. The Main node and Private node cards keep their own lists.

## 0.9.1 (2026-11-23)

Every GET reply says how long the server worked. This is a release: replies carry a new header.

- **`X-Work-Ms`.** Every GET reply carries the server's own time, so a page can tell a busy node from a slow network.
- **Shared code.** The AMI helpers (`ami_msg`, `ami_read`, `ami_read_for`, `ami_read_many`, `ami_output`), `etag_of`, `etag_match` and `with_work_ms` are copied from `shared/confio.py`; the private `_ami_*` copies are gone.
- Nothing else changes.

## 0.9.0 (2026-11-23)

The page feels faster: changes are pushed to it as they happen, commands show their result at once, and the slow reads moved out of the request. This is a release: the page logic and the status route changed.

- **Push, not poll.** The page asks `/api/status?since=<n>` and the server answers as soon as anything changes (or after 20 s with a short "unchanged" reply). The old stacked delay of one refresh on the server plus one on the page is gone. `/api/wake` is no longer used by the page; it stays for older pages.
- **Commands show at once.** After a command or a Disconnect, the server polls Asterisk again right away, then 0.35 s and 1.5 s later, and the page fetches once. The page no longer shows the old state for a few seconds.
- **One round trip.** The Asterisk questions for a refresh (`rpt localnodes`, registrations and one `XStat` per node) are sent together and the replies read as they arrive, not one by one.
- **No cold start.** When the last page closes, the Asterisk connection stays open (up to 15 min) and nothing is polled. The next page wakes it and gets fresh data in a fraction of a second, without a new login. A connection that died while parked is replaced quietly.
- **Slow reads off the request.** A background thread keeps the gateway states (DVSwitch, M17, SvxLink, including the `systemctl is-active` checks) and the Links card current while a page is open, so a status request no longer waits on a subprocess or a port probe. The SvxLink log is read again only when it changes, and `rpt.conf` is parsed again only when its text changes.
- **Lighter page.** Only the open tab is drawn; the others are drawn when opened. A status that did not change is not drawn again. While a command bar has focus the update waits and is drawn when focus leaves, instead of being dropped.
- **Smaller costs.** The snapshot is no longer deep-copied through JSON on every request. A browser tab that closes or goes to the background drops its waiting request.
- Nothing else changes: the same login, the same status fields (plus `seq`), the same commands.

## 0.8.1 (2026-11-22)

The Links card opens **https** for the tools that serve TLS. This is a release: the address a link opens changed.

- SysMon, Node Talker and Node Recorder open `https://<host>:<port>/`. Terminal Monitor and Cockpit already did. Node Controller, instmon, wifimon, 44helper and Pibrary stay on http.
- The console message after `--install` says `https://`.
- Nothing else changes.

## 0.8.0 (2026-11-18)

A new **Linked Nodes** tab lists the main node and every link it has. This is a release: the page has a new tab.

- **Linked Nodes tab**, after Main node. The card shows the main node's state, then one row per link: node, type, tuned to, state, mode, direction, time connected and audio.
- **Private nodes are included.** A link to a private node (1000 to 1999) is marked `(local)`, so it is easy to tell apart from an outside link.
- **Nothing else changes.** The Main node and Private nodes tabs and the status reply are as in 0.7.0.
- **Phone, held upright:** the Nodes table on Overview hides the State column (UP and DOWN badges) and shows the Linked to column in its place. Notes stays hidden. Landscape is unchanged.
- **Palette:** the colour tokens match Node Controller's dark palette (purple, pink, FCS teal, muted and the dim variants are added). The Linked Nodes tab uses its pink.

## 0.7.0 (2026-11-17)

The page is served over TLS only, login sessions are bound to the client's address, and the power buttons need the root password again. This is a release: a node must be given a certificate or a TLS proxy, and a proxy must be listed in `trusted_proxies`.

- **TLS is required.** The server does not start without `cert_file` and `key_file`, or with `https = on` on any address but loopback (a TLS proxy). It exits with code 78, which systemd does not restart. Plain HTTP is no longer served.
- **Install makes a certificate.** When no TLS is configured, `--install` creates a self-signed certificate in `/etc/asl_dvs/tls` (10 years) and writes the paths to `nodemon.conf`.
- **Sessions are bound to the client's address.** A session presented from another address is refused and dropped. `session_bind_ip = off` turns this off.
- **Proxy headers only from `trusted_proxies`.** `CF-Connecting-IP`, `X-Real-IP` and `X-Forwarded-For` count only from a listed address. Any other request carrying them is treated as internet traffic.
- **Logout ends every session**, as in every tool (shared policy). Each address is limited to 10 sessions.
- **Reboot and Shutdown ask for the root password** and are hidden from users who are not root. A wrong password returns 403.
- **Nothing sensitive without login.** `/api/health` and `/api/whoami` give only `{"ok": true}` (and `authed` in whoami) before login.
- **AMI.** The account chosen for the manager interface must have write rights (`write = all` or `system`). Commands are cut off after 15 s, so a stalled Asterisk cannot hold the command lock.
- **Page.** The page calls `POST /api/wake` to keep AMI polling alive. `GET /api/status` no longer changes state.
- **Firewall.** Opening and closing the port handle a ufw IPv6 rule and a timed-out firewall command.
- **Config.** `bridge_nodes` sets the node-number-to-bridge map (default `1999:34001,1917:34008,1900:34000,1921:34018`). `save_config` refuses a non-numeric `main_node`, a port outside 1024–65535, and a non-IPv4 `bind_addr`.
- **Password hash.** A root hash that libcrypt cannot check is logged once by type (for example `$y$` needs libxcrypt 4.4 or later). The hash itself is never logged.
- **A failed request answers 500.** If a handler raises, the reply is a 500 with a message, and the reason is written to the log. The connection is no longer dropped without a word.
- The version is 0.7.0. Existing nodes need the new config keys above before the upgrade, or the install creates them.

## 0.6.0 (2026-11-16)

A node linked to a hub no longer lists the hub's whole roster as its own links, and the Connections tab is gone. This is a release: what the status reply and the page count as a link changed.

- **Only direct links are links.** A link is a node Asterisk reports with a `Conn:` line (and one still connecting). Before, every other node in Asterisk's `LinkedNodes` line, which for a hub such as the East Coast Reflector is every node on it, was added as a link with the state UNKNOWN. A node linked to a hub showed over a hundred links, and Node Talker's transmit node showed the same list again because it is linked to the main node.
- **The nodes behind the links are collapsed.** Under the Linked to column and on the Main node and Private node cards a closed line reads "Other nodes on the links (N)" and opens to the list of node numbers. Asterisk does not say which link each one is behind, so they are not grouped.
- **The counts follow.** "Links on the nodes" on the Overview card counts direct links only, so it no longer counts the same hub nodes once for every node that can see them.
- **Disconnect and Disconnect All are unchanged.** They drop the node's direct links, as before. The status reply gets an `others` list for each node beside `links`.
- **The Connections tab is removed.** It repeated the main node's link table and the gateways, which the Main node tab already shows. The tabs are Overview, Main node, Private nodes and Log.
- Nothing else changes.

## 0.5.1 (2026-11-16)

The look of the Nodes card rows on the Overview tab, in three states. This is a release: the State column's text changed.

- **Up:** the light gold of 0.4.0: a gold edge, an amber glowing node number and a pale gold row.
- **Transmitting or receiving:** a bright red background with amber text and an amber edge, as on Node Controller's favorites, instead of 0.5.0's pale red.
- **Down or not loaded:** clear, with no colour and no button, as before.
- **A short State badge:** a node that is down shows **DOWN** and the reason (not loaded in Asterisk, or what Asterisk said) moves into the Notes column. The long text in the badge pushed the DisCon button off a portrait phone. The Main node and Private nodes tabs still give the full reason in their headings.
- The Status boxes are unchanged.

## 0.5.0 (2026-11-16)

A **DisCon** button for every node on the Overview tab. This is a release: there is a new action.

- **DisCon column**, right-justified, on the Nodes card. Every node that is up has a button; a node that is down or not loaded has none. It acts at once and asks nothing.
- **A private node's button** drops every link on that node (ilink 6). It does not touch the gateway behind the node: a SvxLink talkgroup or a DVSwitch tuning stays as it was.
- **The main node's button, "Disconnect All", does all.** It drops every link on each private node that is loaded, then every link on the main node, then links Node Talker's transmit node again if it was linked, so Node Talker keeps working.
- **Node Talker's transmit node** (1921 by default): its own button drops its links, and the result line says its transmit link stays down until Node Talker links it again.
- **The System bar's Disconnect All** now does the same as the main node's button, and no longer asks first. Reboot and Shutdown still ask.
- **The result** shows under the table (on the System bar when the button on it is used from another tab) for a few seconds, in green or red. If a step fails the others still run, and the message names what did not work. A button turns off while its command is running.
- **Active nodes look like Node Controller's favorites:** an active node's row on the Nodes card has the red background and amber text of Node Controller's quick-link and favorite buttons, instead of 0.4.0's gold edge and glow. A node that is transmitting or receiving has a deeper red. A node that is down or not loaded keeps the plain look. The Status boxes are unchanged.
- **Phone, portrait:** the Nodes card shows only Node, What, State and DisCon, so the button is always on screen. Landscape and wider screens show every column.
- **The Allmon3 button is gone** from the Links card, which now lists the other tools and DVSwitch. The Nodemon buttons in the other tools come in their own releases.
- Every press is written to the Log tab and the journal with the address that pressed it.

## 0.4.0 (2026-11-16)

An **Overview** tab, first and the one the page opens on. This is a release: the status reply has a new field and the page's logic changed.

- **Status card:** whether Asterisk answers, how many of the nodes are up, how many links there are in all, how many gateways are tuned, and the ASL3 registration state.
- **Nodes card:** one line for every node in rpt.conf, the main node first: what it is (the bridge name for a private node), its state (up, not loaded in Asterisk, or no answer), the nodes linked to it, and a note (transmitting or receiving, what its gateway is tuned to, the registration).
- **Links card**, like Node Talker's Setup tab: buttons to the tools on this node that answer right now, which are Node Controller, SysMon, instmon, wifimon, 44helper, Node Talker, Node Recorder, Pibrary, Terminal Monitor, Cockpit, Allmon3 and DVSwitch. A tool that is not running is not shown, and neither is Node Monitor itself. The answer is kept for 15 seconds.
- **Active nodes light up** in Node Controller's amber and gold: a node that is up gets a gold edge, an amber number and a glow, and a node that is transmitting or receiving glows brighter. A node that is not loaded in Asterisk or does not answer stays dim. The same lighting marks the Status boxes that are non-zero.
- **Polling idles when no page is open.** Asterisk is polled only while a logged-in page is asking for the status: the page asks every few seconds while it is on screen and stops when its browser tab is hidden. Thirty seconds after the last request the poller closes its connection to Asterisk and waits; the Log tab says so. The next request wakes it and waits up to 4 seconds for fresh data, so the first view after an idle spell is never stale. A node with no page open now costs Asterisk nothing, and Node Monitor sends no manager commands until the first page asks. The service watchdog's own health check does not wake it.
- The other tabs are unchanged and keep their order after the Overview.

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
