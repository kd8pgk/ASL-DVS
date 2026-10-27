# wifimon changelog

Current file: `wifimon_v5_39_1_20261027.py`. Newest entries first.

## 5.39.1 (2026-10-27)

- **Login splash.** The login screen opens with "Welcome to the KD8PGK WiFi Monitor" above the login card, and the CC BY-NC 4.0 license at the bottom. The callsign comes from `/etc/asl_dvs/asl_dvs.conf` when the page is served, so the page reads it on every load.

## 5.39.0.3 (2026-10-27)

- **Header and page names.** The header, the login card and the page title read "WiFi Monitor". Cosmetic only; no change in behaviour.
- The header sub-line drops "Node Control".

## 5.39.0.2 (2026-10-27)

- **The Node Control look.** wifimon now uses the Node Control colours, with amber, blue, green and red matched to the other tools. The text is Readex Pro (built into the page), not the system font. The header has the Node Control logo and sub-line, buttons are uppercase on the shared size scale, and cards have the same corners. The login page follows the same look. Cosmetic only; no change in behaviour. Readex Pro is Copyright 2019 The Readex Pro Project Authors, under the SIL Open Font License 1.1.

## 5.39.0.1 (2026-10-19)

- **The login screen matches instmon's.** A centered card over a dark,
  blurred background, an amber "wifimon Login" title, a "Root password"
  field and a LOG IN button, with errors in red under it. The Service card's
  button now reads "Log Out". Cosmetic only: the login itself works as before.

## 5.39.0 (2026-10-19)

- **Code cleanup, no change in behaviour.** The WiFi country is read by one
  helper instead of two identical copies.

## 5.38.0 (2026-10-18)

Phase 1 of the boot audit. wifimon serves both builds.

- **Keep off through NetworkManager.** 5.37.0's boot unit raced NetworkManager: it
  started at the same moment NetworkManager began connecting, so it mostly undid a
  connection instead of preventing it (magicbox: NetworkManager joined KD8PGK004 on wlan0
  at 33 s, "network online" was reached on it, and wifimon dropped it at 36 s). Now a
  Keep-off adapter is listed in `/etc/NetworkManager/conf.d/90-wifimon-keepoff.conf`
  (`[keyfile] unmanaged-devices+=mac:<permanent MAC>`, or `interface-name:` for an adapter
  without one), so NetworkManager never uses it, from the start of every boot, and
  "network online" waits for the adapter you use. The setting applies at once
  (`nmcli general reload conf`, `device set … managed no`) and is removed when the
  adapter goes back to Auto or Keep on. The 5.37.0 unit is removed. If a Keep-off adapter
  is the only WiFi adapter left, wifimon lets NetworkManager use it until the next boot.
  Uninstall removes the file.
- **The adapter you use connects at once.** wifimon waited 30 s for NetworkManager to
  rejoin by itself even at boot; NetworkManager didn't, so wlan1 came up only at 66-72 s.
  In the first 10 minutes after boot, when the watched adapter is idle (disconnected, not
  connecting), wifimon now reconnects straight away. After a runtime Keep-off disconnect
  it asks NetworkManager to connect the watched adapter at once. At start it waits up to
  10 s for the saved adapter to appear before falling back to another.
- **No false "Network lost" at boot.** Until the first connection after boot it logs
  "No network yet after boot -- waiting" and doesn't count a drop (the shutdown/reboot
  grace is unchanged).
- **Tunnel watchdog:** while 44helper's late follow-up (`44helper-netready-late`) is
  running it leaves the DVSwitch restart to it (no double restart); a tunnel restart may
  take up to 240 s (the clock wait alone can take 90 s), so it isn't counted as failed
  too early.
- Tested: the watchdog suite and new checks (45): Keep off writes, reads back, reloads
  and unmanages; same mode again does nothing; Auto removes it and manages the adapter;
  `if:` keys; the 5.37.0 unit removed; the only adapter is managed again; a kept-off
  adapter is left alone; runtime disconnect then immediate connect; the boot head start
  skip; no double DV restart during the late follow-up.

## 5.37.0 (2026-10-18)

From magicbox's boot report. wifimon serves both builds.

- **Keep off holds from the start of the boot.** Keep off used
  `nmcli device set … autoconnect no`, which NetworkManager forgets at a reboot, so at
  boot NetworkManager brought the Keep-off adapter up, the tunnel started through it,
  and wifimon disconnected it 13 s later, which took the tunnel server's route with it
  (a routing loop). While any adapter is set to Keep off, wifimon now installs
  `wifimon-keepoff.service` (`/usr/local/sbin/wifimon-keepoff`). It runs right after
  NetworkManager starts and before `network-online.target`, so before the tunnel:
  for each Keep-off adapter (found by its permanent MAC, as wifimon does) it sets
  autoconnect off and disconnects it if it is connecting. It waits up to 20 s for the
  adapters to appear, and leaves an adapter alone when it is the only one. When no
  adapter is set to Keep off any more, the unit is removed. Uninstall removes it too.
- **Tunnel watchdog: a routing loop is fixed at once.** A loop (the tunnel server
  routed into wg0) is definite and the fix only adds a route, so the watchdog no longer
  waits for 3 bad checks: it re-adds the route at the first check. During the wait
  after boot it also fixes a loop (route only; nothing restarted), then leaves the
  rest to the boot order.
- Tested: the Keep-off script against a fake `/sys/class/net` with a stub nmcli
  (connecting adapter disconnected, missing adapter waited for, only adapter left
  alone), the unit written, enabled and removed as modes change, and the watchdog
  suite (35 checks: loop at the first check, loop during the boot wait, no LAN
  route).

## 5.36.0 (2026-10-18)

Fixes from a boot audit. wifimon serves both builds.

- **Fix: false routing loop on every full tunnel.** The tunnel watchdog's loop check
  ran `ip -4 route get <server>` without WireGuard's firewall mark. With a full
  tunnel, wg-quick's rules send every unmarked lookup to wg0, so a healthy tunnel
  looked like a loop. About 8 minutes after each boot the watchdog would add a
  stray route, send a false "Tunnel has no handshake" alert and restart all the
  DVSwitch services. The check now adds `mark <fwmark>` (from
  `wg show wg0 fwmark`) when the tunnel has one, which is how WireGuard's own
  packets are routed.
- **No keepalive: probe before acting.** A tunnel without `PersistentKeepalive` only
  handshakes when something sends traffic, so an idle split tunnel could show "no
  handshake yet" or an old handshake while working fine. The watchdog now sends one
  ping into the tunnel (to 44.0.0.1), waits 6 s and checks again; only if there's
  still no fresh handshake does it count as bad. With a keepalive set, nothing
  changes.
- **Lost-network shutdown/reboot waits 10 minutes after boot.** After a power cut the
  router can take longer to start than the Pi, and the WiFi watchdog could shut down
  or reboot the Pi while the router was still booting. Now it doesn't act until the
  Pi has been up 600 s (logged once).
- Tested: the 5.35.0 suite plus full tunnel healthy (no loop, lookup uses the mark),
  no keepalive with a probe that brings a handshake (no restart) and one that
  doesn't (restart), an old handshake without keepalive, and the boot grace.

## 5.35.0 (2026-10-18)

**Tunnel watchdog.** A node's 44Net tunnel (set up by 44helper) could come up after a
reboot with no handshake (for example a routing loop), and the DVSwitch services
then had no connection, until someone fixed it by hand. wifimon now watches the
tunnel and fixes it. wifimon serves both builds.

- **On by default.** A new **Tunnel watchdog** card shows the state, the last
  handshake, tries this boot, the next try and the last action. **Settings**: on/off,
  failed checks before acting (2–10, default 3), wait after boot (60–1800 s,
  default 300), and restarting the DVSwitch services after a fix (default on).
  Saved in `/etc/wifimon/tunnel_guard.json`; the state is also written to
  `/run/asl_dvs/tunnel_guard.json` for other tools.
- **Checks every minute**, only when `/etc/wireguard/wg0.conf` exists and
  `wg-quick@wg0` is enabled, the Pi has been up longer than the wait after boot,
  there's a normal (non-wg) default route, and no 44helper half-tunnel or
  exceptions test is running. A tunnel you stopped is left alone; one that systemd
  is still starting or retrying is waited for.
