# Dashboard, full build changelog

Current file: `nodecontrol_v9_3_86_20261019.py`. Before 9.3.76 / 9.3.71.15-pi02w the file was `asl_dvs_dashboard[_pi02w]_v….py` and this log was `asl_dvs_dashboard[_pi02w].md`. Newest entries first.

## 9.3.86 (2026-10-19)

Node Listen support, ported from the Pi02w build (9.3.86, 9.3.87, 9.3.89 and
9.3.90-pi02w). Behaviour is the same as there.

- **Listen button** next to the connection indicator in the quick-link row (on a
  phone, beside the indicator). It opens Node Listen in its own tab and reuses that
  tab on later presses, so playing audio keeps playing. It is greyed out when Node
  Listen isn't running. The page asks the new `GET /api/nodelisten-status` at start;
  the server reads the port from `/etc/asl_dvs/nodelisten.conf` (default 8993) and
  checks it answers on 127.0.0.1, cached 15 s. The Dashboard names its own tab, so
  Node Listen's Node Controller button can switch back to it.
- **Node Listen's transmit node (1921)** is kept out of the Dashboard's link
  handling when rpt.conf has the `; nodelisten: transmit node` line right above
  `[1921]`: never shown as the connected node or an extra link; kept by Disconnect,
  tab switches and teardowns while Node Listen runs (relinked after the `ilink 6`
  fallback); unlinked by the poll, at most once every 30 s, when Node Listen isn't
  running. A node 1921 of your own is handled as before.
- **Local API for Node Listen:** `POST /api/local/action`, accepted only from
  127.0.0.1 / ::1 with the `X-ASL-DVS-Local-Key` header matching
  `/etc/asl_dvs/local_api.key` (made at start if missing, mode 0600). `connect`
  (ASL or EchoLink; switches tab first when needed, then the tab's own Connect) and
  `disconnect` (bridge nodes and 1921 refused). Refused requests are logged.

## 9.3.85 (2026-10-19)

The full-build port of 9.3.88-pi02w's IAX port fix.

- **`bindport` in an included file.** The Phone tab writes its nodes' `[nodes]`
  lines as `radio@127.0.0.1:<bindport>/<node>` when iax.conf's `bindport` isn't
  4569. A `bindport` set in a file pulled in with `#include` / `#tryinclude`
  under `[general]` was missed unless that file had its own `[general]` line, so
  the Dashboard used 4569 and the Phone nodes couldn't link. An included file now
  carries on in the section it was included from, as Asterisk reads it.

## 9.3.84 (2026-10-18)

The full-build port of Pi Zero 2 W Dashboards 9.3.78-pi02w to 9.3.85-pi02w: the
tab layout clean-up, the Connect-button service warnings and the M17 changes. The
page is the same as the fork's apart from the full build's existing differences
(3-second idle poll, 500 ms keyed poll, one Phone help line).

- **Top rows removed.** ASL, Echo, STFU, YSF, P25, NXDN, FCS, D-STAR, XLX and M17
  keep only their search row. When nothing is picked from the menu, Connect (or
  Enter in the search box) takes what the old row took: a node number (ASL, Echo), a
  talkgroup or ID number (STFU, P25, NXDN), a `host:port` address (YSF), a reflector
  or gateway callsign with an optional module (D-STAR, XLX). FCS and M17 have no
  search box and use their menus only. The search box stays usable when its list is
  missing.
- **Save** falls back to the typed number and then the last one connected on ASL,
  Echo, STFU, P25 and NXDN, and takes a typed reflector or callsign on D-STAR.
- **LH.** ASL, Echo and STFU open the Edit tab's Last Heard address. FCS opens the
  picked server's page, else the Edit tab's FCS address. M17 opens the reflector's IP
  address (`http://<ip>/`, no port; `/api/m17-hosts` rows carry a new `ip` field).
- **DMR** keeps its row; its Tune button is now Connect, like the FCS, D-STAR and XLX
  buttons. No button says Tune any more.
- **Connect warnings.** A 15 s background check (only when DVSwitch is found) of
  Analog_Bridge, STFU, YSFGateway, P25Gateway, NXDNGateway, ircDDBGateway and
  USRP2M17 in one `systemctl show` call goes out in the status reply (`svc`). Each
  tab's Connect shows red with a strike-through, and a hover note, when its service
  or Analog_Bridge isn't running. Not installed or unknown shows no warning. The
  ASL "not registered" warning moves from Tune to Connect.
- **Leaving the M17 tab runs M17's Disconnect first** (bridge-node link, placeholder
  ini, USRP2M17 restart), before anything else in the switch. Edit doesn't change the
  server's page, so M17 stays connected on Edit.

