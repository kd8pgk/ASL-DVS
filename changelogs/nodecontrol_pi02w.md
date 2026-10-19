# Dashboard, Pi Zero 2 W build changelog

Current file: `nodecontrol_pi02w_v9_3_91_20261019.py`. Before 9.3.76 / 9.3.71.15-pi02w the file was `asl_dvs_dashboard[_pi02w]_v….py` and this log was `asl_dvs_dashboard[_pi02w].md`. Newest entries first.

## 9.3.91-pi02w (2026-10-19)

- **Code cleanup, no change in behaviour.** The M17 and XLX host-list readers
  share one text helper instead of two identical copies, and an unused
  `__pycache__` helper is gone.

## 9.3.90-pi02w (2026-10-19)

- **Listen** keeps its green look but drops the speaker icon. Like SysMon's
  button it is greyed out (instead of hidden) when Node Listen isn't running.
- **Listen opens one tab and reuses it.** The first press opens Node Listen in
  a new tab; later presses switch to that tab without reloading it, so audio
  that is playing keeps playing. Once the tab is closed, the next press opens
  a new one. This also works after the Dashboard page is reloaded.
- The Dashboard names its own tab, so Node Listen's **Node Controller** button
  (0.4.2 or later) can switch back to it instead of opening another.

## 9.3.89-pi02w (2026-10-19)

A local API for Node Listen, so its phone page connects through the Dashboard.
Pi02w only; the full build is unchanged.