- **Counts as bad:** the unit failed; wg0 missing; no handshake ever; a handshake
  older than 3 minutes when a keepalive is set (without one a quiet tunnel can just
  be idle); or the tunnel server routed into wg0.
- **After the failed checks:**
  1. A routing loop: re-adds the tunnel server's /32 on the normal route (a live
     route only; wg0.conf is never edited) and waits a minute for a handshake.
  2. Otherwise, or if that didn't help: `systemctl restart wg-quick@wg0` (90 s
     limit) and waits a minute for a handshake.
  3. Handshake back: restarts netcheck, the bridges, md380-emu, STFU, the gateways,
     ircDDBGateway and webproxy that are enabled, in that order, so services that
     started without the tunnel reconnect.
  4. Still down: tries again after 10 min, 30 min, then hourly; at most 6 tries per
     boot. It never reboots.
- **Alerts:** a new "tunnel" event (in the Alerts card): "Tunnel has no handshake"
  (with a note that a remote session over a full tunnel may drop), "Tunnel is back",
  and "Tunnel watchdog gave up".
- Tested:
  - Unit tests (22) against a simulated system:
    - healthy: no action; no handshake: 2 checks watching, then a tunnel restart
      and the enabled DVSwitch services in order;
    - an old handshake without keepalive: no action; a loop: route fixed with no
      tunnel restart;
    - a restart that doesn't help: back-off, and it gives up after 6;
    - no action when stopped by hand, while systemd retries, during the wait after
      boot, without a network route, when not enabled, during a 44helper test, or
      when off;
    - a failed unit restarted after 2 checks with DVSwitch restart off;
    - the settings validation, defaults and alerts.
  - The settings handler: confirmation required, bad values refused, file mode 600.
  - The card in headless Chromium at 390 px: state and details, the settings form
    filled from the defaults, a bad value refused, a good one saved; no script
    errors, no horizontal scroll.

## 5.34.0 (2026-10-14)

Alerts: the node tells you when something goes wrong, instead of waiting for
you to open a page (reliability plan, Stage 7). wifimon serves both builds.

- **New Alerts card**, off until you turn it on.
  - Set up alerts -> Send with **ntfy** (the ntfy phone app; use a topic only
    you know, for example `https://ntfy.sh/<your-secret-topic>`) or a
    **webhook** (wifimon POSTs JSON: host, event, title, message, level, at).
  - An optional access token is sent as `Authorization: Bearer ...`. It is
    stored in `/etc/wifimon/alerts.json` (root only) and never shown again.
  - **Send test** sends one at once and says whether it got through.
  - The card shows whether alerts are on, how many are waiting, and the last
    send.
- **What sends an alert** (each can be turned off):
  - **Shutdown or reboot by wifimon.**
    - Low voltage: sent right away, with 5 s to try, before power-off.
    - Lost network: queued and sent after the reboot or the next power-on.
  - **Unclean stop:** after a power loss or a wifimon crash, sent once the node
    is back online.
  - **A service keeps restarting:** systemd restarted it 3 times in 10
    minutes. Covers the Dashboard, SysMon, instmon, 44helper, Asterisk,
    Analog_Bridge, MMDVM_Bridge and USRP2M17.
  - **Out-of-memory kill:** the kernel's kill counter went up; names the
    process when the kernel log has it.
  - **AllStarLink registration** lost for 5 minutes, and a "registered
    again" when it comes back. Read from the Dashboard's
    `/run/asl_dvs/asl_reg.json` (Pi Zero 2 W Dashboard 9.3.75 and later). On a
    node without that file the alert never fires, and nothing else changes.
- **Sending:** alerts made while offline wait in
  `/var/lib/wifimon/alerts_queue.json` (up to 50, for up to 24 hours) and go
  out once the node is online. At most one alert of each kind per 30 minutes
  (per service for restarts).
- Tested:
  - Unit tests (17), against a real HTTP receiver where sending is involved:
    - settings validation; the token kept, cleared, never in the page data;
      file mode 600
    - nothing sent while off or for a switched-off event
    - ntfy: title, priority, bearer token, UTF-8 text; webhook JSON
    - offline -> queued; server error -> stays queued; back -> sent and
      cleared
    - 30-minute repeat limit; the test alert bypasses it
    - old entries dropped, queue capped
    - restart loop: 3 in 10 minutes alerts, 3 spread over 20 minutes doesn't
    - OOM with the victim's name
    - registration: not before 5 minutes, then once, then "registered again";
      a stale or missing file is ignored
    - `systemctl show` parsing
    - low-voltage shutdown sends at once, a lost-network reboot queues
  - The card in headless Chromium:
    - off by default, Send test greyed out
    - saving with no address is refused
    - save with a token and one event off: the token never comes back to the
      page
    - Send test reached the local receiver with the token
    - no horizontal scroll at 390 px, no script errors
  - `ci/check_repo.py`

## 5.33.0 (2026-10-14)

Choose what happens when the network is lost: reboot (new, the default) or
power off (reliability plan, Stage 4). wifimon serves both builds.

- **New setting on the Watchdog card:** Change settings -> **When the network
  is lost**: Reboot or Power off.
  - **Default is Reboot**, also for nodes updating from an older wifimon. Before,
    a lost network always powered the node off, so a router that took more
    than 3 minutes to come back left a remote node off until someone visited
    it.
  - **Reboot** happens at most 3 times in 6 hours. After that the node stays
    up and keeps trying to reconnect; the timer reads "Reboot limit reached,
    still trying". When the oldest reboot is more than 6 hours old, one more
    reboot is allowed. The count is kept in
    `/var/lib/wifimon/net_reboots.json`, so it survives the reboots. On a Pi
    whose clock is behind after a reboot (no network, no real-time clock), the
    reboots still count, so it errs toward staying up.
  - **Power off** works as before (for battery or hotspot nodes).
  - **Low voltage** always powers off; this setting doesn't change that.
  - The time limit ("Reboot or power off after no connection for") is the
    same setting as before. Changing the action doesn't restart a countdown
    that is running.
- **On the card:**
  - the rules line says which action applies;
  - new row **Reboots for a lost network**: "1 of 3 in the last 6 hours (one
    frees up 14:05:10)";
  - the red banner says "This node is rebooting" for a reboot.
- The shutdown state and the shutdown report record the action. The report
  reason says "rebooting (reboot n of 3 allowed in 6 h)".
- Tested:
  - Unit tests with mocks (12):
    - the reboot record: the 6-hour window, a clock that is behind, bad files
    - Power off; Reboot counting 1, 2, 3, then refusing the 4th
    - `do_shutdown` runs `systemctl reboot` / `reboot -f`, or `poweroff` for
      low voltage
    - the setting validates, defaults to Reboot, and doesn't restart the
      countdown
    - the real monitor loop with the network down: reboots; powers off; at
      the limit it stays up and clears the hold on reconnect; it reboots
      again once the oldest reboot leaves the window
  - The page in headless Chromium: the rules line for both actions, the
    reboot-count row, the dropdown with its hint, Save writes
    `network_loss_action`, the held timer text, the reboot banner, no
    horizontal scroll at 390 px, no script errors.
  - `ci/check_repo.py`

## 5.32.0 (2026-10-14)

Two watchdogs over wifimon itself and the whole Pi (reliability plan, Stage 1).
wifimon serves both builds; nothing changes in the full build's files.

- **Hardware watchdog (new setting, default on).** The Pi's watchdog chip
  reboots the node if Linux freezes for 15 seconds. systemd feeds the chip
  while the system runs; wifimon only switches this on or off.
  - wifimon writes `/etc/systemd/system.conf.d/90-asl_dvs-hwwatchdog.conf`
    (`RuntimeWatchdogSec=15s`, `RebootWatchdogSec=2min`) and runs
    `systemctl daemon-reexec` so it takes effect at once. It runs it only
    when the file changed.
  - Watchdog card -> Change settings -> **Reboot the Pi if it freezes
    (hardware watchdog)**. Off removes the file (only if wifimon wrote it).
  - The Watchdog card shows **Hardware watchdog**: on (with the time), off,
    "not found on this Pi" (no `/dev/watchdog`), or "run by
    watchdog.service" (wifimon then leaves the chip alone).
  - `--install` applies the saved choice (on when never set); `--uninstall`
    removes the file. The startup of the service applies it too, so it stays
    in step with the setting.