## 9.3.83 (2026-10-14)

The full-build port of Pi Zero 2 W Dashboards 9.3.74-pi02w and 9.3.75-pi02w
(reliability plan, Stages 2 and 7). The code is the same as the fork's. The
only difference is the full build's 1-second poll.

- **A systemd watchdog that checks the right things.** Before, the link-poll
  loop said "alive" at the top of each poll. A hung web server went
  unnoticed. A frozen Asterisk holding the poll on AMI could get the
  Dashboard restarted. With no ASL and no DVSwitch nothing said "alive" at
  all, so systemd restarted the Dashboard every 30 s. Now a `sd-heartbeat`
  thread says "alive" (every 10 s, `WatchdogSec=30` unchanged) only while:
  - the poll loop started a pass in the last 120 s (or isn't running), and
  - the Dashboard answered its own `GET /healthz` within 25 s (the
    `health-probe` thread asks every 10 s on 127.0.0.1).
- **`/healthz`** (new, no login): the same `{"ok":true}` as `/api/ping`.
  instmon 2.50.0 uses it after an update.
- **The poll no longer queues behind a stuck AMI command.** Its read waits at
  most 3 s for the AMI lock, then skips that poll and leaves the page state
  alone. Page commands still wait for the lock. The `asterisk -rx` fallback
  still runs outside the lock.
- The link-mode table is replaced in one step, and `USRP2M17.ini` is forced
  to disk before it replaces the old file.
- **Registration status for alerts:** after every AllStarLink registration
  check, the Dashboard writes `/run/asl_dvs/asl_reg.json` (node, state,
  since, checked_at, next_check_secs). wifimon 5.34.0 reads it for its
  "registration lost" alert. Nothing changes on the page.
- Tested: the same unit tests as the fork, run against this file (12):
  - the AMI lock wait, the fallback outside the lock, the lock released on
    errors
  - the poll loop keeps going while AMI is held
  - the heartbeat rules, with a real server and a real notify socket
  - `/healthz` public, `/api/status` not
  - the link-mode swap, the M17 file write and fsync
  - the registration file contents, mode 644, and an unwritable path
  - `ci/check_repo.py`

## 9.3.82 (2026-10-14)

The ASL tab's Tune button shows whether the node is registered with
AllStarLink, from the Pi Zero 2 W build (9.3.73-pi02w).

- New background check `asl-reg` asks Asterisk `rpt show registrations` (over
  AMI) and looks for the node set in Edit. It uses SysMon's rule:
  - a line naming the node with "unregist", "rejected", "failed", "timeout"
    or "timed out" → unregistered
  - a line naming the node with "regist" → registered
  - the node missing from the list → unregistered
  - Asterisk not answering → unknown
- `/api/status` carries the result as `asl_reg` (read from a cache).
- The Tune button next to the node number box:
  - registered or unknown: its normal teal look
  - unregistered: red border, red text with a line through "Tune", and the
    tooltip "Node N is not registered with AllStarLink". It can still be
    clicked.
- How often it checks:
  - every 30 s while the node is not registered (or the state is unknown);
    the Pi02w build uses 60 s
  - every 15 min once registered
  - again 5 s after a network change (an interface going down or up, or a
    Wi-Fi reconnect, read from `/sys/class/net/*/operstate` and
    `carrier_changes`), then every 30 s until registered
  - at once when the node number in Edit changes
- Tested:
  - Unit test with a mocked AMI: Registered, Rejected, node missing, no
    registrations, and AMI down give registered / unregistered / unregistered
    / unregistered / unknown. With a mocked clock: checks at 0, 30 and 60 s
    while unregistered, then backs off to 15 min, and a network change at
    600 s brings a check at 606 s.
  - The page in headless Chromium: registered teal `rgb(0,255,229)` with no
    line through; unregistered red `rgb(255,61,90)` with a line through and
    the tooltip; unknown teal. No script errors. `node --check` on the page
    script.

## 9.3.81 (2026-10-14)

The Phone tab carries a notice that sending music over a radio node breaks FCC
rules, from the Pi Zero 2 W build (9.3.72-pi02w).

- A boxed amber notice under the Phone tab's Hang Up / Keypad / Patch / Report
  bar:
  - music on an amateur station is prohibited by 47 CFR §97.113(a)(4), and
    that includes a phone system's hold music or a recording played into a call
  - §97.113(e) also bars retransmitting broadcast stations
  - hang up if a call goes to hold music
  - radioless nodes and phone systems with no RF link should be fine
- `BUILD_DATE` is 2026-10-14.
- Tested:
  - The page in headless Chromium: the notice shows on the Phone tab in amber
    `rgb(255,208,64)`, no script errors. `node --check` on the page script.

## 9.3.80 (2026-10-13)

Easier to read: the grey-blue text is white, successes are green and failures are
red, from the Pi Zero 2 W build (9.3.71.18-pi02w). Only text colours change.

- **Grey-blue to white `#ffffff`:**
  - `--text` (was `#d0dff0`), `--muted` (was `#4a6080`) and the Edit page's
    Back/Reload button text (was `#9ab8d0`)
  - the typed-in `#5a7898`, `#7a9ec0`, `#3a5278`, `#6f8aa8`, `#5a6b7c`,
    `#4a5a6a` and `#4a5a3a`
  - the shutdown sub-line `#c98a92`
- **Failures to bright red `--red`:** the error box, the alert bar, the shutdown
  message and a failed phone sign-in (they were pale pink or salmon), and a
  disconnected row's name (it was dark red).
- **Phone tab result line** under Apply, Activate and Revert: green when the step
  worked, red when it failed (the `phMsg` helper). It used to be grey-blue
  whatever the result.
- Toasts were already green and red. Warnings stay amber.
- The full build now uses exactly the same text colours as the Pi Zero 2 W build.
- **Tested** in headless Chromium, before and after: body text
  `rgb(255,255,255)`; the Phone result line green `rgb(0,255,176)` on success and
  red `rgb(255,61,90)` on failure; section labels white; no script errors.
  `node --check` on the page JavaScript.

## 9.3.79 (2026-10-13)

Phone audit fixes and the "Node Control" title, from the Pi Zero 2 W build
(9.3.71.17-pi02w). The same code as pi02w for these parts.

- **Edit page, network cards:** each card shows only its own hints.
  - The router hint shows only on SIP-type cards (it was on IAX2 cards too). It
    no longer tells everyone to forward ports: signing in usually keeps calls
    working, so forward UDP 5060 only if incoming calls don't arrive, and the
    audio ports only if audio is one-way.
  - A "SIP by IP address" network, which doesn't sign in, is told it needs the
    forward for incoming calls.
  - AmateurWire cards get their own Voicemail Access note instead of the Hams
    Over IP port hint.
- **Saved tones:** a favorite's saved tones (Straight to the provider and As
  sound routes) are sent if the call answers any time within the 65-second ring
  time. Before, the dashboard waited only the `*61` digit timeout plus 15 s (35 s
  by default).
