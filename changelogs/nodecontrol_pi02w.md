# Dashboard, Pi Zero 2 W build changelog

Current file: `nodecontrol_pi02w_v9_3_79_20261018.py`. Before 9.3.76 / 9.3.71.15-pi02w the file was `asl_dvs_dashboard[_pi02w]_v….py` and this log was `asl_dvs_dashboard[_pi02w].md`. Newest entries first.

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