- **wifimon has its own systemd watchdog.** The unit is now `Type=notify`
  with `WatchdogSec=60`. A small thread tells systemd "alive" every 15 s,
  but only while the monitor loop has started a pass in the last 180 s. If
  the loop hangs, the web page may still answer, but systemd restarts
  wifimon within about 4 minutes. Before, a hung loop went unnoticed. The
  activity log says when the loop stalls.
- Tested:
  - Unit tests with mocks (14): the file is written once and `daemon-reexec`
    runs once; off removes it; a file wifimon didn't write is left alone; no
    `/dev/watchdog`; watchdog.service running; a failed reexec is reported;
    the time parser; the setting validates, saves, resets to on and does
    not restart the countdowns; the unit lines; the "alive" messages stop
    while the loop is stale and resume when it runs again (real Unix
    socket); the loop's heartbeat stops while a check blocks.
  - The page in headless Chromium: the four Hardware watchdog states, the
    new checkbox (checked by default, with its hint), no horizontal scroll
    at 390 px, no script errors.
  - `node --check` on the page JavaScript, `py_compile`, `pyflakes`,
    `ci/check_repo.py`.
- Not testable here: a real freeze on a Pi. On the node: `wdctl` shows the
  timeout, and `systemctl show -p RuntimeWatchdogUSec` shows `15s`.

## 5.31.0 (2026-10-13)

Easier to read: the grey-blue text is white, successes are green and failures are
red, as in 44helper, SysMon and the Dashboard. wifimon serves both builds. Only
colours change.

- **Versions:** from now on, three-part numbers (5.30 -> 5.31.0).
- **Grey-blue text is now plain white `#ffffff`:**
  - `--text` (was `#e8eef5`) and `--muted` (was `#c6d3e0`)
  - the job banner (was `#dff7fd`)
  - the Disconnect / danger buttons (was `#ffdede`)
- **Bright green and red, the same shades as the other tools:**
  - success `--good` (was `#52d17f`) -> `#00ffb0`
  - failure `--bad` (was `#f06464`) -> `#ff3d5a`

  This colours the signal and status values, badges, the timer, log errors and
  the meter.
- **Pop-up messages:** green text and border on success; red text and border on
  failure. Before, every pop-up had white text and only the border changed.
- **The red alert banner:** its text is now red (was pale pink).
- Warnings and the pending banner stay amber.
- Tested:
  - The page in headless Chromium, before and after: body text
    `rgb(255,255,255)`; success and success pop-up `rgb(0,255,176)`; failure,
    failure pop-up and alert banner `rgb(255,61,90)`; no script errors.
  - `node --check` on the page JavaScript.

## 5.30 (2026-10-12)

- Launcher version 3, the same text instmon 2.43.0, 44helper 0.0.181, SysMon
  Pi02w 6.13.67.13 and Dashboard Pi02w 9.3.71.15 write: a tool file whose name
  starts with a digit (`44helper_v….py`) is loaded through `importlib`, so its
  compiled copy in `__pycache__` is used instead of being recompiled each start.
  Nothing else changed in wifimon.

## 5.29 (2026-10-12)

Standard install layout (same as instmon 2.40.0): the program lives in
`/usr/local/lib/asl_dvs/wifimon/` under its own versioned name, and
`/usr/local/bin/wifimon.py` is a symlink to it. The unit and its `ExecStart`
are unchanged.

- `--install` copies the file to `/usr/local/lib/asl_dvs/wifimon/` and points
  `/usr/local/bin/wifimon.py` at it. An old plain copy at that path is replaced
  in one rename, so the path is never missing, and any other version left in the
  lib folder is removed. Running `--install` through the link changes nothing.
- `--uninstall` removes the link, the lib file, and the lib folder (and
  `/usr/local/lib/asl_dvs/` if that is then empty). Configs, shutdown reports and
  the 30-minute "Stop chip roaming" carry-over work as before.
- Rolling back to 5.28 or older: run this version's `--uninstall` first, as
  Full Update does. instmon 2.40.0 also turns the link into a plain file before
  any older `--install`, so an older copy never lands inside the lib file.
- Tested with mocks against a temporary root: a fresh install, an install over
  an old plain copy and over a newer layout, reinstall through the link, and
  uninstall.

## 5.28 (2026-10-07)

- More details: the groups (Connection, Signal, Network and so on) each sized
  their own key column, so on a two or three column screen the values started at
  different places (200, 193 and 182 px down one column). Every group now uses the
  same key column, so all the values line up. Long keys wrap inside it.
- "Stop chip roaming" survives an update. Uninstalling wifimon removes
  `/etc/modprobe.d/wifimon-brcmfmac.conf`, and instmon's Full Update and Update
  uninstall before they install, so an update silently undid the setting (the
  watchdog's power-save and login-page settings were already re-applied at every
  start from `wifimon.conf`).
  - `--uninstall` saves the file's text in `/etc/wifimon/roam_restore.json` (mode
    600, with the time) and still removes the file.
  - `--install` writes it back if that copy is under 30 minutes old and no roaming
    file exists, then deletes the copy. A real removal, or a fresh install much
    later, does not bring it back by surprise. Only a file wifimon wrote is ever
    saved or written.
  - The first update from 5.27 or older still runs the old uninstall, which saves
    nothing, so it applies from the update after this one. The 44helper reinstall
    job never uninstalls, so it was never affected.
- Tested: 11 checks of the save and put-back logic against the real
  `install_service` and `uninstall_service`; the real installers of every tool
  and the real reinstall job run end to end in a sandbox with `systemctl` stubbed.

## 5.27 (2026-10-07)

- Page layout, found checking the grid on a Galaxy Tab S6 Lite:
  - **Saved networks:** a network that is not in the watchdog's reconnect list has
    no up and down arrows, so its number and name started about 80 px to the left
    of the other rows. It now keeps the same space (hidden arrows), so the number
    and name line up on every row.
  - **Cards:** the full-width Activity log sat between Watchdog and Service, which
    left each of them alone in a half-empty row on a two-column screen (about
    600 to 960 px). The Service card now comes before the Activity log: Watchdog
    and Service share a row at two columns, and at three columns (964 px and up)
    the Activity log fills the row beside Service. The page reads in the same
    order, with the Activity log last.
- Checked in headless Chromium at 390, 600, 800, 980 and 1280 px with a full
  status (connected, three saved networks, scan list, two adapters): the old page
  fails both checks from 600 px up, the new page passes. No change to what the
  page does.

## 5.26 (2026-10-06)

- The WiFi watchdog only runs while at least one network is saved in its
  reconnect list (`/etc/wifimon/wifimon.conf`). With none, it is on hold even when
  switched on: no shutdown timer, no reconnects. Removing the last network stops a
  timer that is already running (on the next check); adding one starts the watchdog.
  The voltage watchdog is not affected.
- Page: the card reads "On, waiting for a saved network", the No connection timer
  reads "No saved networks", and the rules line says why. The popup and the
  turn-on confirm say the WiFi watchdog waits until a network is added. The status
  API has a new `wifi_active` field (switch on and networks saved).

## 5.25 (2026-10-06)

- Watchdogs off on a first install. A fresh `--install` (no
  `/etc/wifimon/wifimon.conf` and no `state.json` yet) starts wifimon with both
  watchdogs off: it runs, shows status and voltage, but doesn't reconnect the WiFi
  or shut the node down. A reinstall, an update or instmon's Full Update keeps
  the watchdogs as they were (`--uninstall` keeps `/etc/wifimon`), and a node
  that has no saved choice keeps both on, as before.
- Popup to turn them on. After login, while a watchdog is off, the page asks
  "Turn the watchdogs on?" with a tick box for each one that is off, and says
  so when no WiFi networks are saved yet. "Not now" closes it until the next
  browser session.
- On/off switches in the Watchdog card: **WiFi watchdog** (reconnects and the
  no-connection shutdown) and **Voltage watchdog** (the low-voltage shutdown),
  each with a confirm. The timers read "Watchdog off" and the rules line says
  what is off. Saved in `/etc/wifimon/state.json` (`watchdogs`); new API
  `POST /api/watchdogs` (login and same-page check as the other changes);
  each change is logged. "Reset to defaults" in Watchdog settings doesn't
  touch these switches.