- **Wording:**
  - "Dial timeout (ms)" is now "*61 digit timeout (ms)", with a tooltip. The
    setting and its saved value are unchanged.
  - Incoming-call status: an open network with trusted numbers says "trusted
    numbers only"; a PIN network with trusted numbers says "waiting for PIN
    (trusted numbers skip it)".
  - The Send keypad tones choices drop the "(v9.3.13 way)" and "(test)" tags.
- **Naming:** the page title, logo, login heading and console banner say "Node
  Control" (no "ASL-DVS"). The service description, the command-line help, the
  phone report and the config files the dashboard writes are unchanged.
- **Tested:**
  - In headless Chromium, the hints for each network type (SIP, SIP by IP, Hams
    Over IP, AmateurWire, IAX2), the label, the tone choices and the titles, with
    no script errors.
  - Saved-tones wait with a simulated clock: answered at 50 s, sent at 51 s
    (9.3.78 gave up).
  - `node --check` on the page JavaScript.

## 9.3.78 (2026-10-13)

Two layout fixes from the Pi Zero 2 W build (9.3.71.12-pi02w and 9.3.71.13-pi02w).

- **Edit page, Phone tab:** the network cards line up on tablet-width screens
  (about 560 to 1200 px).
  - Fields in a row sit on a common bottom line, so a field whose label wraps
    to two lines no longer pushes its box lower.
  - The checkbox rows have the height of a box and sit level with it.
  - The favorites rows use the same columns and gap as the field grid, with the
    clear (✕) button inside the "Then send" cell.
  - The phone layout is unchanged, and so is what is saved.