- **`POST /api/local/action`**, accepted only from 127.0.0.1 / ::1 and only with
  the `X-ASL-DVS-Local-Key` header matching `/etc/asl_dvs/local_api.key` (a
  64-hex-digit key, mode 0600, made at start if missing; Node Listen makes it
  too if it starts first). No login cookie is involved; refused requests are
  logged.
  - `{"action": "connect", "mode": "ASL" | "EchoLink", "node", "name"}`:
    switches to the ASL or Echo tab when another tab is open (the normal tab
    switch, which takes down a digital mode's bridge), then runs the same
    connect as the tab's Connect button, so the link is the Dashboard's own.
  - `{"action": "disconnect", "node"}`: the ASL or Echo tab's Disconnect when it
    is the current link, else drops just that link. Bridge nodes and Node
    Listen's 1921 are refused.
- This keeps the permanent-link "Bridging risk" banner, the extra-link clean-up
  and the bridge watchdog right when the phone page connects, and stops a phone
  connect from linking AllStar while a digital bridge is still linked.

## 9.3.88-pi02w (2026-10-19)

The IAX port is read from included files too. Pi02w only; the full build has the
same code and is unchanged.

- **`bindport` in an included file.** The Phone tab writes its nodes' `[nodes]`
  lines as `radio@127.0.0.1:<bindport>/<node>` when iax.conf's `bindport` isn't
  4569. A `bindport` set in a file pulled in with `#include` / `#tryinclude`
  under `[general]` was missed unless that file had its own `[general]` line, so
  the Dashboard used 4569 and the Phone nodes couldn't link. An included file now
  carries on in the section it was included from, as Asterisk reads it. Found
  while auditing Node Listen 0.3.1, which uses the same rule.

## 9.3.87-pi02w (2026-10-19)

Node Listen's transmit node (1921) is kept out of the Dashboard's link handling.
Pi02w only; the full build is unchanged.

- **Which node:** Node Listen's (nodelisten 0.3.0 and later) transmit node is
  1921, and the Dashboard treats it as Node Listen's only when rpt.conf has the
  `; nodelisten: transmit node` line right above `[1921]` (read when rpt.conf
  changes). A node 1921 of your own is handled as before.
- **Never "the connected node":** the status poll drops it from the link list,
  so it isn't shown as the connected node, a foreign or permanent link, or an
  extra link for the multi-link clean-up.
- **Kept while Node Listen runs** (`/api/nodelisten-status`, the port check
  behind the Listen button): Disconnect, tab switches and every other teardown
  that drops links one by one skip it; the `ilink 6` fallback (link query
  failed) relinks it straight after; the teardown check no longer warns about it.
- **Dropped when Node Listen isn't running:** if it is linked and Node Listen
  doesn't answer, the poll unlinks it (`ilink 1 1921`), at most once every 30 s.
  Node Listen also unlinks it itself when it stops.

## 9.3.86-pi02w (2026-10-18)

A **Listen** button for Node Listen. Pi02w only; the full build is unchanged.

- **Listen button** next to the connection indicator in the quick-link row (on a
  phone, beside the indicator in the row above the links, where there was room).
  It opens Node Listen (`nodelisten`) in a new tab to hear the node in the browser.
- It shows only when Node Listen is running. The page asks the new
  `GET /api/nodelisten-status` once at start; the server reads the port from
  `/etc/asl_dvs/nodelisten.conf` (default 8993) and checks it answers on
  127.0.0.1, cached 15 s. Without Node Listen the row looks as before.

## 9.3.85-pi02w (2026-10-18)

Leaving the M17 tab runs M17's Disconnect first. The full build gets the same change in
9.3.84.

- **M17 disconnects when you leave its tab.** Switching from M17 to any other tab (or
  connecting from another tab's favorites while M17 is active) now does exactly what
  M17's Disconnect button does, before anything else in the switch: drop the ASL link
  to the M17 bridge node, write the placeholder M17 ini, restart USRP2M17 and clear
  the M17 connection. Before, the switch wrote the ini and restarted USRP2M17 but left
  the bridge-node link to the new tab's general link clean-up, which ran afterwards.
  Both now share one helper (`_m17_disconnect_core`).
- Opening the Edit tab doesn't change the server's page, so M17 stays connected while
  you are on Edit. Re-clicking the M17 tab (re-tune) doesn't disconnect.

## 9.3.84-pi02w (2026-10-18)

M17 tab loses its top row; its LH opens the reflector's IP address; its Connect warns
when USRP2M17 or Analog_Bridge is down. The full build is not changed.

- **M17: top row removed.** The reflector IP box, its module menu and Connect above
  the Reflector / Module menus are gone. Reflectors come from the menus only (an
  unlisted reflector can no longer be typed in); saved favorites still connect from
  the grid. The card's module menu already offers All Modules.
- **LH opens the reflector's IP address.** `/api/m17-hosts` rows carry a new `ip`
  field (the IPv4 address from M17Hosts.json, or the IPv6 address when there is no
  IPv4). The card's LH opens `http://<ip>/` with no port (IPv6 in brackets), never
  the DNS name. It is greyed out with no reflector picked or when the reflector
  publishes no IP. Connect still uses the same address as before, and saved
  favorites keep the Last Heard link they were saved with.
- **Connect warning.** The 15 s service check also covers `usrp2m17.service`
  (status `svc.m17`). M17 Connect shows red with a strike-through when USRP2M17 or
  Analog_Bridge isn't running, with a hover note naming what is down.
- The page code for the old row (`m17QuickConnect`, `initModuleSelects`) is removed.

## 9.3.83-pi02w (2026-10-18)

D-STAR and XLX tabs lose their top row; their Connect buttons warn when ircDDBGateway
or Analog_Bridge is down. The full build is not changed.

- **D-STAR, XLX: top row removed.** The reflector box, its module menu, Connect (and
  D-STAR's Save) above the search row are gone. The search row's own A–Z module menu
  stays.
- **Connect takes the top row's job.** When no reflector is picked from the menu,
  Connect (or Enter in the search box) links what is typed there with the module
  menu's letter, through the same connect calls the top row used: a D-STAR reflector
  (`REF001`, `XRF012`, `DCS001`) or gateway callsign (`W1ABC`), or an XLX reflector
  (`XLX334`). A module letter typed after a space (`W1ABC B`, `XLX334 C`) wins over the
  menu, also for a reflector picked from the list. Plain search words and numbers
  ("DAM", "307") stay searches. The search box stays usable when the list is missing.
- **Save.** D-STAR Save takes the picked reflector, or else the typed reflector or
  callsign with its module, like the old top-row Save. XLX Save is unchanged (picked
  reflector only).
- **Connect warning.** The 15 s service check also covers `ircddbgatewayd.service`
  (status `svc.ircddb`). D-STAR and XLX Connect show red with a strike-through when
  ircDDBGateway or Analog_Bridge isn't running, with a hover note naming what is down.
- The page code for the old rows (`dstarQuickConnect`, `dstarQuickSave`,
  `xlxQuickConnect`, `reflectorQuickConnect`) is removed.

## 9.3.82-pi02w (2026-10-18)

FCS tab loses its top row; its Connect warns like YSF's. The full build is not
changed.

- **FCS: top row removed.** The room box, its Connect and the network LH above the
  Server / Room menus are gone. Rooms are picked from the menus only; there is no
  typed room any more.
- **LH falls back to the FCS network.** The card's LH opens the picked server's Last
  Heard page; with no server picked (or a server with no page) it opens the Edit tab's
  FCS Last Heard address, which the removed network LH used to open. It is greyed out
  only when neither exists.
- **Connect warning.** FCS Connect shows red with a strike-through when YSFGateway
  (which FCS runs through) or Analog_Bridge isn't running, with a hover note naming
  what is down. It uses the `ysf` state the server already reports.

## 9.3.81-pi02w (2026-10-18)

YSF, P25 and NXDN tabs lose their Tune row; their Connect buttons warn when their
gateway or Analog_Bridge is down; every Tune button is now Connect. The full build is
not changed.

- **YSF, P25, NXDN: Tune row removed.** The text box and Tune button above the search
  row are gone.
- **Connect takes Tune's job.** When nothing is picked from the menu, Connect (or Enter
  in the search box) tunes what is typed there, through the same quick tune Tune used:
  a talkgroup number (1–8 digits) on P25 and NXDN, a `host:port` or `IP:port` address
  on YSF (other YSF text stays a search). Something picked from the menu still wins.
  The search box stays usable when the list is missing or empty.
- **Save.** P25 and NXDN Save the picked talkgroup, or else the typed number, or else
  the last number tuned (the server still only saves talkgroups in the host list).
  YSF Save is unchanged (a picked reflector only).
- **Gateway warnings.** The 15 s service check also covers `ysfgateway.service`,
  `p25gateway.service` and `nxdngateway.service`, in the same single `systemctl` call,
  and the status reply's `svc` carries `ysf`, `p25` and `nxdn`. YSF, P25 and NXDN
  Connect show red with a strike-through when their gateway or Analog_Bridge isn't
  running, with a hover note naming what is down. A restarting gateway counts as
  running; a gateway that isn't installed, or an unknown state, shows no warning.
- **Tune renamed Connect** on the FCS, D-STAR and XLX quick rows. No button on the
  Dashboard says Tune any more.

## 9.3.80-pi02w (2026-10-18)

STFU tab gets the ASL tab's layout; DMR and STFU warn when their services are down.
The full build is not changed.

- **STFU: Tune row removed.** The talkgroup box and its Tune and LH buttons above the
  search row are gone.
- **STFU: Connect takes Tune's jobs.** A bare number (1–8 digits, talkgroup or ID) in
  the search box tunes with Connect or Enter when no talkgroup is picked from the
  menu, through the same quick tune Tune used, so numbers not in the list work. A
  talkgroup picked from the menu still wins. The search box stays usable when the
  talkgroup list is missing or empty, for typed numbers.
- **STFU: Save.** Saves the picked talkgroup, or else the typed number, or else the
  last number tuned. The server still only saves talkgroups in the BrandMeister list.
- **STFU: LH moved into the search row,** between Connect and Save. It opens the Edit
  tab's STFU Last Heard address and is greyed out while that address is blank.
- **DMR: Tune is renamed Connect.** The DMR row is otherwise unchanged.
- **Service warnings.** Every 15 s the Dashboard checks Analog_Bridge
  (`analog_bridge.service` or `Analog_Bridge.service`) and `stfu.service` (or, with
  no unit, the `/opt/STFU/STFU` process), and the status reply carries the result
  (`svc`). DMR Connect shows red with a strike-through when Analog_Bridge isn't
  running; STFU Connect does when STFU or Analog_Bridge isn't. The hover note names
  what is down. A service that isn't installed, or an unknown state, shows no
  warning. The check runs only when DVSwitch is found.

## 9.3.79-pi02w (2026-10-18)

Echo tab: the same change 9.3.78 made to the ASL tab. The full build is not changed.

- **Tune row removed.** The node-number box and its Tune, LH and Save buttons above
  the search row are gone.
- **Connect takes Tune's jobs.** A bare node number (1–7 digits) in the search box
  connects that node with Connect or Enter when no station is picked from the menu,
  even one that isn't logged in right now. A station picked from the menu still wins.
  The search box stays usable when the station list is missing or empty, for typed
  numbers.
- **Save.** Saves the picked station, or else the typed number, or else the last node
  connected by number.
- **LH opens the Edit tab's Echo Last Heard address.** It no longer opens EchoLink's
  logins page. It is greyed out while that address is blank.
- The page code left over from the two Tune rows is removed.

## 9.3.78-pi02w (2026-10-18)

ASL tab: the Tune row is gone. The search row does its jobs. The full build is not
changed.

- **Tune row removed.** The node-number box and its Tune, LH and Save buttons above
  the search row are gone.
- **Connect takes Tune's jobs.** A bare node number (1–7 digits) in the search box
  connects that node with Connect or Enter when no node is picked from the menu, even
  a node that isn't in the AllStar node list. A node picked from the menu still wins.
  The search box stays usable when the node list is missing or empty, for typed
  numbers.
- **"Not registered" warning moved to Connect.** When the node isn't registered with
  AllStarLink, Connect shows in red with a strike-through (and the hover note), even
  when it is greyed out.
- **Save.** Saves the picked node, or else the typed number, or else the last node
  connected by number.
- **LH opens the Edit tab's ASL Last Heard address.** It no longer opens the picked
  node's AllStar stats page. It is greyed out while that address is blank.

## 9.3.77-pi02w (2026-10-18)

Fresh-boot fixes from the boot audit: the boot disconnect-all now waits for the
network, a Dashboard restart no longer repeats it, and clock steps from NTP no longer
upset the boot checks or the registration time. The full build is not changed.

- **Boot disconnect-all waits for the network.** It ran 30 s after Asterisk started,
  which could be before WiFi and the 44Net tunnel were up, so links made afterwards
  (startup macro, permanent links) stayed up. If Asterisk was late, it ran after
  2 minutes with no Asterisk at all. Now it waits (at most 7.5 minutes from the
  Dashboard's start) until Asterisk has been up 30 s and, when 44helper's boot order
  is in place, `44helper-netready` has finished. Without 44helper it waits for
  Asterisk only. If Asterisk never starts, disconnect-all is skipped and the log says
  so.
- **A Dashboard restart doesn't run disconnect-all again.** A marker for this boot
  (`/run/asl_dvs/boot_disconnect_done`, holding the boot id) is written as soon as
  disconnect-all has run, and a restart during the rest of the fresh-boot work skips
  it. The boot marker is now written once all the fresh-boot work is done.
- **The startup tune waits from Analog_Bridge's start.** The 5-minute wait for
  Analog_Bridge counts from when `analog_bridge.service` (or `Analog_Bridge.service`)
  became active, not from the Dashboard's start, with a limit of 10 minutes after
  boot. Without an Analog_Bridge unit the wait is unchanged.
- **Analog_Bridge's report survives a clock step.** The "from this boot" check on
  `/tmp/ABInfo_*.json` is made against Analog_Bridge's start time from systemd (5 s
  margin) instead of the boot time, so a file written before NTP moved the clock
  forward is still used. Without an Analog_Bridge unit the old check is kept.
- **"Not registered since" survives a clock step.** The time since the registration
  state last changed is counted on the monotonic clock; before, NTP moving the clock
  forward by hours made a fresh "unregistered" look hours old, and wifimon alerted at
  once. `asl_reg.json` keeps the same fields.
- **Phone setup refresh waits for Asterisk.** It tries again every 15 s for up to
  5 minutes instead of one try at 20 s.
- Tested (mocks): disconnect-all with and without 44helper, a late or missing
  Asterisk, a netready unit not in this boot; the tune limits; ABInfo across a
  3-hour clock step; the restart marker; registration "since" after a 5-hour clock
  step; the Phone refresh retry.

## 9.3.76-pi02w (2026-10-18)

Fresh-boot start-up fixes from a boot audit (44helper's boot order now makes
Analog_Bridge wait up to 3 minutes for the network and the tunnel).

- **The fresh-boot DVSwitch tune waits for Analog_Bridge.** On a fresh boot the
  Dashboard sent its startup tune (DMR server, or disconnect and re-select the mode)
  straight away. With Analog_Bridge still waiting for the network the tune went
  nowhere, and the boot marker, written first, stopped it being tried again. Now
  the tune runs in a background thread that waits up to 5 minutes for
  Analog_Bridge's `/tmp/ABInfo_*.json` from this boot, then tunes (or tunes anyway
  after the limit). The boot marker is written only after that, so a Dashboard
  restart during the wait tries again. A restart within the same boot still
  keeps the live links, unchanged.
- **The tune no longer runs before the service reports ready**, so a slow
  `dvswitch.sh` can't push the Dashboard past systemd's 90 s start limit.
- **Fresh-boot disconnect-all waits for Asterisk to settle.** It now runs in the
  background once Asterisk has been active for 30 s (at most 2 minutes), so it
  doesn't race Asterisk's own start-up.
- Tested (mocks): the tune waits for Analog_Bridge and then tunes; with no report
  it tunes after the limit; the marker is written only afterwards; disconnect-all
  waits for a settled Asterisk; `startup()` on a fresh boot starts both in the
  background and returns at once; a same-boot restart keeps the live links.

## 9.3.75-pi02w (2026-10-14)

The Dashboard shares the AllStarLink registration state with other tools, so
wifimon can send an alert when the node drops off AllStarLink (reliability
plan, Stage 7). The full build is not changed.

- After every registration check, the Dashboard writes
  `/run/asl_dvs/asl_reg.json`, readable by all:
  - `node`, `state` (`registered`, `unregistered` or `unknown`);
  - `since`: when the state last changed;
  - `checked_at`: this check;
  - `next_check_secs`: 900 when registered, 60 otherwise, so a reader can
    tell when the file is stale.
- `/run` is in memory, so this doesn't wear the SD card. If the file can't be
  written, the check carries on as before.
- Nothing changes on the page.
- Tested (unit tests with mocks, 2): registered, then registered again (`since`
  kept, `checked_at` moves on), then unregistered (`since` moves, and the
  next check is in 60 s); mode 644; no `.tmp` left; an unwritable path
  doesn't break the check. `ci/check_repo.py`.

## 9.3.74-pi02w (2026-10-14)

The systemd watchdog now checks the right things (reliability plan, Stage 2).
The full build is not changed.

- **New heartbeat.** Before, the link-poll loop told systemd "alive" at the
  top of each poll. So a hung web server went unnoticed. Worse, a frozen
  Asterisk that held the poll on AMI could get the Dashboard killed and
  restarted for Asterisk's fault. With no ASL and no DVSwitch, there was no
  poll loop at all, so systemd restarted the Dashboard every 30 s. Now a
  `sd-heartbeat` thread sends "alive" (every 10 s, `WatchdogSec=30`
  unchanged) only when both hold:
  - the link-poll loop started a pass in the last 120 s (or it isn't
    running), and
  - the Dashboard answered its own `GET /healthz` within the last 25 s. A
    `health-probe` thread asks every 10 s on 127.0.0.1, on the port the
    server is bound to.

  When either fails, the log says which, and systemd restarts the Dashboard
  within about a minute.
- **`/healthz`** (new, no login): the same tiny `{"ok":true}` as
  `/api/ping`, for this probe and for instmon's check after an update.
- **The poll no longer waits behind a stuck AMI command.** Its
  `rpt show variables` waits at most 3 s for the AMI lock. When the lock is
  busy it skips that poll and leaves the page state as it was (before, a
  failed poll could blank the link state). The log says so once. Commands
  from the page wait for the lock as before. The `asterisk -rx` fallback
  still runs outside the lock.
- The link-mode table is replaced in one step instead of cleared and
  refilled, so another thread never reads it empty.
- `USRP2M17.ini` (M17 bridge) is forced to disk before it replaces the old
  file, like the Dashboard's own config.
- Tested (unit tests with mocks, 10):
  - the AMI lock wait gives up in time; calls without a wait still queue;
    the fallback runs with the lock free; the lock is released on errors
  - with AMI held, the poll loop keeps running and doesn't touch the page
    state
  - the heartbeat rules
  - against a real server on a free port: `/healthz` answers without login
    while `/api/status` needs it; "alive" messages reach a real notify
    socket, stop while the server refuses connections, and resume after
  - the link-mode swap; the M17 file write and fsync
  - `ci/check_repo.py` (py_compile, pyflakes, node --check, version,
    README, changelog, launcher)

## 9.3.73-pi02w (2026-10-14)

The ASL tab's Tune button shows whether the node is registered with
AllStarLink. The full build is not changed.

- New background check `asl-reg` asks Asterisk `rpt show registrations` (over
  AMI) and looks for the node set in Edit. It uses SysMon's rule:
  - a line naming the node with "unregist", "rejected", "failed", "timeout"
    or "timed out" → unregistered
  - a line naming the node with "regist" → registered
  - the node missing from the list → unregistered
  - Asterisk not answering → unknown
- `/api/status` carries the result as `asl_reg` (read from a cache, so the
  status call does no extra work).
- The Tune button next to the node number box:
  - registered or unknown: its normal teal look
  - unregistered: red border, red text with a line through "Tune", and the
    tooltip "Node N is not registered with AllStarLink". It can still be
    clicked.
- How often it checks:
  - every 60 s while the node is not registered (or the state is unknown)
  - every 15 min once registered
  - again 5 s after a network change (an interface going down or up, or a
    Wi-Fi reconnect, read from `/sys/class/net/*/operstate` and
    `carrier_changes`), then every 60 s until registered
  - at once when the node number in Edit changes
- Tested:
  - Unit test with a mocked AMI: Registered, Rejected, node missing, no
    registrations, and AMI down give registered / unregistered / unregistered
    / unregistered / unknown. With a mocked clock: checks at 0, 60 and 120 s
    while unregistered, then backs off to 15 min, and a network change at
    600 s brings a check at 606 s.
  - The page in headless Chromium: registered teal `rgb(0,255,229)` with no
    line through; unregistered red `rgb(255,61,90)` with a line through and
    the tooltip; unknown teal. No script errors. `node --check` on the page
    script.

## 9.3.72-pi02w (2026-10-14)

The Phone tab carries a notice that sending music over a radio node breaks FCC
rules. The full build is not changed.

- A boxed amber notice under the Phone tab's Hang Up / Keypad / Patch / Report
  bar:
  - music on an amateur station is prohibited by 47 CFR §97.113(a)(4), and
    that includes a phone system's hold music or a recording played into a call
  - §97.113(e) also bars retransmitting broadcast stations
  - hang up if a call goes to hold music
  - radioless nodes and phone systems with no RF link should be fine
- Version moves from four parts to three: 9.3.71.18-pi02w -> 9.3.72-pi02w.
  `BUILD_DATE` is 2026-10-14.
- Tested:
  - The page in headless Chromium: the notice shows on the Phone tab in amber
    `rgb(255,208,64)`, no script errors. `node --check` on the page script.

## 9.3.71.18-pi02w (2026-10-13)

Easier to read: the grey-blue text is white, successes are green and failures are
red, as in 44helper 0.0.187x and SysMon 6.13.67.17-pi02w. Only text colours
change. The full build is not changed.

- The grey-blue colours are now plain white `#ffffff`:
  - `--text` (was `#d0dff0`), `--muted` (was `#4a6080`) and the Edit page's
    Back/Reload button text (was `#9ab8d0`)
  - the typed-in `#5a7898` (section labels, row numbers, reflector hosts,
    column headers, hints, input placeholders), `#7a9ec0` (card messages and
    muted buttons), `#3a5278` (the idle TG indicator, the edit count, section
    headers), `#6f8aa8`, `#5a6b7c`, `#4a5a6a` and `#4a5a3a`
  - the shutdown sub-line `#c98a92`
- Failures that were pale pink or salmon are bright red `--red`: the error
  box, the alert bar, the shutdown message and a failed phone sign-in. A
  disconnected row's name, which was dark red, is bright red.
- The Phone tab's result line under Apply, Activate and Revert:
  - green when the step worked, red when it failed (new `phMsg` helper)
  - it was grey-blue whatever the result
- Toasts were already green and red and are unchanged. Warnings stay amber.
- Tested:
  - The page in headless Chromium, before and after: body text
    `rgb(255,255,255)`, the Phone result line green `rgb(0,255,176)` for a
    success and red `rgb(255,61,90)` for a failure, no script errors.
  - No old grey-blue text colour left.
  - `node --check` on the page JavaScript.

## 9.3.71.17-pi02w (2026-10-13)

Phone fixes from an audit of the Phone tab and the Edit page's Phone section,
and the "Node Controller" naming. Pi Zero 2 W build only; the full build is
unchanged.

- Edit page, network cards: each card shows only its own hints.
  - The router hint ("SIP needs UDP 5060 and UDP 10000-20000 forwarded") was
    the `else` of the Hams Over IP check, so IAX2 cards showed it too. It now
    shows only on SIP-type cards, and no longer tells everyone to forward ports:
    signing in usually keeps calls working with nothing forwarded; forward UDP
    5060 only if incoming calls don't arrive, and the audio ports if audio is
    one-way. A "SIP by IP address" network, which doesn't sign in, is told it
    needs the forward for incoming calls.
  - AmateurWire cards no longer show the Hams Over IP port hint ("SIP on UDP
    5160, audio on 10000-15000"); they get their own Voicemail Access note.
- A favorite's saved tones (Straight to the provider and As sound routes) are
  sent if the call answers any time within the 65-second ring time. Before, the
  dashboard waited only the `*61` digit timeout plus 15 s (35 s by default) and
  dropped the tones on a later answer.
- Wording:
  - "Dial timeout (ms)" is now "*61 digit timeout (ms)", with a tooltip: it is
    how long `*61` from the radio waits for the next digit, not how long a call
    rings. The setting and its saved value are unchanged.
  - Incoming-call status: an open network with trusted numbers says "trusted
    numbers only" (others get busy), and a PIN network with trusted numbers says
    "waiting for PIN (trusted numbers skip it)".
  - Send keypad tones choices drop the "(v9.3.13 way)" and "(test)" tags:
    "Straight to the provider", "Through the call", "As sound (tone recordings)".
- Naming: the page title, logo and login heading say "Node Control" (no
  "ASL-DVS"); so does the console banner. The service description, the phone
  report and the config files the dashboard writes are unchanged.
- Tested: page in headless Chromium (each network type's hints, the four
  incoming-status cases, title, logo and labels, no script errors); saved-tones
  wait with a simulated clock (answered at 50 s: sent at 51 s; 9.3.71.16 gave up
  at 35 s).

## 9.3.71.16-pi02w (2026-10-12)

The USRP2M17 quick-link button is now an **InstMon** button. The same change is in the full build (9.3.77).

- The right-hand quick links are now InstMon, WiFiMon and SysMon. InstMon has
  the same look as the other quick-link buttons and opens instmon
  (`http://<host>:8990/`) in a new tab.
- The M17 tab is unchanged.
- File: `nodecontrol_pi02w_v9_3_71_16_20261012.py`.

## 9.3.71.15-pi02w (2026-10-12)

The Dashboard is now named **nodecontrol**. The same change is in the full build (9.3.76).
Needs instmon 2.43.0 or later to show it under the new name.

- File: `nodecontrol_pi02w_v9_3_71_15_20261012.py` (was `asl_dvs_dashboard…`).
- Service: `nodecontrol.service` (was `asl_dvs_dashboard.service`). `--install`
  stops, disables and removes the old unit before it starts the new one, so
  port 8989 is never held twice.
- Program: `/usr/local/bin/nodecontrol.py`, a link into
  `/usr/local/lib/asl_dvs/nodecontrol/`. `/usr/local/bin/asl_dvs_dashboard.py`
  stays as a second link to the same file, for older instmon and uninstaller
  versions. The old copies in `/usr/local/lib/asl_dvs/dashboard/` and directly
  in `/usr/local/lib/asl_dvs/` are removed; other tools' folders are not touched.
- `--uninstall` removes both units, both links, the lib file and the empty
  folders.
- Unchanged: `/etc/asl_dvs/asl_dvs.conf`, `phone.json`, the login, port 8989, and
  the `asl_dvs_dashboard` markers on the Phone tab's Asterisk files (existing
  nodes' dialplans carry them, and the Dashboard finds its own blocks by them).
- Launcher version 3 (the same text in every tool that writes it): a tool file
  whose name starts with a digit, like `44helper_v….py`, is loaded through
  `importlib`, so its compiled copy in `__pycache__` is used instead of being
  recompiled on every start.
- Tested with mocks against a temporary root: a fresh node, a node on the old
  service with the file in the old flat folder or in `dashboard/`, the new
  layout, installing through either link, and uninstall with a stray old unit;
  another tool's folder survives each time.

## 9.3.71.14-pi02w (2026-10-12)

Standard install layout (same as instmon 2.40.0, wifimon 5.29, 44helper 0.0.180
and SysMon). The same change is in the full build (9.3.75).

- `--install` copies the file to `/usr/local/lib/asl_dvs/dashboard/` (it used to
  sit directly in `/usr/local/lib/asl_dvs/`, which now holds one folder per tool)
  and points `/usr/local/bin/asl_dvs_dashboard.py` at it. The link is swapped in
  with one rename, so the path is never missing. Any other version in the new
  folder is removed, and so are the old `asl_dvs_dashboard*.py` files (and their
  compiled copies) directly in `/usr/local/lib/asl_dvs/`. The other tools'
  folders there are not touched. Running `--install` through the link changes
  nothing.
- Unit: adds `NotifyAccess=main`, the same as SysMon and instmon. Otherwise
  unchanged.
- `--uninstall` also removes the empty lib folder, and `/usr/local/lib/asl_dvs/`
  if nothing else is left in it.
- Tested with mocks against a temporary root: a fresh install, an install over
  the old flat layout (with another tool's folder next to it) and over the new
  layout, reinstall through the link, and uninstall.

## 9.3.71.13-pi02w (2026-10-07)

- M17 favorites: the module drop-down on each reflector row clipped "All Modules"
  to "All Modu" (the box was 88 px wide, the text needs about 71 px plus padding
  and the arrow). It is now 7.6 rem wide on the M17 grid and the M17 quick bar.
  The rows were already identical to each other at 390, 800, 980 and 1280 px;
  the drop-down clip was the only difference. Other pages (D-STAR, XLX) keep the
  narrow box because their modules are one letter.

## 9.3.71.12-pi02w (2026-10-07)

- Edit, Phone tab: the network cards lined up wrongly on tablet-width screens
  (about 560 to 1200 px; found on a Galaxy Tab S6 Lite in Vivaldi, where turning
  on "Desktop site" hid it). Phones use one column and were fine.
  - A field whose label wraps to two lines (for example "SIP server / proxy /
    registrar") pushed its box lower than the boxes beside it. Fields in a row
    now sit on a common bottom line, so every box lines up.
  - The checkbox rows ("E911 is set up", "Allow international") sat at label
    height, above the box next to them. They now have the height of a box and
    sit level with it.
  - The favorites rows used their own column widths and gap, so Name, Number and
    "Then send" did not sit under the field columns above them. They now use the
    same columns and gap as the field grid at every width. The clear (✕) button
    sits inside the "Then send" cell. Phone layout is unchanged.
  - Measured in headless Chromium at 390, 560, 561, 700, 800, 900, 1000 and
    1200 px: the old build had misaligned rows at every width from 560 up, the new
    build has none, and the favorites columns match the field columns.
- No change to what is saved: names, numbers and tones sync as before, and the
  clear button still works.

## 9.3.71.11-pi02w (2026-10-07)

- M17: USRP2M17 now listens on UDP 17010 for reflector traffic (`LocalPort` in
  `[M17 Network]` of `USRP2M17.ini`), was 32010. MMDVM_Bridge's stock
  `[P25 Network]` also listens on 32010, and on node 652702 both programs held it
  at once (`ss -ulpn`), so reflector packets could reach MMDVM_Bridge instead of
  USRP2M17. The new port is written the next time the dashboard connects or
  disconnects an M17 reflector. Reflectors answer the port USRP2M17 sends from,
  so nothing else needs to change.

## 9.3.71.10-pi02w (2026-10-06)

- Phone: `*65` from the radio hangs up again. Since 9.3.71.8/9.3.71.9 no call uses
  autopatch, so `65 = autopatchdn` did nothing. `*65` now runs the same hang-up
  script as `*62` (`65 = cmd,/var/lib/asterisk/dvs_phone_hangup`), and both end any
  call. This corrects the 9.3.71.8 note that `*65` hangs up radio-dialed calls.
- Phone: the dashboard's Hang up now also cancels a radio dial that is still
  collecting digits (`rpt cmd <node> autopatchdn`), instead of keying `*65`.
- Edit page, Phone section: new "How calls from the radio work (show/hide)" note
  explaining `*61` dialing through the dashboard, why it avoids the dead key, and
  hanging up with `*62`/`*65`.
- The start-up refresh rewrites the phone nodes in `rpt.conf` on the first start.

## 9.3.71.9-pi02w (2026-10-06)

- Phone: calls dialed from the radio (`*61<number>`) now place the call the same way
  as the dashboard's Dial button (9.3.71.8), so they don't dead-key the radio either.
  - `*61` stays an autopatch code, but it now points at a new context,
    `dvs-radio-<network>` (`dvs-radio-out` for the Phone Bridge node). That context
    runs `/var/lib/asterisk/dvs_phone_dialreq <number> <network>` and hangs up, which
    ends the autopatch at once.
  - The script only accepts digits (up to 20) and a network id. It leaves a request
    file in `/run/asl_dvs_tones/req`, like the `*980`-`*982` tone codes.
  - The dashboard picks it up within about 2 seconds and dials it as if Dial were
    pressed: AMI `Originate` into `rpt(<node>,Pv)`, with the same checks (phone tab
    open, patch on, number rules, E911). The result shows as a notice on the Phone
    tab. A request from a network that isn't the picked one is ignored.
- `app_system.so` joins the phone modules, for the dialplan's `System()`.
- The start-up refresh rewrites `rpt.conf`, the dialplan and the new script on the
  first start of this build. Revert removes the script with the others.

## 9.3.71.8-pi02w (2026-10-06)

- Phone: calls dialed from the dashboard (numbers, favorites, Test call, Voicemail)
  no longer use autopatch (`rpt fun <node> *61<number>`). The dashboard has Asterisk
  place the call (AMI `Originate`, `Local/<number>@dvs-node-<network>/n`), and when
  it is answered the call joins the phone node with `rpt(<node>,Pv)`, the same way
  incoming calls already do.
- Why: during an autopatch call app_rpt keeps every linked node keyed for the whole
  call, so a simplex hotspot transmits nonstop and can't hear your radio. Joined
  with `Pv` (phone mode with VOX), the radio keys only while the far end is talking.
- The dialing rules are unchanged: the same `dvs-node-<network>` context, number
  checks, caller ID, saved tones and the phone patch on/off switch. Calls ring for up
  to 65 seconds.
- Differences from autopatch: the radio hears nothing until the far end answers (no
  ringback over the air). Long nonstop far-end talk is cut for 2 s every 10 s
  (`voxtimeout` / `voxrecover`), as on incoming calls.
- `*61<number>` dialed from the radio still uses autopatch (rpt.conf unchanged).
  From the radio, `*62` hangs up any call and `*65` hangs up radio-dialed calls.

## 9.3.71.7-pi02w (2026-10-06)

- Phone tab: the favorite in use lights up like the active row on the ASL, Echo
  and digital tabs (green bar and tint). It lights while dialing and while ringing
  in, and its dot turns on once the call is connected. It clears when the call ends.
  - Calls you dial light the favorite with the dialed number. A leading 1 on an
    11-digit number is ignored, so 5551234567 and 15551234567 match.
  - Incoming calls light the favorite whose number matches the caller ID.
  - The Test call and Voicemail rows light up for those calls.
  - The name turns gold while the radio is keyed, as on the other tabs.
- Page-only change: the Phone status already carries the call state and number.
  The highlight is switched on the rows already shown on each status refresh, so
  the list isn't redrawn.

## 9.3.71.6-pi02w (2026-10-06)

- Phone: new "Listen only (the radio never transmits into calls)" box in the Edit
  page's Phone section, off by default, one setting for all phone networks. Saved as
  `listen_only` in `/etc/asl_dvs/phone.json`.
- When it is on, the phone nodes are linked to the radio node as monitor links
  (`rpt cmd <radio node> ilink 2 <phone node>`) instead of two-way (`ilink 3`). You
  hear calls on the radio, and nothing from the radio (audio, keying or DTMF) goes
  into the call. Dialing, hang-up and keypad tones from the dashboard still work.
  Codes keyed on the radio (*61, *65, *980-*982) don't reach the phone node.
- The link watchdog reads each link's mode from `RPT_ALINKS` and relinks the phone
  node in the right mode when it is linked the other way, so the change takes effect
  a few seconds after Save Phone, after a network switch and after a restart. Other
  bridges are unchanged.
- The Phone tab shows "Listen only" next to the call status while it is on.

## 9.3.71.5-pi02w (2026-10-06)

- Phone: keypad tones on every SIP network (SIP with login, SIP by IP, Hams Over IP,
  AmateurWire) always go as tone packets (RFC 2833): `dtmf_mode=rfc4733` in
  `dvs_phone_pjsip.conf`. The Tone mode picker, its hints and the Hams Over IP
  tone-mode warning are gone from the Edit page. Saved `tone_mode` values in
  `/etc/asl_dvs/phone.json` are ignored and dropped on the next save. The phone
  report still compares what Asterisk has loaded against RFC 2833.
- Phone: the Hams Over IP AllStar Link card and everything behind it are removed:
  the Edit page card (Turn on, username, password, internet name, port, landing
  node, dial string), the HOIP AllStar caller row on the Phone tab, the incoming
  IAX2 account in `dvs_phone_iax.conf`, the `[dvs-hoiplink]` dialplan, the
  `phone-hl-dialstring` action, the port notes on save and the report section. The
  Phone tab status no longer looks up HOIP AllStar callers on each poll. The saved
  `hoip_link` block is dropped on the next save. With no IAX2 phone networks, the
  IAX2 include lines come out of `iax.conf` too.
- Phone: sign-in is always "Picked network only". The Sign in picker and each
  network's "Sign in (register) with this network" box are gone. Every network with
  a login (SIP with login, Hams Over IP, AmateurWire, IAX2) signs in while it is
  the picked network. `phone.json` keeps `signin_mode: "picked"` and `register: true`
  on those networks, which sysmon's Phone checks read.
- The start-up refresh rewrites the SIP, IAX2 and dialplan files on the first
  start of this build and reloads them.

## 9.3.71.4-pi02w (2026-10-06)

- Phone: fixes choppy receive audio on calls since 9.3.71.3. Removing the Simplex
  setting also removed `duplex = 1` and the VOX lines from the phone nodes, so they
  took `duplex` from `[node-main]` (2, full duplex, on an ASL3 install). The phone
  nodes in `rpt.conf` now always get simplex mode with the default VOX values:
  `duplex = 1`, `voxtimeout = 10000`, `voxrecover = 2000`, `simplexpatchdelay = 25`,
  `simplexphonedelay = 25`. This is what 9.3.71.2 wrote with Simplex on. There is
  still no setting for it on the Edit page. The start-up refresh rewrites the phone
  nodes on the first start of this build. Hang time still comes from `[node-main]`.

## 9.3.71.3-pi02w (2026-10-06)

- Phone: simplex and hang time always use the defaults. The Edit page's
  "Simplex radio (use VOX for calls)" box, VOX timeout, VOX recovery, Radio delay,
  Phone delay and Hang time fields are gone, and saved `simplex` / `hangtime`
  values in `/etc/asl_dvs/phone.json` are ignored and dropped on the next save. The
  phone nodes in `rpt.conf` no longer get `duplex = 1`, the VOX lines or
  `hangtime =`; the start-up refresh rewrites them on the first start of this build.
- Phone: the five programmable tone buttons are gone: the Edit page fields, the
  buttons beside the call status on the Phone tab, the saved `buttons` per network,
  and the radio codes *983 to *987. *980 (*), *981 (#) and *982 (*99) stay, and the
  Phone tab keeps its *99 and # buttons.
- Phone: the keypad pop-up is now the keys, the tones sent and the call check.
  "Send keypad tones" (the tone route) moved to the Edit page's Phone section, with
  the radio codes as a hint below it. The per-call tone mode picker and "Keep this"
  are gone (each SIP network's Tone mode on the Edit page is the setting), and with
  them the `phone-tone-mode` and `phone-tone-keep` actions and the tone-mode lookup
  the Phone tab status did on every poll during a call.

## 9.3.71.2-pi02w (2026-10-06)

- Launcher version 2 (`/usr/local/bin/asl_dvs_launch.py`, the same file every ASL-DVS `--install` writes) adds three memory savers, each with an off switch. Create the file and restart the service to turn one off; delete it and restart to turn it back on.
  - `python3 -OO`: drops docstrings from the loaded code. Off: `/etc/asl_dvs/launch_no_optimize`
  - `MALLOC_ARENA_MAX=2`: at most 2 malloc pools instead of up to 8 per CPU core. Off: `/etc/asl_dvs/launch_no_arena_cap`
  - `malloc_trim`: 1 minute after start, then every 5 minutes, freed memory is handed back to Linux. Off: `/etc/asl_dvs/launch_no_trim`
  
  The service files are unchanged: the launcher starts Python once more with `-OO` and `MALLOC_ARENA_MAX` (same PID, so systemd notify and watchdog are not affected). The launcher itself is comment-stripped too.

- Repo copy is comment-stripped. The change history that was in the file's comments now lives in this changelog.


## Earlier history

Carried over unchanged from the comments of the files below.

### asl_dvs_dashboard_pi02w_v9_3_71_2_20261006.py (header comments)

```text
ASL-DVS Node Control  —  asl_dvs_dashboard.py  —  v9.3.71.2-pi02w  —  2026-10-06
KD8PGK / Claude AI (Anthropic)  —  CC BY-NC 4.0
Build: Pi Zero 2 W fork of v9.3.71

Same tabs and features as v9.3.71 (Phone
and every digital mode); lighter on memory and CPU for a 512 MB Pi:
  - ASL node search reads /var/lib/asterisk/astdb.txt from disk on each
    search instead of holding ~40,000 nodes in memory (was ~16 MB, 32 MB
    while the file was re-read).  One pass per file version records the
    node count, repeated nodes and lines with control characters, so a
    search only fully parses lines that could match (~30 ms here).
  - EchoLink station search: the `echolink dbdump` list is written to
    /run/asl_dvs_dashboard/echodb.txt (about 300 KB for 20,000 stations)
    and searched the same way, instead of a 2-5 MB in-memory list rebuilt
    every 5 minutes.  Refreshed on use when older than 5 minutes; a failed
    refresh keeps the last good file.
  Results are identical to v9.3.71 (same parsing, first line for a node
  wins, same order, same counts and totals).
  - Slower polling: the link/keyed poll of Asterisk runs every 2 s (was
    1 s; bridge up/down now after 2 polls, ~4 s, was 3 polls, ~3 s); the
    page refreshes every 5 s when idle (was 3 s; 1 s while busy is
    unchanged) and checks the TX/RX light every 1 s (was 0.5 s).
  - Launcher: the service starts through /usr/local/bin/asl_dvs_launch.py
    (shared with the Pi02w sysmon), which imports this file instead of
    running it, so Python keeps the compiled copy in __pycache__ and
    reuses it: about 25 MB settled instead of 45 MB, twice as fast to
    start.  --install clears compiled copies of older versions;
    --uninstall removes this one and, when unused, the launcher.
  v9.3.71.2-pi02w: Launcher version 2 (the same file every ASL-DVS
    --install writes): three memory savers, each with an off switch --
    python3 -OO (drops docstrings from the loaded code; off:
    /etc/asl_dvs/launch_no_optimize), MALLOC_ARENA_MAX=2 (at most 2
    malloc pools instead of up to 8 per CPU core; off:
    /etc/asl_dvs/launch_no_arena_cap) and malloc_trim every 5 minutes
    (freed memory handed back to Linux; off:
    /etc/asl_dvs/launch_no_trim).  Create the file and restart the
    service to turn one off.  The service files are unchanged; the
    launcher starts Python once more with -OO and MALLOC_ARENA_MAX (same
    PID).
  v9.3.71.1-pi02w: --uninstall also removes the EchoLink cache folder
    /run/asl_dvs_dashboard, and no longer stops part-way if a compiled
    copy or the launcher is already gone.
```