## 5.24 (2026-10-06)

- Launcher version 2 (`/usr/local/bin/asl_dvs_launch.py`, the same file every ASL-DVS `--install` writes) adds three memory savers, each with an off switch. Create the file and restart the service to turn one off; delete it and restart to turn it back on.
  - `python3 -OO`: drops docstrings from the loaded code. Off: `/etc/asl_dvs/launch_no_optimize`
  - `MALLOC_ARENA_MAX=2`: at most 2 malloc pools instead of up to 8 per CPU core. Off: `/etc/asl_dvs/launch_no_arena_cap`
  - `malloc_trim`: 1 minute after start, then every 5 minutes, freed memory is handed back to Linux. Off: `/etc/asl_dvs/launch_no_trim`
  
  The service files are unchanged: the launcher starts Python once more with `-OO` and `MALLOC_ARENA_MAX` (same PID, so systemd notify and watchdog are not affected). The launcher itself is comment-stripped too.

- The check that a pending change's undo record is a dict no longer uses `assert` (`python3 -OO` skips asserts).

- Repo copy is comment-stripped. The change history that was in the file's comments now lives in this changelog.


## Earlier history

Carried over unchanged from the comments of the files below.

### wifimon_v5_24_20261006.py (header comments)

```text
"""
wifimon.py — WiFi & Voltage Watchdog + Dashboard for Raspberry Pi Zero 2W
Version: 5.24 (Launcher version 2: memory savers)
Build: common (all nodes, including Pi Zero 2 W)

Monitors wifi connectivity and supply voltage.
Triggers a clean system shutdown on:
 1. Sustained low voltage (undervoltage protection).
 2. Sustained network connection loss.
Serves a web dashboard on port 8991 (plain HTTP by default, root-password login).

v5.24 — Launcher version 2 (the same file every ASL-DVS --install writes): three memory savers, each with an off switch -- python3 -OO (drops docstrings from the loaded code; off: /etc/asl_dvs/launch_no_optimize), MALLOC_ARENA_MAX=2 (at most 2 malloc pools instead of up to 8 per CPU core; off: /etc/asl_dvs/launch_no_arena_cap) and malloc_trim every 5 minutes (freed memory handed back to Linux; off: /etc/asl_dvs/launch_no_trim).  Create the file and restart the service to turn one off.  The service files are unchanged; the launcher starts Python once more with -OO and MALLOC_ARENA_MAX (same PID). The check that a pending change's undo record is a dict no longer uses assert (python3 -OO skips asserts).

v5.23 — --uninstall no longer stops part-way if a compiled copy or the launcher is already gone (removed by another uninstall at the same moment).

v5.22 — Starts through the shared launcher. wifimon.service now runs
 /usr/bin/python3 /usr/local/bin/asl_dvs_launch.py /usr/local/bin/wifimon.py.
 Run directly, Python compiles the whole 363 KB file on every start and
 keeps that memory (about 36 MB); the launcher imports wifimon instead, so
 Python saves the compiled copy in /usr/local/bin/__pycache__ and reuses
 it on later starts (about 22 MB, twice as fast to start). Python checks
 the file's date and size each start and recompiles by itself after an
 update. --install writes the launcher (same file the Pi Zero 2 W sysmon /
 dashboard, instmon and install_asl_dvs v6.5 write); --uninstall removes
 wifimon's compiled copy and the launcher once no unit uses it.

v5.21 — Adapter switches. Each WiFi adapter on the Radio & device card
 gets a 3-way switch: Auto (NetworkManager decides, same as before),
 Keep on, Keep off. Field log showed wlan0 rejoining SpectrumSetup-DD by
 itself after a restart although it had been disconnected earlier
 (`nmcli device disconnect` only lasts until the next reboot/NM restart).
 Keep off: `nmcli device set <dev> autoconnect no`, and disconnect it
 whenever it starts connecting. Keep on: autoconnect yes, and if it sits
 "disconnected" wifimon joins it (at most every RECONNECT_INTERVAL_SECS)
 to the highest-priority saved network that is in range and not already
 active on another adapter (up to 3 tried). For the adapter the watchdog
 uses, Keep on only sets autoconnect -- the watchdog's own reconnect
 logic (v5.16/v5.17) stays in charge. A "dev-mode" thread checks every
 DEVMODE_CHECK_SECS (10) and on every NetworkManager wl* event; it does
 nothing while the hotspot is on, a dashboard change is pending, or
 another change holds the action lock, and Keep on waits while a connect
 job runs or the adapter is unavailable (radio off).
 Settings are keyed by the adapter's factory hardware address
 (ETHTOOL_GPERMADDR; fallback /sys address if not randomized; last resort
 the name), so they follow the adapter if USB adapters swap wlan names.
 Stored in /etc/wifimon/state.json as "device_modes" (compare-before-
 write). Unplugged adapters with a setting are listed as "Not plugged
 in" with a Forget button (POST /api/device/forget {key}).
 Safety: Keep off is refused on the adapter the watchdog is using, and
 "Use this device" is refused on a Keep off adapter. If a reboot renames
 adapters so the watched one is now a Keep off adapter, the watchdog is
 moved to another adapter (Keep on first, then a connected one) with a
 warning, and the shutdown timer paused. Disconnect is refused on a Keep
 on adapter (it would just rejoin). POST /api/device/mode {device, mode,
 confirm} goes through the usual 60 s auto-undo, which restores the old
 setting (and reconnects if Keep off cut it).
 Also: HTTP_PORT back to 8991 (the attached copy had 8992).

v5.20 — Reconnect fixes, stage 5 of 5 (plan complete): WiFi chips on
 both sides. New "WiFi chips" group under More details.
 This Pi: chip model from the kernel's boot lines ("... for chip
 BCM43430/2", "Firmware: BCM43430/2 ...") -- caught by the v5.19 kernel
 log reader, or read once from `journalctl -k -b` if the kernel buffer
 has rolled over; else the SDIO chip ID (0xa9a6 = BCM43430/43436,
 0x4345 = BCM43455) or a USB adapter's own maker/product strings. Driver,
 firmware version and bus from the driver's own report (the ethtool
 "driver info" request, made directly -- ethtool itself isn't needed).
 Router: read from `iw dev <if> scan dump`, which lists what's already
 cached -- it never starts a scan. For the joined access point: maker,
 model, model number and device name if it announces them (its WPS
 info); the chip maker as a best guess from the vendor tags it
 broadcasts (Broadcom, Qualcomm/Atheros, MediaTek/Ralink, Realtek,
 Marvell, Quantenna); and the maker registered for its hardware address,
 if an OUI list is installed (ieee-data or nmap) and the address isn't
 a locally-set one. Missing items show "Not announced by the router".
 Cached per access point (retried every 60 s until found), so the 30 s
 status refresh costs almost nothing.

v5.19 — Reconnect fixes, stage 4 of 5: clearer log + WiFi health check.
 (1) "wlan0: connecting (need authentication)" is logged as INFO with
 "(password handshake)" -- it's a normal step of every join. Only if the
 device still isn't connected AUTH_WARN_SECS (30) later is a warning
 logged that the saved password may be wrong or changed.
 (2) Brief blips: missed checks that clear before counting as a drop
 (v5.16) get one INFO line ("Brief blip: N missed check(s), back without
 a drop") and are counted. Today's counters -- brief blips, real drops,
 WiFi chip stalls -- show on the Status card under the facts and in a
 new "WiFi health (today)" group under More details. Blip/drop counts
 live in /run/wifimon/health.json (tmpfs: survive a service restart, not
 a reboot, no SD writes) and reset at local midnight.
 (3) WiFi chip stalls: a reader thread follows the kernel log
 (/dev/kmsg, root only) for brcmf lines about timeouts (timeout / timed
 out / err=-110 / halted / crashed / firmware trap). Lines within 2 s are
 one stall. At start the kernel buffer is read back to count today's
 stalls since boot. Each stall is logged as a warning (at most one a
 minute, the rest counted). The last 20 chip messages and today's
 counters go into every shutdown/test report ("health" in the JSON, a
 "WiFi health today" line plus a "Recent WiFi chip messages" section in
 the text version).
 (4) "Stop chip roaming" (brcmfmac only), under More details after the
 country code: POST /api/roaming {off, confirm} writes
 /etc/modprobe.d/wifimon-brcmfmac.conf (options brcmfmac roamoff=1) or
 removes it (only if wifimon wrote it). Takes effect after a reboot; the
 box shows the live state and what the next boot will use. --uninstall
 removes the file.

v5.18 — Reconnect fixes, stage 3 of 5: keep power save off. New watchdog
 setting "Keep WiFi power save off (all networks)" (KEEP_POWERSAVE_OFF,
 default off). On, it: (1) writes /etc/NetworkManager/conf.d/
 90-wifimon-powersave.conf (wifi.powersave=2 as the default for every
 WiFi profile, so networks added later are covered too) and runs
 `nmcli general reload conf` -- never a NetworkManager restart;
 (2) sets any saved profile that explicitly asks for power save
 (enable/ignore) to disable, compare-before-modify; (3) turns power save
 off on the live link with iw. Then it keeps it off: after every
 reconnect, every NetworkManager "connected" event, and whenever the 30 s
 status refresh sees it on, the live state is checked and turned off
 again with iw, logged as "Power save had come back on -- turned it off
 again". Not while the hotspot is on. Off removes the file (profiles
 already set to disable stay that way -- the v5.7 per-network control
 changes them back). Reconciled at every start like the login-page
 file; --uninstall removes it. Settings checkboxes now carry their own
 hint text (data-hint), and the settings-save reply joins both notes
 when both NetworkManager files change.

v5.17 — Reconnect fixes, stage 2 of 5: smarter reconnect after a real
 drop. (1) Head start: after a real drop wifimon leaves NetworkManager
 (or wpa_supplicant) alone for NM_HEAD_START_SECS (30), since it rejoins
 by itself, and while NetworkManager reports the WiFi device as
 connecting/deactivating wifimon waits too -- up to NM_BUSY_MAX_SECS (45)
 in a row, so a join stuck forever can't block the watchdog. The same
 busy check runs before each network inside a retry round. (2) In range:
 with nmcli, each retry round scans first and skips saved networks that
 aren't in range (hidden networks are always tried; if the scan finds
 nothing, every network is tried as before). Skipped names are logged
 when the list changes, not every round. This stops the ~25 s stall on an absent network (seen
 with KD8PGK2). (3) Verify: after a join, wifimon now allows up to
 RECONNECT_VERIFY_SECS (15) for the connection check to pass, checking
 every 2 s, instead of one check after 3 s -- a slow DHCP no longer makes
 it move on and break a join that was working.

v5.16 — Reconnect fixes, stage 1 of 5: stop wifimon causing drops.
 Field log showed a single missed ping (every ~30 s) made the watchdog
 run `nmcli connection up` on the network the node was ALREADY on, which
 made NetworkManager disconnect and rejoin (3-5 s outage each time).
 Now: (1) with the WiFi link still up, one missed check is not a drop --
 it takes MISSES_BEFORE_LOST (3) misses in a row (~15 s); the shutdown
 countdown is still dated from the first miss, so shutdown timing is
 unchanged. If the WiFi link itself goes down it counts at once, as
 before. (2) The reconnect never rejoins the network the node is
 currently joined to. (3) Joined to WiFi but no internet: wifimon waits
 STUCK_LINK_SECS (60) before doing anything; after that the current
 network may be rejoined (a genuinely stuck link). The reconnect also
 stops early if the node comes back on its own while it runs.

v5.15 — WiFi country code, stage 2 of 2: the dashboard. Under the Status
 card's More details, right after Pi health, a "WiFi country code" block
 shows the code and country name with a Change button; Change opens a
 country picker (names with codes, sorted by name; preselects the current
 code, or the browser's region when none is set) and Set. The block sits
 outside the part that redraws every 5 s, so an open picker is never
 wiped. On the main Status view, when no country code is set, a one-line
 warning with a Fix button appears; Fix opens More details and the picker.
 The confirm dialog explains the brief-drop / auto-undo behaviour. The
 country list comes from GET /api/countries once per page load.

v5.14 — WiFi country code, stage 1 of 2: setting it. POST /api/country
 {code, confirm}: the code is checked against a built-in ISO 3166 list
 (249 entries). With raspi-config installed it runs `raspi-config nonint
 do_wifi_country XX` (what the Pi OS menu does, including keeping it after
 a reboot). Without it: `iw reg set XX` now, plus
 /etc/modprobe.d/wifimon-country.conf (options cfg80211
 ieee80211_regdom=XX) for the next boot, compare-before-write. On
 wpa_supplicant setups the country= line of wpa_supplicant.conf is updated
 as well. The result is read back with `iw reg get`; if the node still
 reports another code, the reply says so (a reboot may be needed) instead
 of claiming success. A new country can rule out the channel in use, so
 this uses the v5.1 auto-undo (60 s, shutdown timer paused): with no
 check-in the previous code is re-applied the same way; if there was none
 (00), the live setting goes back to 00 and wifimon's own modprobe file is
 removed -- a setting raspi-config already saved stays until changed
 again. Refused while the hotspot is on or another change is waiting.
 Logged in the Activity log.

v5.13 — nmcli additions, stage 4 of 4: emergency hotspot, started by
 hand only (never automatically). "Start hotspot" on the Radio & device
 card: network name (default <hostname>-setup), password (8-63
 characters, a random one offered), auto-stop after 15/30/60/120
 minutes. The hotspot is a NetworkManager profile written as a keyfile
 (0600; the password never goes on a command line): mode=ap, 2.4 GHz,
 WPA2 (CCMP), ipv4.method=shared (NetworkManager hands out addresses with
 dnsmasq -- the button is greyed out with a note when dnsmasq isn't
 installed), autoconnect off, bound to the WiFi device. Each start
 replaces the previous hotspot profile. Hotspot profiles never appear in
 Saved networks, the reconnect list or the join-order sync.
 The Pi has one radio, so the node leaves its WiFi while the hotspot is
 on; the confirm dialog says so and gives the address to open once your
 phone has joined (NetworkManager's shared address, normally
 http://10.42.0.1:8991). While it's on, the no-connection shutdown timer
 and auto-reconnect are paused (the low-voltage timer is not), other
 changes are refused except "Save only" in Add network -- so a hotel
 network can be added from the phone -- and a banner shows the time left.
 "Stop hotspot" (or the auto-stop) takes the hotspot down and runs the
 v5.2 connect job to the chosen network (default: the one the node was on
 before), with the usual known-good fallback. The hotspot state is kept
 in /run/wifimon/hotspot.json, so if wifimon restarts while it's on, the
 hotspot is taken down at start and normal reconnecting resumes.

v5.12 — nmcli additions, stage 3 of 4: per-network options. Saved
 networks that have a NetworkManager profile get an "Options" button:
 IP address (Automatic / Fixed / Automatic with custom DNS -- address +
 prefix, gateway, 1-3 DNS servers; the gateway must be inside the
 address's network), "Use this Pi's real MAC address"
 (802-11-wireless.cloned-mac-address = permanent, for hotels and routers
 that register devices by MAC), and Band: Any / 2.4 GHz only / 5 GHz
 only (802-11-wireless.band; only offered when the WiFi device can do
 5 GHz, checked once with `iw phy` -- a Pi Zero 2W is 2.4 GHz only).
 Change from the plan: these live in their own Options form, not the
 Edit form, because Edit replaces the profile and so refuses the network
 in use, while options use `nmcli connection modify` and do work on it.
 Options changes on the network in use re-activate it, which briefly
 drops the WiFi, so they use the v5.1 auto-undo with a 2-minute window
 (the page may have to be reopened at a new address, and log in again
 there): the previous values are restored and the network re-activated
 if no page checks in. On other networks it just saves the options.
 Only values that actually change are written. Add network gains the
 real-MAC checkbox, and Edit now carries IP / MAC / band options over to
 the replacement profile (as v5.7 did for auto-join and power save).

v5.11 — Shutdown reports, stage 4 of 4: unclean stops. At start wifimon
 writes a small marker (/var/lib/wifimon/running.json: start time, boot
 id, pid, version, fsynced) and removes it on a normal stop. If the
 marker is still there at the next start and no shutdown report was
 saved after that run began, an "unclean stop" report is saved: same
 boot id = wifimon itself stopped unexpectedly (crash / killed) while
 the node kept running; different boot id = the node lost power or
 restarted without a clean shutdown (e.g. a brownout faster than the
 low-voltage timer). It includes the end of the previous boot's journal
 when the journal is kept on disk (otherwise it says so). Cost: one small
 write per start and one delete per stop -- no periodic heartbeat.

v5.10 — Shutdown reports, stage 3 of 4: dashboard. New "Shutdown reports"
 section in the Activity log card: saved reports newest first, View
 (the plain-text version in a scroll box), Download (.txt), Delete (with
 confirmation), and "Save a test report", which writes a full report --
 snapshot, Activity log, diagnostics -- without shutting anything down.
 After a restart, a banner says when and why the node last shut down
 (shutdown and unclean-stop reports from the last 7 days, older than the
 current run), with View and Dismiss (remembered in the browser, so no
 disk write). API, login required: GET /api/reports, GET /api/report
 ?name=&format=text|json[&download=1], POST /api/reports/delete,
 POST /api/reports/test. Report names are checked against a strict
 pattern, so nothing outside the report folder can be read or deleted.

v5.9 — Shutdown reports, stage 2 of 4: save the report. do_shutdown()
 now writes a report to /var/log/wifimon/ (folder 0700, files 0600)
 BEFORE it asks systemd to power off. Correction to the plan: power-off
 starts at once (the 15 s in do_shutdown is only the fallback before
 `poweroff -f`), so the report is finished first, which delays the
 shutdown by at most ~10 s (5 s for low voltage). Order: (1) the reason,
 thresholds in force, the stage-1 snapshots (first, countdown, final) and
 the whole Activity log are written straight away -- temp file, fsync,
 rename, fsync the folder -- so a report exists even if power dies next;
 (2) last-moment diagnostics are gathered within the time budget (WiFi
 link, device list, addresses, routes, rfkill, the last NetworkManager or
 wpa_supplicant log lines, the last kernel messages -- each command
 time-limited, each output capped at 8 KB) and the report is rewritten
 the same safe way. Reports are capped at REPORT_MAX_BYTES (256 KB; when
 over, diagnostics are shortened first, then middle snapshots, then the
 oldest log lines, and the report says it was trimmed) and only the
 newest REPORT_KEEP (10) are kept. Nothing secret goes in: the Activity
 log never holds passwords. --uninstall leaves the reports in place.

v5.8 — Shutdown reports, stage 1 of 4: record the lead-up (memory only;
 nothing is written to the SD card in this stage). As soon as either
 countdown starts (no connection or low voltage), the watchdog starts
 keeping snapshots of everything the Status card's More details shows --
 connection, signal, network, Pi health, watchdog counters -- plus the
 power readings, CPU temperature, the device in use and how old each
 piece of data was. One snapshot when the problem starts (always kept),
 then one every SNAPSHOT_EVERY_SECS (10 s; SNAPSHOT_LOWV_EVERY_SECS = 5 s
 while the voltage is low), keeping the newest SNAPSHOT_KEEP (20). During
 a no-connection countdown each snapshot also asks the status collector
 for an early slow refresh so IP/DNS/network details aren't 30 s old.
 When wifimon decides to shut down it takes one last snapshot from a
 fresh collection (fast values only for low voltage, where time matters),
 ready for stage 2 to save. If the problem clears first, or a dashboard
 change pauses the timer, the recording is thrown away. The Watchdog card
 shows while a recording is running; GET /api/snapshots (login needed)
 returns it in full. Snapshots are copies of data wifimon already
 collects, so the cost is small. (The country code / power save plan
 moves to after the shutdown-report stages.)

v5.7 — nmcli additions, stage 2 of 4 (quick buttons).
 Reconnect now (Status card): runs the v5.2 connect job on the network
 in use, so a reconnect that doesn't come back falls straight through to
 the known-good networks, with the shutdown timer paused as usual. Same
 one-at-a-time rule and confirm:true as every change.
 Power save off: when the Status card sees power save on, it offers
 "Turn off for this network" and "Turn off for all saved networks". This
 sets 802-11-wireless.powersave = 2 (disable) on the NetworkManager
 profile(s) -- so it survives reboots, unlike `iw ... set power_save
 off` -- and, for the network in use, also runs that iw command so it
 takes effect now without dropping the connection. Profiles already set
 are not rewritten. The Edit form gains "Power save: leave as default /
 off".
 Auto-join on/off: a toggle on each saved network that has a
 NetworkManager profile (connection.autoconnect). Off means neither
 NetworkManager nor wifimon joins it by itself: the watchdog's retries
 and the connect job's known-good fallback both skip it. Connect still
 works for it, and a failed switch can still go back to it as the
 network it was just on (that return is part of the switch you asked
 for, not the node choosing a network).
 Edit now keeps a network's auto-join and power-save settings when it
 replaces the profile (v5.3-v5.6 reset them to NetworkManager's defaults).

v5.6 — nmcli additions, stage 1 of 4 (automatic features; no new buttons).
 Join-order sync: whenever the reconnect list changes (arrows, Add,
 Add to list, Take off list, Edit, Delete, or a tag change) and once at
 start, each NetworkManager profile on the list gets
 connection.autoconnect-priority = its place counted from the bottom
 (top of an N-long list = N), so NetworkManager's own choice at boot
 matches wifimon's order. Profiles not on the list are left alone. A
 profile is only modified when its value differs (each modify rewrites
 its file -- SD wear), runs in its own thread with a 1 s pause to batch
 quick arrow clicks, and never touches the live connection.
 NetworkManager events: a background `nmcli monitor` feeds WiFi lines
 into the Activity log -- "wlan0: disconnected", "wlan0: using
 connection 'Home'", "wlan0: connecting (need authentication)" (flagged
 as a possible wrong password), "Connectivity is now 'portal'", primary
 connection changes. Other devices, p2p-dev lines, and connect sub-steps
 are dropped; an identical line within 10 s is skipped and at most 30
 lines a minute are logged. If the monitor exits it restarts itself
 (5 s, doubling to a 5 min ceiling). Runs with LC_ALL=C so the messages
 it matches aren't translated.
 Login-page check: new watchdog setting "Detect login pages" (off by
 default). On, it writes /etc/NetworkManager/conf.d/
 90-wifimon-connectivity.conf (NetworkManager then fetches
 http://nmcheck.gnome.org/check_network_status.txt about every 5 min)
 and runs `nmcli general reload conf` -- never a NetworkManager restart,
 which would drop the WiFi. Off removes the file; wifimon owns that file
 and reconciles it at every start, and --uninstall removes it. While on,
 the page shows a banner when NetworkManager reports "portal" (the
 network wants a login page, which a headless node can't complete), the
 Status card's Internet line says so, and a failed Connect names it as
 the reason (the job's final message and its step list now show each
 failed step's reason). With the setting off wifimon ignores NM's
 connectivity state, because NM then reports "full" regardless.
 Also: changing watchdog settings only restarts running countdowns when
 a timer-related value actually changed.
 Decided for stage 4: the emergency hotspot will be started by hand
 only (no automatic start instead of shutting down).

v5.5 — The dashboard is served over plain HTTP by default, like the rest
 of the suite's web tools: USE_TLS in the CONFIG block now defaults to
 False (set it True to get the v5.0-v5.4 self-signed HTTPS back).
 With HTTPS off by choice, --install no longer makes a certificate and
 prints an http:// address, and the red "Not encrypted" badge and the
 startup warning are gone; they now appear only when HTTPS is switched
 on but can't start. A certificate already made in /etc/wifimon/tls is
 left in place and simply not used. The "come back at ..." hint shown
 before a network switch now uses whichever scheme the page is on.
 Note: with plain HTTP the root password (login, Show password) and any
 WiFi password shown cross the network unencrypted -- use the dashboard
 on a trusted network. The login cookie already drops its HTTPS-only
 flag when HTTPS is off.

v5.4 — Dashboard Stage 5 of 5 (the wifimon + wifi_menu.sh dashboard
 conversion is complete). New "Activity log" card: the last 100 wifimon
 log events at INFO and above -- connection drops and restores, retries,
 voltage warnings, every dashboard action, password Shows, failed
 logins -- kept in memory only (nothing written to the SD card, gone on
 restart; the journal still has the full history). The page fetches only
 entries newer than the last one it has (/api/log?after=N), can show
 warnings and errors only, and has a Copy button.
 Security audit of the whole v5.3 file (same process as the v4.8 audit).
 Fixed:
  A1 Log line forging: text from outside -- network names, nmcli error
     output -- was logged as-is, so a control character or newline in it
     could fake extra journal lines. A filter on the wifimon logger now
     replaces control characters in every message, which also covers
     the new Activity log. (The page itself was already safe: every value
     is inserted as text, never as HTML.)
  A2 Password in exception text: when `nmcli device wifi connect ...
     password <psk>` or `wpa_cli set_network ... psk` timed out, the
     TimeoutExpired message -- which includes the whole command, password
     and all -- was logged (DEBUG only, so off by default). It now logs
     "timed out" without the command; _nmcli_ok() does the same.
  A3 Connection cap was global only: one client holding 16 idle
     keep-alive connections could lock everyone else out of the
     dashboard. Now also capped at MAX_CONNECTIONS_PER_IP (8) per address.
  A4 _IFACE_RE allowed a device name starting with '-', which a command
     could read as an option. Names must now start with a letter or digit
     (they're also still checked against the real device list).
 Checked and fine: every POST needs a session plus the CSRF headers;
 every change needs confirm:true server-side; no shell anywhere (argv
 lists only); config, state, pending, keyfile and TLS key files are
 written 0600 with atomic replace; passwords never appear in /api/status
 or the logs; Show password needs the root password again and shares the
 login lockout; the settings ranges can't produce an instant shutdown.
 Accepted risks, documented, not changed:
  R1 A network with no NetworkManager profile (wifimon.conf-only, or the
     wpa_cli backend) still gets its password on nmcli / wpa_cli's
     command line during a watchdog retry (the v4.8 accepted risk). Any
     network saved from the dashboard has a profile, so it never does.
  R2 Sessions slide with activity and have no absolute lifetime; an open
     dashboard tab stays logged in. They end on logout or restart.
  R3 No Host-header allow-list. A DNS-rebinding page can't use the
     session (the cookie belongs to the node's own name) and, over HTTPS,
     fails the certificate check; it could only try logins, which the
     per-IP lockout limits.
  R4 If openssl is missing the dashboard falls back to plain HTTP (red
     badge + journal warning), and Show password works there too, by
     the user's decision in the Stage 1 plan.
  R5 A slow PAM failure (pam_faildelay) holds a connection thread for a
     couple of seconds; the connection caps bound this, and the watchdog
     runs in its own thread either way.
 Verified off-hardware: new tests for each fix (forged-newline SSID,
 timed-out connect with a password, per-IP cap, dashed device name),
 the Activity log API and card in jsdom, and every earlier stage's
 suite re-run on both copies. Not verified on a real Pi.

v5.3 — Dashboard Stage 4 of 5.
 Saved networks card: up/down arrows set the watchdog's reconnect order
 (priorities are renumbered 1..N on every move). NetworkManager-only
 profiles get "Add to reconnect list", and "Add all" imports every one
 of them at once (this replaces --setup-wifi's import for NM systems;
 names come from each profile's SSID, not its profile name). "Take off
 list" removes a network from wifimon.conf but keeps its NM profile.
 "Edit" changes security, password (blank = keep the current one) and
 hidden: a fresh keyfile profile is loaded first and the old profile(s)
 deleted only after that worked, so a failed edit changes nothing; the
 network is re-tagged Not verified. The network in use can't be edited
 (replacing its profile would drop the connection).
 Watchdog card: "Change settings" edits the shutdown / reconnect
 settings -- no-connection shutdown, low-voltage shutdown, low-voltage
 level, reconnect interval, check interval, internet-check address --
 within fixed safe ranges, plus "Reset to defaults" (the CONFIG block
 values). They apply at once and are saved in /etc/wifimon/state.json
 (merged with the saved device, compare-before-write). Any countdown
 running when settings change starts over, so shortening a limit can
 never trigger an instant shutdown.
 Watchdog reconnect: when a network has a NetworkManager profile, the
 watchdog now starts that profile (`nmcli connection up`) instead of
 `nmcli device wifi connect <ssid> password <psk>`. That keeps the
 password off the command line whenever a profile exists, and stops NM
 from growing duplicate profiles. Networks without a profile still use
 the v4.8 call (the documented accepted risk).

v5.2 — Dashboard Stage 3 of 5. Two new cards.
 "Saved networks": ONE list merging NetworkManager's WiFi profiles with
 wifimon.conf's reconnect list, one row per network name. Each row
 shows its priority (wifimon.conf order; "not in the watchdog list" for
 NM-only profiles), a tag -- Known good (has connected and passed the
 connection check at least once), Not verified, or Failed (last attempt
 didn't connect) -- the password hidden behind Show, and Connect /
 Delete. Show asks for the root password again every time (same per-IP
 lockout as login), is fetched one network at a time, never included
 in /api/status, hides itself after 30 s, and is logged. Delete refuses
 the network in use. "Add network" form: name (typed or picked from the
 scan), Open / WPA2 / WPA3, password, hidden; "Save & connect" or "Save
 only". A new network is written to NetworkManager as a keyfile
 (/etc/NetworkManager/system-connections, 0600) and loaded with
 `nmcli connection load`, so its password never appears on any command
 line; it is also added to wifimon.conf at the bottom of the priority
 order, tagged Not verified.
 "Nearby networks": NM's scan list (strongest entry per name, hidden
 names left out) with a Rescan button; Connect for saved or open
 networks, "Add..." (opens the form pre-filled) for secured unsaved ones.
 Connecting runs as a background job so the page can lose contact
 mid-switch: pause the shutdown timer, remember the current network as
 the return point, give the new one NEW_NETWORK_TEST_SECS (30 s) to
 join and pass the watchdog's connection check. If it fails it's
 tagged Failed (never deleted, and nothing else is touched), then the
 job retries the return point, then Known good networks by priority,
 FALLBACK_TEST_SECS (20 s) each, skipping networks a fresh scan doesn't
 see (hidden ones are always tried). If all fail the pause ends at once
 and the normal watchdog takes over. The result shows as a popup the
 next time the page reaches the node. One job or pending change at a
 time (shares Stage 2's lock).
 Tags are written to wifimon.conf only when they change. The watchdog
 also tags a wifimon.conf network Known good when it sees the node
 connected on it, and reloads the list when the dashboard changes it
 (v4.8 only loaded it at start). Its own reconnect order is now: the
 network just lost, then Known good, then untagged / Not verified, then
 Failed -- by priority within each group.
 Fixes carried from v4.8: wifimon.conf is now read and written with
 ConfigParser(interpolation=None) -- before, a '%' in a password made
 load_wifi_networks() fail and save_wifi_networks() raise. And because
 ConfigParser trims spaces around values, a password that starts or
 ends with a space is now stored as psk_b64 (base64) instead of psk.
 Fix to v5.1: change handlers now send their reply only after releasing
 the action lock, so a quick follow-up click can't be refused as "busy".
 These cards need NetworkManager (nmcli); they say so if it's missing.
 Verified off-hardware with the fake-nmcli harness through the live
 HTTPS server; not verified against a real NetworkManager, keyfile
 loading on Pi OS, or a WPA3 network.

v5.1 — Dashboard Stage 2 of 5. New "Radio & device" card: turn the
 WiFi radio on/off, disconnect a WiFi device, or switch which WiFi
 device is in use (the web version of wifi_menu.sh options 2-5; needs
 NetworkManager/nmcli, the card says so if it's missing).
 Auto-undo: turning the radio off, disconnecting, or switching devices
 becomes a "pending change". The page checks in automatically on its
 next successful poll at least 5 s after the change; if no check-in
 arrives within CHANGE_UNDO_SECS (60 s) -- e.g. the change cut off the
 browser's own WiFi path -- wifimon puts things back (radio on + the
 previous profile, reconnect the device, or switch back). An "Undo now"
 button is on the pending banner. One pending change at a time. The
 pending change is also written to /run/wifimon/pending_change.json
 (tmpfs, no SD wear) before the action runs, so if wifimon restarts
 mid-change it undoes it on the next start rather than leaving the
 node cut off.
 Timer pause: any change made from the card pauses the no-connection
 shutdown timer (and auto-reconnect, which would otherwise fight the
 change) for CHANGE_GRACE_SECS (180 s). While paused the timer is
 cleared, so if the node is still offline afterwards it starts again
 from the full NO_CONN_SHUTDOWN_SECS. The low-voltage timer is never
 paused.
 Switching devices moves the watchdog to the new device at run time
 (INTERFACE becomes a live setting) and saves the choice to
 /etc/wifimon/state.json (0600, compare-before-write, written only on a
 switch). On start, a saved device that still exists overrides INTERFACE
 from the CONFIG block.
 The page now knows which interface the browser reached it through; the
 confirm dialog warns when a change may cut the browser off.
 Also: the status collector can be asked for an early slow refresh, so
 the card updates right after a change instead of up to 30 s later.
 Verified off-hardware: a fake nmcli (state machine) driven through the
 live HTTPS server -- radio off/on, disconnect, switch, auto-keep,
 auto-undo on timeout, Undo now, one-at-a-time, restart recovery,
 timer pause in the watchdog loop -- plus the page in jsdom. Not
 verified on a real Pi with two WiFi adapters.

v5.0 — Dashboard Stage 1 of 5 (merging wifimon + wifi_menu.sh into one
 dashboard service). The watchdog loop that used to be run() now runs
 in its own thread (_watchdog_loop); its decisions are unchanged from
 v4.8 -- same timers, same thresholds, same reconnect order, same
 shutdown path and shutdown_state.json -- it only publishes its state
 (_wd) for the dashboard, and each pass is wrapped so one unexpected
 error is logged instead of silently ending the watchdog. If the web
 server can't start (port taken, TLS failure), the watchdog keeps
 running without it.
 New: a second thread (_collector_loop) gathers WiFi details for the
 page from cheap sources -- /sys, /proc/net/wireless, iw, nmcli, ip,
 vcgencmd -- on two speeds (fast every 5 s: signal, counters, voltage;
 slow every 30 s: IP, DNS, security, country, power save). The page
 only ever reads that cached snapshot, so polling the page never runs
 nmcli. Nothing is written to the SD card.
 New: HTTPS on port 8991 with a per-node self-signed certificate made
 by openssl on first start (/etc/wifimon/tls, key 0600, EC P-256,
 10 years). If openssl is missing it falls back to plain HTTP and says
 so loudly (log + red badge on the page).
 New: root-password login (PAM first, /etc/shadow + libcrypt fallback,
 same approach as the rest of the suite), independent of the other
 suite tools: own cookie (wifimon_session), own in-memory session store
 (12 h, sliding, refreshed Set-Cookie on every authenticated response),
 per-IP lockout with exponential backoff after 5 failed tries, CSRF
 check on every POST (X-Requested-With + JSON Content-Type + Origin
 must match Host), security headers (CSP, X-Frame-Options, nosniff,
 no-referrer), 16 KB body cap, 16-connection cap.
 New cards: Status (network name, signal meter, IP, internet check,
 plus a "More details" panel: Connection, Signal, Network, Pi health,
 Watchdog), Watchdog (live countdowns, thresholds, voltage/throttle
 flags), Service (version, uptime, encryption, restart, log out).
 Restart runs through a detached systemd-run unit (suite standard for
 anything that restarts its own process) and needs confirm:true.
 --install now also creates the certificate and prints the dashboard
 address, and warns if root has no password (login would fail).
 Verified off-hardware only: parsers against sample iw / nmcli /
 /proc / vcgencmd output, a live in-process HTTPS server (login,
 lockout, CSRF, headers, sessions, status JSON), and the page script
 in jsdom. Not verified on a real Pi: real iw/nmcli output on the
 Zero 2W, PAM login with the real root password, the self-restart.

v4.8 — Security audit fixes. (1) save_wifi_networks() and
 _ensure_config() now write wifimon.conf (plaintext WiFi PSKs) via a
 shared _write_config_atomic() helper: os.open(..., 0o600) + tmp-file
 + os.replace(), instead of plain open() followed by a separate
 os.chmod(). This closes two gaps: a brief window where the file
 existed with default-umask permissions before the chmod landed, and
 the lack of crash-safety (a mid-write interruption -- this daemon
 watchdog-reboots the node on its own -- could previously truncate
 the config and lose every saved network). Matches the pattern
 _write_shutdown_state() already used. (2) _connect_wpa_cli() now
 escapes embedded \" and \\ in SSID/PSK values via _wpa_cli_quote()
 before wrapping them in wpa_cli's quoted-string syntax -- a raw "
 in an SSID (broadcastable by anyone nearby) could previously break
 wpa_cli's own parsing of the set_network command. Still never
 touches a shell (subprocess is always called with an argv list), so
 this was never OS command injection, just unescaped input for
 wpa_cli's own quoting. (3) run() now logs a warning if not running
 as root, matching the check install_service()/uninstall_service()/
 run_wifi_setup() already had. Not fixed, documented as accepted
 risk: nmcli/wpa_cli both put the PSK on their own subprocess
 command line (visible via ps/proc to another *local* user for that
 call's duration) -- avoiding this needs NetworkManager D-Bus or the
 wpa_supplicant control socket instead of these CLIs, a materially
 bigger change than this fix warranted.

v4.7 — Before triggering a shutdown, wifimon now writes a small JSON
 state file to /run/wifimon/shutdown_state.json (active/reason/trigger/
 since). This is written first thing inside do_shutdown(), well before
 the actual poweroff, so asl_dvs_dashboard and sysmon — which already
 poll their own /api/status every few seconds — have time to pick it
 up and show a persistent "wifimon is shutting this node down" popup
 before the node goes dark. /run is tmpfs and is wiped on every real
 reboot, so the flag self-clears; run() also clears it defensively on
 startup in case wifimon was restarted without a full reboot (e.g.
 after a crash) so a stale flag can't get stuck showing forever.

v4.6 — Fixed the shebang: it was `# -*- coding: utf-8 -*-` on line 1
 and `#!/usr/bin/env python3` commented out on line 2, so running the
 file directly (./wifimon.py) couldn't find an interpreter — it only
 ever worked when invoked as `python3 wifimon.py`. The shebang is now
 the literal, uncommented first line; the coding declaration moved to
 line 2, which PEP 263 also allows. No other change.