- **M17 favorites:** the module drop-down is 7.6 rem wide on the M17 grid and the
  M17 quick bar, so "All Modules" is no longer clipped to "All Modu". D-STAR and
  XLX keep the narrow box.
- Tested in headless Chromium at 390, 800 and 1200 px: the M17 drop-down is
  121.6 px (7.6 rem), and the favorites rows render with the new tone cell. No
  script errors; `node --check` on the page JavaScript.

## 9.3.77 (2026-10-12)

The USRP2M17 quick-link button is now an **InstMon** button. The same change is in the Pi Zero 2 W build (9.3.71.16-pi02w).

- The right-hand quick links are now InstMon, WiFiMon and SysMon. InstMon has
  the same look as the other quick-link buttons and opens instmon
  (`http://<host>:8990/`) in a new tab.
- The M17 tab is unchanged.
- File: `nodecontrol_v9_3_77_20261012.py`.

## 9.3.76 (2026-10-12)

The Dashboard is now named **nodecontrol**. The same change is in the Pi Zero 2 W build (9.3.71.15-pi02w).
Needs instmon 2.43.0 or later to show it under the new name.

- File: `nodecontrol_v9_3_76_20261012.py` (was `asl_dvs_dashboard…`).
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
- Tested with mocks against a temporary root: a fresh node, a node on the old
  service with the file in the old flat folder or in `dashboard/`, the new
  layout, installing through either link, and uninstall with a stray old unit;
  another tool's folder survives each time.

## 9.3.75 (2026-10-12)

Standard install layout (same as instmon 2.40.0, wifimon 5.29, 44helper 0.0.180
and SysMon). The same change is in the Pi Zero 2 W build (9.3.71.14-pi02w).

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

## 9.3.74 (2026-10-11)

- M17: USRP2M17 now listens on UDP 17010 for reflector traffic (`LocalPort` in
  `[M17 Network]` of `USRP2M17.ini`), was 32010. Same fix as Dashboard Pi02w
  9.3.71.11: MMDVM_Bridge's stock `[P25 Network]` also listens on 32010, so both
  programs could hold the port at once and reflector packets could reach
  MMDVM_Bridge instead of USRP2M17. The new port is written the next time the
  dashboard connects or disconnects an M17 reflector. Reflectors answer the port
  USRP2M17 sends from, so nothing else needs to change.
- Tested: the `USRP2M17.ini` text the dashboard writes now has `LocalPort=17010`.

## 9.3.73 (2026-10-06)

Phone tab brought level with the Pi Zero 2 W build (Dashboard Pi02w 9.3.71.3 to
9.3.71.10). The phone code is now the same in both builds; see
`changelogs/asl_dvs_dashboard_pi02w.md` for each step in detail.

- Simplex and hang time always use the defaults. The Edit page's Simplex box, its
  VOX/delay fields and Hang time are gone. Phone nodes always get `duplex = 1` and
  the default VOX lines (`voxtimeout = 10000`, `voxrecover = 2000`,
  `simplexpatchdelay = 25`, `simplexphonedelay = 25`).
- The five programmable tone buttons and radio codes *983-*987 are gone; *980 (*),
  *981 (#) and *982 (*99) stay. The keypad pop-up is the keys, tones sent and the
  call check; "Send keypad tones" moved to the Edit page.
- Keypad tones on every SIP network go as tone packets (RFC 2833); the Tone mode
  picker is gone.
- The Hams Over IP AllStar Link card and everything behind it (incoming IAX2
  account, `[dvs-hoiplink]` dialplan, dial-string button, Phone tab caller row) are
  removed.
- Sign-in is always "Picked network only"; the Sign in picker and each network's
  register box are gone.
- New "Listen only" box: phone nodes link to the radio node as monitor links
  (`ilink 2`), so nothing from the radio goes into calls. The link watchdog relinks
  in the right mode.
- The favorite in use lights up on the Phone tab, for calls you dial and incoming
  calls from a favorite's number; Test call and Voicemail rows too.
- Calls dialed from the dashboard use AMI `Originate` into `rpt(<node>,Pv)` instead of
  autopatch, so a simplex radio keys only while the far end talks (no dead key).
- `*61` from the radio hands the number to the dashboard through a new
  `dvs-radio-<network>` context and `/var/lib/asterisk/dvs_phone_dialreq`, so
  radio-dialed calls work the same way. `app_system.so` joins the phone modules.
- `*65` runs the hang-up script like `*62`; Hang up also cancels a radio dial still
  collecting digits. New "How calls from the radio work (show/hide)" note on the Edit
  page.
- The start-up refresh rewrites the phone parts of `rpt.conf`, the dialplan, the SIP
  and IAX2 files and the scripts on the first start of this build.

## 9.3.72 (2026-10-06)

- No code change from 9.3.71. Repo copy is comment-stripped. The change history that was in the file's comments now lives in this changelog.


## Earlier history

Carried over unchanged from the comments of the files below.

### asl_dvs_dashboard_v9_3_73_20261006.py (header comments, as of 9.3.71)

```text
ASL-DVS Node Control  —  asl_dvs_dashboard.py  —  v9.3.72  —  2026-10-06
KD8PGK / Claude AI (Anthropic)  —  CC BY-NC 4.0
```

### asl_dvs_dashboard_v8_0_3_20260822.py (older copy kept in the repo, stripped in place)

```text
ASL-DVS Node Control  —  asl_dvs_dashboard.py  —  v8.0.3  —  2026-08-22
KD8PGK / Claude AI (Anthropic)  —  CC BY-NC 4.0

v8.0.3: startup() no longer forces an ASL disconnect-all or an idle-mode
DVS retune on every dashboard process restart -- only on a genuine fresh
system boot (detected via /proc/sys/kernel/random/boot_id + a /run
marker, see _is_fresh_boot()). This was previously running unconditionally
on EVERY restart of asl_dvs_dashboard.service: the external watchdog's
restart, systemd's own Restart=always/WatchdogSec=30, and manual
`systemctl restart` all funneled through the same code path and would
hard-drop live ASL links (and blip-retune live DVS links) even though
Asterisk/Analog_Bridge themselves never went down -- only this process did.
```