v4.5 — Line-ending normalization only. No behavior change. Lines 252-412
 (the WiFi-setup-wizard block: _prompt_manual_networks through
 run_wifi_setup) had plain LF endings while the rest of the file used
 CRLF — evidently pasted in from a different editor/source at some
 point without normalizing. Whole file is now LF throughout, matching
 the rest of the ASL-DVS-M17 suite (asl_dvs_m17_44helper, instmon).
 Verified: every line's content is byte-identical to v4.4 once both
 are normalized for comparison — only line-ending bytes changed.

v4.3 — Added /etc/wifimon/wifimon.conf with a [network_N] section per
 known WiFi network (ssid/psk/priority). While the connection is down,
 wifimon now aggressively retries connecting — the network that was
 just lost first, then the configured networks in priority order —
 using nmcli if present, falling back to wpa_cli. This runs alongside
 the existing shutdown countdown, not instead of it: NO_CONN_SHUTDOWN_SECS
 still fires on schedule no matter how many reconnect attempts happened.
 If wifimon.conf has no networks configured, this is a no-op and
 behavior is unchanged from v4.2.

v4.4 — --install now prompts for WiFi setup on an interactive terminal
 if no networks are configured yet: enter one manually, or import
 networks already saved on the system (nmcli connection profiles or
 wpa_supplicant.conf). Skipped automatically for non-interactive
 installs, and never re-prompts if wifimon.conf already has networks
 in it. The same menu is also available standalone via --setup-wifi.

Usage:
 sudo python3 wifimon.py --install      Install as systemd service & start
 sudo python3 wifimon.py --uninstall    Stop & remove systemd service
 sudo python3 wifimon.py --setup-wifi   Add/import WiFi networks
 python3 wifimon.py                     Run watchdog + dashboard in foreground

Dashboard:  http://<node>.local:8991  (log in with the root password)
"""
```
