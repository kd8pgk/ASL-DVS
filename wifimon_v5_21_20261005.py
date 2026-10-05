#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#"""
#wifimon.py — WiFi & Voltage Watchdog + Dashboard for Raspberry Pi Zero 2W
#Version: 5.21 (Adapter switches: Auto / Keep on / Keep off)

#Monitors wifi connectivity and supply voltage.
#Triggers a clean system shutdown on:
#  1. Sustained low voltage (undervoltage protection).
#  2. Sustained network connection loss.
#Serves a web dashboard on port 8991 (plain HTTP by default, root-password login).
#
#v5.21 — Adapter switches. Each WiFi adapter on the Radio & device card
#  gets a 3-way switch: Auto (NetworkManager decides, same as before),
#  Keep on, Keep off. Field log showed wlan0 rejoining SpectrumSetup-DD by
#  itself after a restart although it had been disconnected earlier
#  (`nmcli device disconnect` only lasts until the next reboot/NM restart).
#  Keep off: `nmcli device set <dev> autoconnect no`, and disconnect it
#  whenever it starts connecting. Keep on: autoconnect yes, and if it sits
#  "disconnected" wifimon joins it (at most every RECONNECT_INTERVAL_SECS)
#  to the highest-priority saved network that is in range and not already
#  active on another adapter (up to 3 tried). For the adapter the watchdog
#  uses, Keep on only sets autoconnect -- the watchdog's own reconnect
#  logic (v5.16/v5.17) stays in charge. A "dev-mode" thread checks every
#  DEVMODE_CHECK_SECS (10) and on every NetworkManager wl* event; it does
#  nothing while the hotspot is on, a dashboard change is pending, or
#  another change holds the action lock, and Keep on waits while a connect
#  job runs or the adapter is unavailable (radio off).
#  Settings are keyed by the adapter's factory hardware address
#  (ETHTOOL_GPERMADDR; fallback /sys address if not randomized; last resort
#  the name), so they follow the adapter if USB adapters swap wlan names.
#  Stored in /etc/wifimon/state.json as "device_modes" (compare-before-
#  write). Unplugged adapters with a setting are listed as "Not plugged
#  in" with a Forget button (POST /api/device/forget {key}).
#  Safety: Keep off is refused on the adapter the watchdog is using, and
#  "Use this device" is refused on a Keep off adapter. If a reboot renames
#  adapters so the watched one is now a Keep off adapter, the watchdog is
#  moved to another adapter (Keep on first, then a connected one) with a
#  warning, and the shutdown timer paused. Disconnect is refused on a Keep
#  on adapter (it would just rejoin). POST /api/device/mode {device, mode,
#  confirm} goes through the usual 60 s auto-undo, which restores the old
#  setting (and reconnects if Keep off cut it).
#  Also: HTTP_PORT back to 8991 (the attached copy had 8992).
#
#v5.20 — Reconnect fixes, stage 5 of 5 (plan complete): WiFi chips on
#  both sides. New "WiFi chips" group under More details.
#  This Pi: chip model from the kernel's boot lines ("... for chip
#  BCM43430/2", "Firmware: BCM43430/2 ...") -- caught by the v5.19 kernel
#  log reader, or read once from `journalctl -k -b` if the kernel buffer
#  has rolled over; else the SDIO chip ID (0xa9a6 = BCM43430/43436,
#  0x4345 = BCM43455) or a USB adapter's own maker/product strings. Driver,
#  firmware version and bus from the driver's own report (the ethtool
#  "driver info" request, made directly -- ethtool itself isn't needed).
#  Router: read from `iw dev <if> scan dump`, which lists what's already
#  cached -- it never starts a scan. For the joined access point: maker,
#  model, model number and device name if it announces them (its WPS
#  info); the chip maker as a best guess from the vendor tags it
#  broadcasts (Broadcom, Qualcomm/Atheros, MediaTek/Ralink, Realtek,
#  Marvell, Quantenna); and the maker registered for its hardware address,
#  if an OUI list is installed (ieee-data or nmap) and the address isn't
#  a locally-set one. Missing items show "Not announced by the router".
#  Cached per access point (retried every 60 s until found), so the 30 s
#  status refresh costs almost nothing.
#
#v5.19 — Reconnect fixes, stage 4 of 5: clearer log + WiFi health check.
#  (1) "wlan0: connecting (need authentication)" is logged as INFO with
#  "(password handshake)" -- it's a normal step of every join. Only if the
#  device still isn't connected AUTH_WARN_SECS (30) later is a warning
#  logged that the saved password may be wrong or changed.
#  (2) Brief blips: missed checks that clear before counting as a drop
#  (v5.16) get one INFO line ("Brief blip: N missed check(s), back without
#  a drop") and are counted. Today's counters -- brief blips, real drops,
#  WiFi chip stalls -- show on the Status card under the facts and in a
#  new "WiFi health (today)" group under More details. Blip/drop counts
#  live in /run/wifimon/health.json (tmpfs: survive a service restart, not
#  a reboot, no SD writes) and reset at local midnight.
#  (3) WiFi chip stalls: a reader thread follows the kernel log
#  (/dev/kmsg, root only) for brcmf lines about timeouts (timeout / timed
#  out / err=-110 / halted / crashed / firmware trap). Lines within 2 s are
#  one stall. At start the kernel buffer is read back to count today's
#  stalls since boot. Each stall is logged as a warning (at most one a
#  minute, the rest counted). The last 20 chip messages and today's
#  counters go into every shutdown/test report ("health" in the JSON, a
#  "WiFi health today" line plus a "Recent WiFi chip messages" section in
#  the text version).
#  (4) "Stop chip roaming" (brcmfmac only), under More details after the
#  country code: POST /api/roaming {off, confirm} writes
#  /etc/modprobe.d/wifimon-brcmfmac.conf (options brcmfmac roamoff=1) or
#  removes it (only if wifimon wrote it). Takes effect after a reboot; the
#  box shows the live state and what the next boot will use. --uninstall
#  removes the file.
#
#v5.18 — Reconnect fixes, stage 3 of 5: keep power save off. New watchdog
#  setting "Keep WiFi power save off (all networks)" (KEEP_POWERSAVE_OFF,
#  default off). On, it: (1) writes /etc/NetworkManager/conf.d/
#  90-wifimon-powersave.conf (wifi.powersave=2 as the default for every
#  WiFi profile, so networks added later are covered too) and runs
#  `nmcli general reload conf` -- never a NetworkManager restart;
#  (2) sets any saved profile that explicitly asks for power save
#  (enable/ignore) to disable, compare-before-modify; (3) turns power save
#  off on the live link with iw. Then it keeps it off: after every
#  reconnect, every NetworkManager "connected" event, and whenever the 30 s
#  status refresh sees it on, the live state is checked and turned off
#  again with iw, logged as "Power save had come back on -- turned it off
#  again". Not while the hotspot is on. Off removes the file (profiles
#  already set to disable stay that way -- the v5.7 per-network control
#  changes them back). Reconciled at every start like the login-page
#  file; --uninstall removes it. Settings checkboxes now carry their own
#  hint text (data-hint), and the settings-save reply joins both notes
#  when both NetworkManager files change.
#
#v5.17 — Reconnect fixes, stage 2 of 5: smarter reconnect after a real
#  drop. (1) Head start: after a real drop wifimon leaves NetworkManager
#  (or wpa_supplicant) alone for NM_HEAD_START_SECS (30), since it rejoins
#  by itself, and while NetworkManager reports the WiFi device as
#  connecting/deactivating wifimon waits too -- up to NM_BUSY_MAX_SECS (45)
#  in a row, so a join stuck forever can't block the watchdog. The same
#  busy check runs before each network inside a retry round. (2) In range:
#  with nmcli, each retry round scans first and skips saved networks that
#  aren't in range (hidden networks are always tried; if the scan finds
#  nothing, every network is tried as before). Skipped names are logged
#  when the list changes, not every round. This stops the ~25 s stall on an absent network (seen
#  with KD8PGK2). (3) Verify: after a join, wifimon now allows up to
#  RECONNECT_VERIFY_SECS (15) for the connection check to pass, checking
#  every 2 s, instead of one check after 3 s -- a slow DHCP no longer makes
#  it move on and break a join that was working.
#
#v5.16 — Reconnect fixes, stage 1 of 5: stop wifimon causing drops.
#  Field log showed a single missed ping (every ~30 s) made the watchdog
#  run `nmcli connection up` on the network the node was ALREADY on, which
#  made NetworkManager disconnect and rejoin (3-5 s outage each time).
#  Now: (1) with the WiFi link still up, one missed check is not a drop --
#  it takes MISSES_BEFORE_LOST (3) misses in a row (~15 s); the shutdown
#  countdown is still dated from the first miss, so shutdown timing is
#  unchanged. If the WiFi link itself goes down it counts at once, as
#  before. (2) The reconnect never rejoins the network the node is
#  currently joined to. (3) Joined to WiFi but no internet: wifimon waits
#  STUCK_LINK_SECS (60) before doing anything; after that the current
#  network may be rejoined (a genuinely stuck link). The reconnect also
#  stops early if the node comes back on its own while it runs.
#
#v5.15 — WiFi country code, stage 2 of 2: the dashboard. Under the Status
#  card's More details, right after Pi health, a "WiFi country code" block
#  shows the code and country name with a Change button; Change opens a
#  country picker (names with codes, sorted by name; preselects the current
#  code, or the browser's region when none is set) and Set. The block sits
#  outside the part that redraws every 5 s, so an open picker is never
#  wiped. On the main Status view, when no country code is set, a one-line
#  warning with a Fix button appears; Fix opens More details and the picker.
#  The confirm dialog explains the brief-drop / auto-undo behaviour. The
#  country list comes from GET /api/countries once per page load.
#
#v5.14 — WiFi country code, stage 1 of 2: setting it. POST /api/country
#  {code, confirm}: the code is checked against a built-in ISO 3166 list
#  (249 entries). With raspi-config installed it runs `raspi-config nonint
#  do_wifi_country XX` (what the Pi OS menu does, including keeping it after
#  a reboot). Without it: `iw reg set XX` now, plus
#  /etc/modprobe.d/wifimon-country.conf (options cfg80211
#  ieee80211_regdom=XX) for the next boot, compare-before-write. On
#  wpa_supplicant setups the country= line of wpa_supplicant.conf is updated
#  as well. The result is read back with `iw reg get`; if the node still
#  reports another code, the reply says so (a reboot may be needed) instead
#  of claiming success. A new country can rule out the channel in use, so
#  this uses the v5.1 auto-undo (60 s, shutdown timer paused): with no
#  check-in the previous code is re-applied the same way; if there was none
#  (00), the live setting goes back to 00 and wifimon's own modprobe file is
#  removed -- a setting raspi-config already saved stays until changed
#  again. Refused while the hotspot is on or another change is waiting.
#  Logged in the Activity log.
#
#v5.13 — nmcli additions, stage 4 of 4: emergency hotspot, started by
#  hand only (never automatically). "Start hotspot" on the Radio & device
#  card: network name (default <hostname>-setup), password (8-63
#  characters, a random one offered), auto-stop after 15/30/60/120
#  minutes. The hotspot is a NetworkManager profile written as a keyfile
#  (0600; the password never goes on a command line): mode=ap, 2.4 GHz,
#  WPA2 (CCMP), ipv4.method=shared (NetworkManager hands out addresses with
#  dnsmasq -- the button is greyed out with a note when dnsmasq isn't
#  installed), autoconnect off, bound to the WiFi device. Each start
#  replaces the previous hotspot profile. Hotspot profiles never appear in
#  Saved networks, the reconnect list or the join-order sync.
#  The Pi has one radio, so the node leaves its WiFi while the hotspot is
#  on; the confirm dialog says so and gives the address to open once your
#  phone has joined (NetworkManager's shared address, normally
#  http://10.42.0.1:8991). While it's on, the no-connection shutdown timer
#  and auto-reconnect are paused (the low-voltage timer is not), other
#  changes are refused except "Save only" in Add network -- so a hotel
#  network can be added from the phone -- and a banner shows the time left.
#  "Stop hotspot" (or the auto-stop) takes the hotspot down and runs the
#  v5.2 connect job to the chosen network (default: the one the node was on
#  before), with the usual known-good fallback. The hotspot state is kept
#  in /run/wifimon/hotspot.json, so if wifimon restarts while it's on, the
#  hotspot is taken down at start and normal reconnecting resumes.
#
#v5.12 — nmcli additions, stage 3 of 4: per-network options. Saved
#  networks that have a NetworkManager profile get an "Options" button:
#  IP address (Automatic / Fixed / Automatic with custom DNS -- address +
#  prefix, gateway, 1-3 DNS servers; the gateway must be inside the
#  address's network), "Use this Pi's real MAC address"
#  (802-11-wireless.cloned-mac-address = permanent, for hotels and routers
#  that register devices by MAC), and Band: Any / 2.4 GHz only / 5 GHz
#  only (802-11-wireless.band; only offered when the WiFi device can do
#  5 GHz, checked once with `iw phy` -- a Pi Zero 2W is 2.4 GHz only).
#  Change from the plan: these live in their own Options form, not the
#  Edit form, because Edit replaces the profile and so refuses the network
#  in use, while options use `nmcli connection modify` and do work on it.
#  Options changes on the network in use re-activate it, which briefly
#  drops the WiFi, so they use the v5.1 auto-undo with a 2-minute window
#  (the page may have to be reopened at a new address, and log in again
#  there): the previous values are restored and the network re-activated
#  if no page checks in. On other networks it just saves the options.
#  Only values that actually change are written. Add network gains the
#  real-MAC checkbox, and Edit now carries IP / MAC / band options over to
#  the replacement profile (as v5.7 did for auto-join and power save).
#
#v5.11 — Shutdown reports, stage 4 of 4: unclean stops. At start wifimon
#  writes a small marker (/var/lib/wifimon/running.json: start time, boot
#  id, pid, version, fsynced) and removes it on a normal stop. If the
#  marker is still there at the next start and no shutdown report was
#  saved after that run began, an "unclean stop" report is saved: same
#  boot id = wifimon itself stopped unexpectedly (crash / killed) while
#  the node kept running; different boot id = the node lost power or
#  restarted without a clean shutdown (e.g. a brownout faster than the
#  low-voltage timer). It includes the end of the previous boot's journal
#  when the journal is kept on disk (otherwise it says so). Cost: one small
#  write per start and one delete per stop -- no periodic heartbeat.
#
#v5.10 — Shutdown reports, stage 3 of 4: dashboard. New "Shutdown reports"
#  section in the Activity log card: saved reports newest first, View
#  (the plain-text version in a scroll box), Download (.txt), Delete (with
#  confirmation), and "Save a test report", which writes a full report --
#  snapshot, Activity log, diagnostics -- without shutting anything down.
#  After a restart, a banner says when and why the node last shut down
#  (shutdown and unclean-stop reports from the last 7 days, older than the
#  current run), with View and Dismiss (remembered in the browser, so no
#  disk write). API, login required: GET /api/reports, GET /api/report
#  ?name=&format=text|json[&download=1], POST /api/reports/delete,
#  POST /api/reports/test. Report names are checked against a strict
#  pattern, so nothing outside the report folder can be read or deleted.
#
#v5.9 — Shutdown reports, stage 2 of 4: save the report. do_shutdown()
#  now writes a report to /var/log/wifimon/ (folder 0700, files 0600)
#  BEFORE it asks systemd to power off. Correction to the plan: power-off
#  starts at once (the 15 s in do_shutdown is only the fallback before
#  `poweroff -f`), so the report is finished first, which delays the
#  shutdown by at most ~10 s (5 s for low voltage). Order: (1) the reason,
#  thresholds in force, the stage-1 snapshots (first, countdown, final) and
#  the whole Activity log are written straight away -- temp file, fsync,
#  rename, fsync the folder -- so a report exists even if power dies next;
#  (2) last-moment diagnostics are gathered within the time budget (WiFi
#  link, device list, addresses, routes, rfkill, the last NetworkManager or
#  wpa_supplicant log lines, the last kernel messages -- each command
#  time-limited, each output capped at 8 KB) and the report is rewritten
#  the same safe way. Reports are capped at REPORT_MAX_BYTES (256 KB; when
#  over, diagnostics are shortened first, then middle snapshots, then the
#  oldest log lines, and the report says it was trimmed) and only the
#  newest REPORT_KEEP (10) are kept. Nothing secret goes in: the Activity
#  log never holds passwords. --uninstall leaves the reports in place.
#
#v5.8 — Shutdown reports, stage 1 of 4: record the lead-up (memory only;
#  nothing is written to the SD card in this stage). As soon as either
#  countdown starts (no connection or low voltage), the watchdog starts
#  keeping snapshots of everything the Status card's More details shows --
#  connection, signal, network, Pi health, watchdog counters -- plus the
#  power readings, CPU temperature, the device in use and how old each
#  piece of data was. One snapshot when the problem starts (always kept),
#  then one every SNAPSHOT_EVERY_SECS (10 s; SNAPSHOT_LOWV_EVERY_SECS = 5 s
#  while the voltage is low), keeping the newest SNAPSHOT_KEEP (20). During
#  a no-connection countdown each snapshot also asks the status collector
#  for an early slow refresh so IP/DNS/network details aren't 30 s old.
#  When wifimon decides to shut down it takes one last snapshot from a
#  fresh collection (fast values only for low voltage, where time matters),
#  ready for stage 2 to save. If the problem clears first, or a dashboard
#  change pauses the timer, the recording is thrown away. The Watchdog card
#  shows while a recording is running; GET /api/snapshots (login needed)
#  returns it in full. Snapshots are copies of data wifimon already
#  collects, so the cost is small. (The country code / power save plan
#  moves to after the shutdown-report stages.)
#
#v5.7 — nmcli additions, stage 2 of 4 (quick buttons).
#  Reconnect now (Status card): runs the v5.2 connect job on the network
#  in use, so a reconnect that doesn't come back falls straight through to
#  the known-good networks, with the shutdown timer paused as usual. Same
#  one-at-a-time rule and confirm:true as every change.
#  Power save off: when the Status card sees power save on, it offers
#  "Turn off for this network" and "Turn off for all saved networks". This
#  sets 802-11-wireless.powersave = 2 (disable) on the NetworkManager
#  profile(s) -- so it survives reboots, unlike `iw ... set power_save
#  off` -- and, for the network in use, also runs that iw command so it
#  takes effect now without dropping the connection. Profiles already set
#  are not rewritten. The Edit form gains "Power save: leave as default /
#  off".
#  Auto-join on/off: a toggle on each saved network that has a
#  NetworkManager profile (connection.autoconnect). Off means neither
#  NetworkManager nor wifimon joins it by itself: the watchdog's retries
#  and the connect job's known-good fallback both skip it. Connect still
#  works for it, and a failed switch can still go back to it as the
#  network it was just on (that return is part of the switch you asked
#  for, not the node choosing a network).
#  Edit now keeps a network's auto-join and power-save settings when it
#  replaces the profile (v5.3-v5.6 reset them to NetworkManager's defaults).
#
#v5.6 — nmcli additions, stage 1 of 4 (automatic features; no new buttons).
#  Join-order sync: whenever the reconnect list changes (arrows, Add,
#  Add to list, Take off list, Edit, Delete, or a tag change) and once at
#  start, each NetworkManager profile on the list gets
#  connection.autoconnect-priority = its place counted from the bottom
#  (top of an N-long list = N), so NetworkManager's own choice at boot
#  matches wifimon's order. Profiles not on the list are left alone. A
#  profile is only modified when its value differs (each modify rewrites
#  its file -- SD wear), runs in its own thread with a 1 s pause to batch
#  quick arrow clicks, and never touches the live connection.
#  NetworkManager events: a background `nmcli monitor` feeds WiFi lines
#  into the Activity log -- "wlan0: disconnected", "wlan0: using
#  connection 'Home'", "wlan0: connecting (need authentication)" (flagged
#  as a possible wrong password), "Connectivity is now 'portal'", primary
#  connection changes. Other devices, p2p-dev lines, and connect sub-steps
#  are dropped; an identical line within 10 s is skipped and at most 30
#  lines a minute are logged. If the monitor exits it restarts itself
#  (5 s, doubling to a 5 min ceiling). Runs with LC_ALL=C so the messages
#  it matches aren't translated.
#  Login-page check: new watchdog setting "Detect login pages" (off by
#  default). On, it writes /etc/NetworkManager/conf.d/
#  90-wifimon-connectivity.conf (NetworkManager then fetches
#  http://nmcheck.gnome.org/check_network_status.txt about every 5 min)
#  and runs `nmcli general reload conf` -- never a NetworkManager restart,
#  which would drop the WiFi. Off removes the file; wifimon owns that file
#  and reconciles it at every start, and --uninstall removes it. While on,
#  the page shows a banner when NetworkManager reports "portal" (the
#  network wants a login page, which a headless node can't complete), the
#  Status card's Internet line says so, and a failed Connect names it as
#  the reason (the job's final message and its step list now show each
#  failed step's reason). With the setting off wifimon ignores NM's
#  connectivity state, because NM then reports "full" regardless.
#  Also: changing watchdog settings only restarts running countdowns when
#  a timer-related value actually changed.
#  Decided for stage 4: the emergency hotspot will be started by hand
#  only (no automatic start instead of shutting down).
#
#v5.5 — The dashboard is served over plain HTTP by default, like the rest
#  of the suite's web tools: USE_TLS in the CONFIG block now defaults to
#  False (set it True to get the v5.0-v5.4 self-signed HTTPS back).
#  With HTTPS off by choice, --install no longer makes a certificate and
#  prints an http:// address, and the red "Not encrypted" badge and the
#  startup warning are gone; they now appear only when HTTPS is switched
#  on but can't start. A certificate already made in /etc/wifimon/tls is
#  left in place and simply not used. The "come back at ..." hint shown
#  before a network switch now uses whichever scheme the page is on.
#  Note: with plain HTTP the root password (login, Show password) and any
#  WiFi password shown cross the network unencrypted -- use the dashboard
#  on a trusted network. The login cookie already drops its HTTPS-only
#  flag when HTTPS is off.
#
#v5.4 — Dashboard Stage 5 of 5 (the wifimon + wifi_menu.sh dashboard
#  conversion is complete). New "Activity log" card: the last 100 wifimon
#  log events at INFO and above -- connection drops and restores, retries,
#  voltage warnings, every dashboard action, password Shows, failed
#  logins -- kept in memory only (nothing written to the SD card, gone on
#  restart; the journal still has the full history). The page fetches only
#  entries newer than the last one it has (/api/log?after=N), can show
#  warnings and errors only, and has a Copy button.
#  Security audit of the whole v5.3 file (same process as the v4.8 audit).
#  Fixed:
#   A1 Log line forging: text from outside -- network names, nmcli error
#      output -- was logged as-is, so a control character or newline in it
#      could fake extra journal lines. A filter on the wifimon logger now
#      replaces control characters in every message, which also covers
#      the new Activity log. (The page itself was already safe: every value
#      is inserted as text, never as HTML.)
#   A2 Password in exception text: when `nmcli device wifi connect ...
#      password <psk>` or `wpa_cli set_network ... psk` timed out, the
#      TimeoutExpired message -- which includes the whole command, password
#      and all -- was logged (DEBUG only, so off by default). It now logs
#      "timed out" without the command; _nmcli_ok() does the same.
#   A3 Connection cap was global only: one client holding 16 idle
#      keep-alive connections could lock everyone else out of the
#      dashboard. Now also capped at MAX_CONNECTIONS_PER_IP (8) per address.
#   A4 _IFACE_RE allowed a device name starting with '-', which a command
#      could read as an option. Names must now start with a letter or digit
#      (they're also still checked against the real device list).
#  Checked and fine: every POST needs a session plus the CSRF headers;
#  every change needs confirm:true server-side; no shell anywhere (argv
#  lists only); config, state, pending, keyfile and TLS key files are
#  written 0600 with atomic replace; passwords never appear in /api/status
#  or the logs; Show password needs the root password again and shares the
#  login lockout; the settings ranges can't produce an instant shutdown.
#  Accepted risks, documented, not changed:
#   R1 A network with no NetworkManager profile (wifimon.conf-only, or the
#      wpa_cli backend) still gets its password on nmcli / wpa_cli's
#      command line during a watchdog retry (the v4.8 accepted risk). Any
#      network saved from the dashboard has a profile, so it never does.
#   R2 Sessions slide with activity and have no absolute lifetime; an open
#      dashboard tab stays logged in. They end on logout or restart.
#   R3 No Host-header allow-list. A DNS-rebinding page can't use the
#      session (the cookie belongs to the node's own name) and, over HTTPS,
#      fails the certificate check; it could only try logins, which the
#      per-IP lockout limits.
#   R4 If openssl is missing the dashboard falls back to plain HTTP (red
#      badge + journal warning), and Show password works there too, by
#      the user's decision in the Stage 1 plan.
#   R5 A slow PAM failure (pam_faildelay) holds a connection thread for a
#      couple of seconds; the connection caps bound this, and the watchdog
#      runs in its own thread either way.
#  Verified off-hardware: new tests for each fix (forged-newline SSID,
#  timed-out connect with a password, per-IP cap, dashed device name),
#  the Activity log API and card in jsdom, and every earlier stage's
#  suite re-run on both copies. Not verified on a real Pi.
#
#v5.3 — Dashboard Stage 4 of 5.
#  Saved networks card: up/down arrows set the watchdog's reconnect order
#  (priorities are renumbered 1..N on every move). NetworkManager-only
#  profiles get "Add to reconnect list", and "Add all" imports every one
#  of them at once (this replaces --setup-wifi's import for NM systems;
#  names come from each profile's SSID, not its profile name). "Take off
#  list" removes a network from wifimon.conf but keeps its NM profile.
#  "Edit" changes security, password (blank = keep the current one) and
#  hidden: a fresh keyfile profile is loaded first and the old profile(s)
#  deleted only after that worked, so a failed edit changes nothing; the
#  network is re-tagged Not verified. The network in use can't be edited
#  (replacing its profile would drop the connection).
#  Watchdog card: "Change settings" edits the shutdown / reconnect
#  settings -- no-connection shutdown, low-voltage shutdown, low-voltage
#  level, reconnect interval, check interval, internet-check address --
#  within fixed safe ranges, plus "Reset to defaults" (the CONFIG block
#  values). They apply at once and are saved in /etc/wifimon/state.json
#  (merged with the saved device, compare-before-write). Any countdown
#  running when settings change starts over, so shortening a limit can
#  never trigger an instant shutdown.
#  Watchdog reconnect: when a network has a NetworkManager profile, the
#  watchdog now starts that profile (`nmcli connection up`) instead of
#  `nmcli device wifi connect <ssid> password <psk>`. That keeps the
#  password off the command line whenever a profile exists, and stops NM
#  from growing duplicate profiles. Networks without a profile still use
#  the v4.8 call (the documented accepted risk).
#
#v5.2 — Dashboard Stage 3 of 5. Two new cards.
#  "Saved networks": ONE list merging NetworkManager's WiFi profiles with
#  wifimon.conf's reconnect list, one row per network name. Each row
#  shows its priority (wifimon.conf order; "not in the watchdog list" for
#  NM-only profiles), a tag -- Known good (has connected and passed the
#  connection check at least once), Not verified, or Failed (last attempt
#  didn't connect) -- the password hidden behind Show, and Connect /
#  Delete. Show asks for the root password again every time (same per-IP
#  lockout as login), is fetched one network at a time, never included
#  in /api/status, hides itself after 30 s, and is logged. Delete refuses
#  the network in use. "Add network" form: name (typed or picked from the
#  scan), Open / WPA2 / WPA3, password, hidden; "Save & connect" or "Save
#  only". A new network is written to NetworkManager as a keyfile
#  (/etc/NetworkManager/system-connections, 0600) and loaded with
#  `nmcli connection load`, so its password never appears on any command
#  line; it is also added to wifimon.conf at the bottom of the priority
#  order, tagged Not verified.
#  "Nearby networks": NM's scan list (strongest entry per name, hidden
#  names left out) with a Rescan button; Connect for saved or open
#  networks, "Add..." (opens the form pre-filled) for secured unsaved ones.
#  Connecting runs as a background job so the page can lose contact
#  mid-switch: pause the shutdown timer, remember the current network as
#  the return point, give the new one NEW_NETWORK_TEST_SECS (30 s) to
#  join and pass the watchdog's connection check. If it fails it's
#  tagged Failed (never deleted, and nothing else is touched), then the
#  job retries the return point, then Known good networks by priority,
#  FALLBACK_TEST_SECS (20 s) each, skipping networks a fresh scan doesn't
#  see (hidden ones are always tried). If all fail the pause ends at once
#  and the normal watchdog takes over. The result shows as a popup the
#  next time the page reaches the node. One job or pending change at a
#  time (shares Stage 2's lock).
#  Tags are written to wifimon.conf only when they change. The watchdog
#  also tags a wifimon.conf network Known good when it sees the node
#  connected on it, and reloads the list when the dashboard changes it
#  (v4.8 only loaded it at start). Its own reconnect order is now: the
#  network just lost, then Known good, then untagged / Not verified, then
#  Failed -- by priority within each group.
#  Fixes carried from v4.8: wifimon.conf is now read and written with
#  ConfigParser(interpolation=None) -- before, a '%' in a password made
#  load_wifi_networks() fail and save_wifi_networks() raise. And because
#  ConfigParser trims spaces around values, a password that starts or
#  ends with a space is now stored as psk_b64 (base64) instead of psk.
#  Fix to v5.1: change handlers now send their reply only after releasing
#  the action lock, so a quick follow-up click can't be refused as "busy".
#  These cards need NetworkManager (nmcli); they say so if it's missing.
#  Verified off-hardware with the fake-nmcli harness through the live
#  HTTPS server; not verified against a real NetworkManager, keyfile
#  loading on Pi OS, or a WPA3 network.
#
#v5.1 — Dashboard Stage 2 of 5. New "Radio & device" card: turn the
#  WiFi radio on/off, disconnect a WiFi device, or switch which WiFi
#  device is in use (the web version of wifi_menu.sh options 2-5; needs
#  NetworkManager/nmcli, the card says so if it's missing).
#  Auto-undo: turning the radio off, disconnecting, or switching devices
#  becomes a "pending change". The page checks in automatically on its
#  next successful poll at least 5 s after the change; if no check-in
#  arrives within CHANGE_UNDO_SECS (60 s) -- e.g. the change cut off the
#  browser's own WiFi path -- wifimon puts things back (radio on + the
#  previous profile, reconnect the device, or switch back). An "Undo now"
#  button is on the pending banner. One pending change at a time. The
#  pending change is also written to /run/wifimon/pending_change.json
#  (tmpfs, no SD wear) before the action runs, so if wifimon restarts
#  mid-change it undoes it on the next start rather than leaving the
#  node cut off.
#  Timer pause: any change made from the card pauses the no-connection
#  shutdown timer (and auto-reconnect, which would otherwise fight the
#  change) for CHANGE_GRACE_SECS (180 s). While paused the timer is
#  cleared, so if the node is still offline afterwards it starts again
#  from the full NO_CONN_SHUTDOWN_SECS. The low-voltage timer is never
#  paused.
#  Switching devices moves the watchdog to the new device at run time
#  (INTERFACE becomes a live setting) and saves the choice to
#  /etc/wifimon/state.json (0600, compare-before-write, written only on a
#  switch). On start, a saved device that still exists overrides INTERFACE
#  from the CONFIG block.
#  The page now knows which interface the browser reached it through; the
#  confirm dialog warns when a change may cut the browser off.
#  Also: the status collector can be asked for an early slow refresh, so
#  the card updates right after a change instead of up to 30 s later.
#  Verified off-hardware: a fake nmcli (state machine) driven through the
#  live HTTPS server -- radio off/on, disconnect, switch, auto-keep,
#  auto-undo on timeout, Undo now, one-at-a-time, restart recovery,
#  timer pause in the watchdog loop -- plus the page in jsdom. Not
#  verified on a real Pi with two WiFi adapters.
#
#v5.0 — Dashboard Stage 1 of 5 (merging wifimon + wifi_menu.sh into one
#  dashboard service). The watchdog loop that used to be run() now runs
#  in its own thread (_watchdog_loop); its decisions are unchanged from
#  v4.8 -- same timers, same thresholds, same reconnect order, same
#  shutdown path and shutdown_state.json -- it only publishes its state
#  (_wd) for the dashboard, and each pass is wrapped so one unexpected
#  error is logged instead of silently ending the watchdog. If the web
#  server can't start (port taken, TLS failure), the watchdog keeps
#  running without it.
#  New: a second thread (_collector_loop) gathers WiFi details for the
#  page from cheap sources -- /sys, /proc/net/wireless, iw, nmcli, ip,
#  vcgencmd -- on two speeds (fast every 5 s: signal, counters, voltage;
#  slow every 30 s: IP, DNS, security, country, power save). The page
#  only ever reads that cached snapshot, so polling the page never runs
#  nmcli. Nothing is written to the SD card.
#  New: HTTPS on port 8991 with a per-node self-signed certificate made
#  by openssl on first start (/etc/wifimon/tls, key 0600, EC P-256,
#  10 years). If openssl is missing it falls back to plain HTTP and says
#  so loudly (log + red badge on the page).
#  New: root-password login (PAM first, /etc/shadow + libcrypt fallback,
#  same approach as the rest of the suite), independent of the other
#  suite tools: own cookie (wifimon_session), own in-memory session store
#  (12 h, sliding, refreshed Set-Cookie on every authenticated response),
#  per-IP lockout with exponential backoff after 5 failed tries, CSRF
#  check on every POST (X-Requested-With + JSON Content-Type + Origin
#  must match Host), security headers (CSP, X-Frame-Options, nosniff,
#  no-referrer), 16 KB body cap, 16-connection cap.
#  New cards: Status (network name, signal meter, IP, internet check,
#  plus a "More details" panel: Connection, Signal, Network, Pi health,
#  Watchdog), Watchdog (live countdowns, thresholds, voltage/throttle
#  flags), Service (version, uptime, encryption, restart, log out).
#  Restart runs through a detached systemd-run unit (suite standard for
#  anything that restarts its own process) and needs confirm:true.
#  --install now also creates the certificate and prints the dashboard
#  address, and warns if root has no password (login would fail).
#  Verified off-hardware only: parsers against sample iw / nmcli /
#  /proc / vcgencmd output, a live in-process HTTPS server (login,
#  lockout, CSRF, headers, sessions, status JSON), and the page script
#  in jsdom. Not verified on a real Pi: real iw/nmcli output on the
#  Zero 2W, PAM login with the real root password, the self-restart.
#
#v4.8 — Security audit fixes. (1) save_wifi_networks() and
#  _ensure_config() now write wifimon.conf (plaintext WiFi PSKs) via a
#  shared _write_config_atomic() helper: os.open(..., 0o600) + tmp-file
#  + os.replace(), instead of plain open() followed by a separate
#  os.chmod(). This closes two gaps: a brief window where the file
#  existed with default-umask permissions before the chmod landed, and
#  the lack of crash-safety (a mid-write interruption -- this daemon
#  watchdog-reboots the node on its own -- could previously truncate
#  the config and lose every saved network). Matches the pattern
#  _write_shutdown_state() already used. (2) _connect_wpa_cli() now
#  escapes embedded \" and \\ in SSID/PSK values via _wpa_cli_quote()
#  before wrapping them in wpa_cli's quoted-string syntax -- a raw "
#  in an SSID (broadcastable by anyone nearby) could previously break
#  wpa_cli's own parsing of the set_network command. Still never
#  touches a shell (subprocess is always called with an argv list), so
#  this was never OS command injection, just unescaped input for
#  wpa_cli's own quoting. (3) run() now logs a warning if not running
#  as root, matching the check install_service()/uninstall_service()/
#  run_wifi_setup() already had. Not fixed, documented as accepted
#  risk: nmcli/wpa_cli both put the PSK on their own subprocess
#  command line (visible via ps/proc to another *local* user for that
#  call's duration) -- avoiding this needs NetworkManager D-Bus or the
#  wpa_supplicant control socket instead of these CLIs, a materially
#  bigger change than this fix warranted.
#
#v4.7 — Before triggering a shutdown, wifimon now writes a small JSON
#  state file to /run/wifimon/shutdown_state.json (active/reason/trigger/
#  since). This is written first thing inside do_shutdown(), well before
#  the actual poweroff, so asl_dvs_dashboard and sysmon — which already
#  poll their own /api/status every few seconds — have time to pick it
#  up and show a persistent "wifimon is shutting this node down" popup
#  before the node goes dark. /run is tmpfs and is wiped on every real
#  reboot, so the flag self-clears; run() also clears it defensively on
#  startup in case wifimon was restarted without a full reboot (e.g.
#  after a crash) so a stale flag can't get stuck showing forever.
#
#v4.6 — Fixed the shebang: it was `# -*- coding: utf-8 -*-` on line 1
#  and `#!/usr/bin/env python3` commented out on line 2, so running the
#  file directly (./wifimon.py) couldn't find an interpreter — it only
#  ever worked when invoked as `python3 wifimon.py`. The shebang is now
#  the literal, uncommented first line; the coding declaration moved to
#  line 2, which PEP 263 also allows. No other change.
#
#v4.5 — Line-ending normalization only. No behavior change. Lines 252-412
#  (the WiFi-setup-wizard block: _prompt_manual_networks through
#  run_wifi_setup) had plain LF endings while the rest of the file used
#  CRLF — evidently pasted in from a different editor/source at some
#  point without normalizing. Whole file is now LF throughout, matching
#  the rest of the ASL-DVS-M17 suite (asl_dvs_m17_44helper, instmon).
#  Verified: every line's content is byte-identical to v4.4 once both
#  are normalized for comparison — only line-ending bytes changed.
#
#v4.3 — Added /etc/wifimon/wifimon.conf with a [network_N] section per
#  known WiFi network (ssid/psk/priority). While the connection is down,
#  wifimon now aggressively retries connecting — the network that was
#  just lost first, then the configured networks in priority order —
#  using nmcli if present, falling back to wpa_cli. This runs alongside
#  the existing shutdown countdown, not instead of it: NO_CONN_SHUTDOWN_SECS
#  still fires on schedule no matter how many reconnect attempts happened.
#  If wifimon.conf has no networks configured, this is a no-op and
#  behavior is unchanged from v4.2.
#
#v4.4 — --install now prompts for WiFi setup on an interactive terminal
#  if no networks are configured yet: enter one manually, or import
#  networks already saved on the system (nmcli connection profiles or
#  wpa_supplicant.conf). Skipped automatically for non-interactive
#  installs, and never re-prompts if wifimon.conf already has networks
#  in it. The same menu is also available standalone via --setup-wifi.
#
#Usage:
#  sudo python3 wifimon.py --install      Install as systemd service & start
#  sudo python3 wifimon.py --uninstall    Stop & remove systemd service
#  sudo python3 wifimon.py --setup-wifi   Add/import WiFi networks
#  python3 wifimon.py                     Run watchdog + dashboard in foreground
#
#Dashboard:  http://<node>.local:8991  (log in with the root password)
#"""

import argparse
import base64
import configparser
import ctypes
import ctypes.util
import getpass
import hmac
import http.cookies
import json
import logging
import os
import re
import secrets
import select
import fcntl
import array
import shutil
import signal
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote as urllib_unquote, urlsplit

APP_VERSION = "5.21"

# ── CONFIG ──────────────────────────────────────────────────────────────
# Watchdog (unchanged from v4.8)
INTERFACE                 = "wlan0"
PING_TARGET               = "8.8.8.8"
CHECK_INTERVAL            = 5
PING_TIMEOUT              = 2
NO_CONN_SHUTDOWN_SECS     = 180
LOW_VOLTAGE_THRESHOLD     = 0.90
LOW_VOLTAGE_SHUTDOWN_SECS = 30
RECONNECT_INTERVAL_SECS   = 15
MISSES_BEFORE_LOST        = 3    # failed checks in a row (WiFi link still up) before "lost" (v5.16)
STUCK_LINK_SECS           = 60   # joined but no internet this long before any reconnect (v5.16)
NM_HEAD_START_SECS        = 30   # after a real drop, let NetworkManager rejoin by itself first (v5.17)
NM_BUSY_MAX_SECS          = 45   # longest wifimon waits in a row while NetworkManager is mid-join (v5.17)
RECONNECT_VERIFY_SECS     = 15   # time a joined network gets to pass the connection check (v5.17)
AUTH_WARN_SECS            = 30   # password handshake still not done this long -> warn (v5.19)

# Dashboard (new in v5.0)
HTTP_BIND        = "0.0.0.0"   # listen on every interface
HTTP_PORT        = 8991
USE_TLS          = False       # True = self-signed HTTPS (needs openssl); False = plain HTTP
SESSION_TTL_SECS = 12 * 3600   # a login lasts 12 h, extended by activity
STATUS_FAST_SECS = 5           # signal, data counters, voltage
STATUS_SLOW_SECS = 30          # IP, DNS, security, country, power save
MAX_CONNECTIONS  = 16          # concurrent dashboard connections
MAX_CONNECTIONS_PER_IP = 8     # of those, from any one address (v5.4)

# Dashboard changes (new in v5.1)
CHANGE_UNDO_SECS  = 60         # risky change undoes itself unless the page checks in within this
CHANGE_GRACE_SECS = 180        # shutdown timer + auto-reconnect paused this long after a change

# Connecting to networks (new in v5.2)
NEW_NETWORK_TEST_SECS = 30     # time a network gets to join + pass the connection check
FALLBACK_TEST_SECS    = 20     # time each fallback network gets

# Shutdown reports (new in v5.8)
SNAPSHOT_EVERY_SECS      = 10  # snapshot interval during a no-connection countdown
SNAPSHOT_LOWV_EVERY_SECS = 5   # ... and while the voltage is low
SNAPSHOT_KEEP            = 20  # newest snapshots kept (plus the first one)
REPORT_KEEP              = 10  # shutdown reports kept in REPORT_DIR (v5.9)
REPORT_MAX_BYTES         = 256 * 1024

# Login-page detection (new in v5.6; also switchable on the dashboard)
DETECT_LOGIN_PAGES    = False  # True = NetworkManager checks nmcheck.gnome.org every ~5 min

# WiFi power save (new in v5.18; also switchable on the dashboard)
KEEP_POWERSAVE_OFF    = False  # True = power save off for every network, re-checked after reconnects

# Adapter Auto / Keep on / Keep off (new in v5.21; set per adapter on the dashboard)
DEVMODE_CHECK_SECS    = 10     # how often Keep on / Keep off adapters are checked (also on every NM event)
# ── END CONFIG ──────────────────────────────────────────────────────────

CONFIG_DIR  = "/etc/wifimon"
CONFIG_FILE = os.path.join(CONFIG_DIR, "wifimon.conf")
TLS_DIR     = os.path.join(CONFIG_DIR, "tls")
TLS_CERT    = os.path.join(TLS_DIR, "cert.pem")
TLS_KEY     = os.path.join(TLS_DIR, "key.pem")

SHUTDOWN_STATE_DIR  = "/run/wifimon"
SHUTDOWN_STATE_FILE = os.path.join(SHUTDOWN_STATE_DIR, "shutdown_state.json")
PENDING_FILE        = os.path.join(SHUTDOWN_STATE_DIR, "pending_change.json")
STATE_FILE          = os.path.join(CONFIG_DIR, "state.json")
NM_CONN_DIR         = "/etc/NetworkManager/system-connections"
NM_CONF_FILE        = "/etc/NetworkManager/conf.d/90-wifimon-connectivity.conf"
NM_PS_CONF_FILE     = "/etc/NetworkManager/conf.d/90-wifimon-powersave.conf"
HEALTH_FILE         = os.path.join(SHUTDOWN_STATE_DIR, "health.json")
ROAM_MODPROBE       = "/etc/modprobe.d/wifimon-brcmfmac.conf"
REPORT_DIR          = "/var/log/wifimon"
RUN_MARKER          = "/var/lib/wifimon/running.json"

_DEFAULT_CONFIG = {
    "network_1": {
        "ssid": "",
        "psk": "",
        "priority": "1",
    },
}


def _write_config_atomic(cfg: "configparser.ConfigParser") -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp_path = CONFIG_FILE + ".tmp"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        cfg.write(f)
    os.replace(tmp_path, CONFIG_FILE)


def _ensure_config() -> None:
    if os.path.exists(CONFIG_FILE):
        return
    cfg = configparser.ConfigParser(interpolation=None)
    for section, values in _DEFAULT_CONFIG.items():
        cfg[section] = values
    _write_config_atomic(cfg)
    log.info("Created default config at %s", CONFIG_FILE)


def load_wifi_networks() -> List[Dict[str, object]]:
    _ensure_config()
    cfg = configparser.ConfigParser(interpolation=None)
    try:
        cfg.read(CONFIG_FILE)
    except configparser.Error as e:
        log.error("Failed to parse %s: %s", CONFIG_FILE, e)
        return []

    networks = []
    for section in cfg.sections():
        if not section.startswith("network_"):
            continue
        ssid = cfg.get(section, "ssid", fallback="").strip()
        if not ssid:
            continue
        psk = cfg.get(section, "psk", fallback="")
        psk_b64 = cfg.get(section, "psk_b64", fallback="").strip()
        if psk_b64:
            try:
                psk = base64.b64decode(psk_b64, validate=True).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                log.error("Bad psk_b64 for %s in %s", ssid, CONFIG_FILE)
        try:
            priority = int(cfg.get(section, "priority", fallback="99"))
        except ValueError:
            priority = 99
        net: Dict[str, object] = {"ssid": ssid, "psk": psk, "priority": priority}
        for key in ("status", "security"):
            value = cfg.get(section, key, fallback="").strip()
            if value:
                net[key] = value
        if cfg.get(section, "hidden", fallback="").strip().lower() in ("yes", "true", "1"):
            net["hidden"] = True
        networks.append(net)

    networks.sort(key=lambda n: n["priority"])
    return networks


def save_wifi_networks(networks: List[Dict[str, object]], quiet: bool = False) -> None:
    cfg = configparser.ConfigParser(interpolation=None)
    for i, n in enumerate(networks, start=1):
        psk = str(n.get("psk", ""))
        section = {
            "ssid": n["ssid"],
            "psk": psk,
            "priority": str(n.get("priority", i)),
        }
        if psk != psk.strip():
            section["psk"] = ""
            section["psk_b64"] = base64.b64encode(psk.encode("utf-8")).decode("ascii")
        for key in ("status", "security"):
            if n.get(key):
                section[key] = str(n[key])
        if n.get("hidden"):
            section["hidden"] = "yes"
        cfg[f"network_{i}"] = section
    _write_config_atomic(cfg)
    if not quiet:
        print(f"  [+] Saved {len(networks)} network(s) to {CONFIG_FILE}")

INSTALL_BIN_PATH = "/usr/local/bin/wifimon.py"
SYSTEMD_SERVICE_PATH = "/etc/systemd/system/wifimon.service"

SYSTEMD_SERVICE_CONTENT = f"""[Unit]
Description=WiFi and Voltage Watchdog + Dashboard (port {HTTP_PORT})
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/bin/wifimon.py
Restart=always
RestartSec=3s
StandardOutput=journal
StandardError=journal

Nice=-5
OOMScoreAdjust=-500

[Install]
WantedBy=multi-user.target
"""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("wifimon")


_LOG_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


class _SanitizeFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        clean = _LOG_CTRL_RE.sub(" ", msg)
        record.msg, record.args = clean, None
        return True


_ACTIVITY_MAX = 100
_activity_lock = threading.Lock()
_activity: List[Dict[str, object]] = []
_activity_seq = 0


class _ActivityHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        global _activity_seq
        try:
            msg = record.getMessage()[:500]
        except Exception:
            return
        with _activity_lock:
            _activity_seq += 1
            _activity.append({"seq": _activity_seq, "at": record.created,
                              "level": record.levelname.lower(), "msg": msg})
            del _activity[:-_ACTIVITY_MAX]


def _activity_since(after: int) -> Dict[str, object]:
    with _activity_lock:
        return {"seq": _activity_seq,
                "entries": [dict(e) for e in _activity if int(e["seq"]) > after]}


log.addFilter(_SanitizeFilter())
log.addHandler(_ActivityHandler(logging.INFO))

_shutdown_event = threading.Event()

def _handle_sigterm(signum: int, frame: object) -> None:
    log.info("Signal %d received — exiting cleanly", signum)
    _shutdown_event.set()

signal.signal(signal.SIGTERM, _handle_sigterm)
signal.signal(signal.SIGINT,  _handle_sigterm)

def install_service() -> None:
    if os.geteuid() != 0:
        print("Error: Installation requires root privileges. Run with 'sudo'.")
        sys.exit(1)

    current_script = os.path.abspath(__file__)

    print("Installing wifimon...")

    if current_script != INSTALL_BIN_PATH:
        shutil.copy2(current_script, INSTALL_BIN_PATH)
        print(f"  [+] Copied script to {INSTALL_BIN_PATH}")
    os.chmod(INSTALL_BIN_PATH, 0o755)

    if USE_TLS:
        if _ensure_tls_cert():
            print(f"  [+] HTTPS certificate ready in {TLS_DIR}")
        else:
            print("  [!] Could not create an HTTPS certificate (is openssl installed?)")
            print("      The dashboard will fall back to plain HTTP.")

    with open(SYSTEMD_SERVICE_PATH, "w") as f:
        f.write(SYSTEMD_SERVICE_CONTENT)
    print(f"  [+] Created service file at {SYSTEMD_SERVICE_PATH}")

    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "wifimon.service"], check=True)
    subprocess.run(["systemctl", "restart", "wifimon.service"], check=True)
    print("  [+] Enabled and restarted wifimon.service")

    if not load_wifi_networks():
        if sys.stdin.isatty():
            run_wifi_setup()
            if load_wifi_networks():
                subprocess.run(["systemctl", "restart", "wifimon.service"], check=False)
                print("  [+] Restarted wifimon.service to pick up the new network(s)")
        else:
            print(f"  [i] No WiFi networks configured. Run "
                  f"'sudo python3 {INSTALL_BIN_PATH} --setup-wifi' to add some,")
            print(f"      or edit {CONFIG_FILE} directly.")

    scheme = "https" if (USE_TLS and os.path.exists(TLS_CERT)) else "http"
    print(f"\nDashboard: {scheme}://{socket.gethostname()}.local:{HTTP_PORT}"
          f"  (or the node's IP address)")
    print("  Log in with the root password.")
    if _root_password_status() != "set":
        print("  [!] root has no usable password, so dashboard login will fail.")
        print("      Set one with:  sudo passwd root")
    if scheme == "https":
        print("  The browser will warn about the self-signed certificate the first")
        print("  time. That's expected -- accept it once per browser.")

    print("\nInstallation complete! View logs anytime using:")
    print("  journalctl -u wifimon -f")

def uninstall_service() -> None:
    if os.geteuid() != 0:
        print("Error: Uninstallation requires root privileges. Run with 'sudo'.")
        sys.exit(1)

    print("Uninstalling wifimon...")

    subprocess.run(["systemctl", "disable", "--now", "wifimon.service"], stderr=subprocess.DEVNULL)
    print("  [-] Stopped and disabled wifimon.service")

    if os.path.exists(SYSTEMD_SERVICE_PATH):
        os.remove(SYSTEMD_SERVICE_PATH)
        print(f"  [-] Removed {SYSTEMD_SERVICE_PATH}")

    subprocess.run(["systemctl", "daemon-reload"], stderr=subprocess.DEVNULL)

    if os.path.exists(INSTALL_BIN_PATH):
        os.remove(INSTALL_BIN_PATH)
        print(f"  [-] Removed {INSTALL_BIN_PATH}")

    if os.path.isdir(REPORT_DIR):
        print(f"  [i] Shutdown reports kept in {REPORT_DIR} (delete it by hand if unwanted)")

    if os.path.exists(NM_CONF_FILE):
        os.remove(NM_CONF_FILE)
        subprocess.run(["nmcli", "general", "reload", "conf"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"  [-] Removed {NM_CONF_FILE}")

    if os.path.exists(NM_PS_CONF_FILE):
        os.remove(NM_PS_CONF_FILE)
        subprocess.run(["nmcli", "general", "reload", "conf"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"  [-] Removed {NM_PS_CONF_FILE}")

    if (_read_text(ROAM_MODPROBE) or "").startswith("# Written by wifimon"):
        os.remove(ROAM_MODPROBE)
        print(f"  [-] Removed {ROAM_MODPROBE} (takes effect after a reboot)")

    print("\nUninstallation complete.")

def _prompt_manual_networks(start_priority: int = 1) -> List[Dict[str, object]]:
    networks: List[Dict[str, object]] = []
    priority = start_priority
    while True:
        ssid = input("  SSID: ").strip()
        if not ssid:
            print("  (blank SSID, skipping)")
        else:
            psk = getpass.getpass("  Password (blank for open network): ")
            networks.append({"ssid": ssid, "psk": psk, "priority": priority})
            priority += 1
        again = input("Add another network? [y/N]: ").strip().lower()
        if again != "y":
            break
    return networks


def _discover_nmcli_networks() -> List[Dict[str, object]]:
    found: List[Dict[str, object]] = []
    try:
        out = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return found

    seen_ssids = set()
    for line in out.stdout.splitlines():
        parts = line.split(":")
        if len(parts) < 2 or parts[1] != "802-11-wireless":
            continue
        name = parts[0]
        if name in seen_ssids:
            continue
        seen_ssids.add(name)
        psk = ""
        try:
            sec = subprocess.run(
                ["nmcli", "-s", "-g", "802-11-wireless-security.psk",
                 "connection", "show", name],
                capture_output=True, text=True, timeout=10,
            )
            psk = sec.stdout.strip()
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        found.append({"ssid": name, "psk": psk, "found_pw": bool(psk)})
    return found


def _discover_wpa_supplicant_networks() -> List[Dict[str, object]]:
    found: List[Dict[str, object]] = []
    path = "/etc/wpa_supplicant/wpa_supplicant.conf"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return found

    for block in content.split("network={")[1:]:
        block = block.split("}", 1)[0]
        ssid = None
        psk = ""
        hashed = False
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("ssid="):
                ssid = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("psk="):
                raw = line.split("=", 1)[1].strip().strip('"')
                psk = raw
                if '"' not in line.split("=", 1)[1] and len(raw) == 64:
                    hashed = True
        if ssid:
            found.append({"ssid": ssid, "psk": psk, "found_pw": bool(psk),
                           "hashed": hashed})
    return found


def _discover_system_networks() -> List[Dict[str, object]]:
    backend = _wifi_backend()
    if backend == "nmcli":
        return _discover_nmcli_networks()
    if backend == "wpa_cli":
        return _discover_wpa_supplicant_networks()
    return []


def _prompt_import_networks(start_priority: int = 1) -> List[Dict[str, object]]:
    discovered = _discover_system_networks()
    if not discovered:
        print("  No saved networks found on this system — switching to manual entry.")
        return _prompt_manual_networks(start_priority)

    print(f"  Found {len(discovered)} saved network(s):")
    for i, n in enumerate(discovered, start=1):
        pw_note = "password saved" if n.get("found_pw") else "no password found"
        if n.get("hashed"):
            pw_note += ", pre-hashed key (wpa_cli-only)"
        print(f"    {i}) {n['ssid']}  [{pw_note}]")

    choice = input("Import all? [Y/n], or enter numbers (e.g. 1,3): ").strip().lower()
    if choice in ("", "y", "yes"):
        selected = discovered
    elif choice in ("n", "no"):
        return []
    else:
        idxs = []
        for tok in choice.split(","):
            tok = tok.strip()
            if tok.isdigit() and 1 <= int(tok) <= len(discovered):
                idxs.append(int(tok) - 1)
        selected = [discovered[i] for i in idxs]

    networks = []
    for i, n in enumerate(selected, start=start_priority):
        if n.get("hashed"):
            log.info("Imported %s as a pre-hashed key (wpa_cli-only)", n["ssid"])
        networks.append({"ssid": n["ssid"], "psk": n.get("psk", ""), "priority": i})
    return networks


def run_wifi_setup() -> None:
    if os.geteuid() != 0:
        print("ERROR: WiFi setup requires root  →  sudo python3 wifimon.py --setup-wifi",
              file=sys.stderr)
        sys.exit(1)

    existing = load_wifi_networks()
    next_priority = (max((n["priority"] for n in existing), default=0) + 1)

    print("\nWiFi network setup for wifimon:")
    print("  1) Enter a network manually (SSID + password)")
    print("  2) Import known networks already saved on this system")
    print("  3) Skip for now — edit /etc/wifimon/wifimon.conf later")
    choice = input("Choice [1/2/3]: ").strip()

    if choice == "1":
        new_networks = _prompt_manual_networks(next_priority)
    elif choice == "2":
        new_networks = _prompt_import_networks(next_priority)
    else:
        print(f"  Skipped. Edit {CONFIG_FILE} manually, or re-run --setup-wifi later.")
        return

    if not new_networks:
        print("  No networks added.")
        return

    save_wifi_networks(existing + new_networks)

def _has_carrier() -> bool:
    try:
        with open(f"/sys/class/net/{INTERFACE}/carrier", "r") as f:
            return f.read().strip() == "1"
    except OSError:
        return False

def _get_gateway() -> Optional[str]:
    try:
        with open("/proc/net/route", "r") as f:
            for line in f:
                fields = line.strip().split()
                if len(fields) >= 3 and fields[0] == INTERFACE and fields[1] == "00000000":
                    gw_hex = fields[2]
                    if gw_hex != "00000000":
                        gw_ip = socket.inet_ntoa(struct.pack("<I", int(gw_hex, 16)))
                        if gw_ip != "0.0.0.0":
                            return gw_ip
    except (OSError, ValueError, struct.error):
        pass
    return None

_state_lock = threading.Lock()
_wd: Dict[str, object] = {
    "connected": None,
    "internet": None,
    "via": None,
    "ping_ms": None,
    "down_since_mono": None,
    "lowv_since_mono": None,
    "low_v": None,
    "last_good_ssid": None,
    "last_drop_at": None,
    "last_restore_at": None,
    "last_check_at": None,
    "reconnect_attempts": 0,
    "last_reconnect_at": None,
    "last_reconnect_ssid": None,
    "last_reconnect_ok": None,
    "networks_configured": 0,
    "loop_errors": 0,
}


def _wd_update(**changes: object) -> None:
    with _state_lock:
        _wd.update(changes)


def _wd_incr(key: str) -> None:
    with _state_lock:
        _wd[key] = int(_wd.get(key) or 0) + 1


_PING_TIME_RE = re.compile(r"time[=<]\s*([\d.]+)\s*ms")


def _ping_once(host: str) -> Tuple[bool, Optional[float]]:
    try:
        res = subprocess.run(
            ["ping", "-c", "1", "-W", str(PING_TIMEOUT), "-I", INTERFACE, host],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            timeout=PING_TIMEOUT + 2,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, None
    if res.returncode != 0:
        return False, None
    m = _PING_TIME_RE.search(res.stdout or "")
    return True, (float(m.group(1)) if m else None)


def is_connected() -> bool:
    if not _has_carrier():
        _wd_update(internet=False, via=None, ping_ms=None)
        return False

    ok, ms = _ping_once(PING_TARGET)
    if ok:
        _wd_update(internet=True, via="internet", ping_ms=ms)
        return True

    gw = _get_gateway()
    if gw:
        ok, ms = _ping_once(gw)
        if ok:
            _wd_update(internet=False, via="gateway", ping_ms=ms)
            return True

    _wd_update(internet=False, via=None, ping_ms=None)
    return False

_reconnect_lock = threading.Lock()
_reconnecting = False
_last_absent: List[str] = []   # v5.17: log the out-of-range list only when it changes


def _wifi_backend() -> Optional[str]:
    if shutil.which("nmcli"):
        return "nmcli"
    if shutil.which("wpa_cli"):
        return "wpa_cli"
    return None


def _connect_nmcli(ssid: str, psk: str) -> bool:
    try:
        profiles = _profiles_for(ssid)
    except Exception:
        profiles = []
    if profiles:
        ok, msg = _nmcli_ok(["connection", "up", "uuid", str(profiles[0]["uuid"]),
                             "ifname", INTERFACE], timeout=25)
        if not ok:
            log.debug("nmcli connection up for %s failed: %s", ssid, msg)
        return ok
    try:
        if psk:
            cmd = ["nmcli", "device", "wifi", "connect", ssid,
                   "password", psk, "ifname", INTERFACE]
        else:
            cmd = ["nmcli", "device", "wifi", "connect", ssid, "ifname", INTERFACE]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              timeout=20, text=True)
        if res.returncode != 0:
            log.debug("nmcli connect to %s failed: %s", ssid, res.stderr.strip())
        return res.returncode == 0
    except subprocess.TimeoutExpired:
        log.debug("nmcli connect to %s timed out", ssid)
        return False
    except FileNotFoundError as e:
        log.debug("nmcli connect to %s error: %s", ssid, e)
        return False


def _wpa_cli_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _connect_wpa_cli(ssid: str, psk: str) -> bool:
    try:
        out = subprocess.run(["wpa_cli", "-i", INTERFACE, "list_networks"],
                              capture_output=True, text=True, timeout=10)
        net_id = None
        for line in out.stdout.splitlines()[1:]:
            fields = line.split("\t")
            if len(fields) >= 2 and fields[1] == ssid:
                net_id = fields[0]
                break

        if net_id is None:
            add_out = subprocess.run(["wpa_cli", "-i", INTERFACE, "add_network"],
                                      capture_output=True, text=True, timeout=10)
            net_id = add_out.stdout.strip().splitlines()[-1]
            subprocess.run(["wpa_cli", "-i", INTERFACE, "set_network", net_id,
                             "ssid", _wpa_cli_quote(ssid)], capture_output=True, timeout=10)
            if psk:
                subprocess.run(["wpa_cli", "-i", INTERFACE, "set_network", net_id,
                                 "psk", _wpa_cli_quote(psk)], capture_output=True, timeout=10)
            else:
                subprocess.run(["wpa_cli", "-i", INTERFACE, "set_network", net_id,
                                 "key_mgmt", "NONE"], capture_output=True, timeout=10)

        subprocess.run(["wpa_cli", "-i", INTERFACE, "enable_network", net_id],
                        capture_output=True, timeout=10)
        subprocess.run(["wpa_cli", "-i", INTERFACE, "select_network", net_id],
                        capture_output=True, timeout=10)
        subprocess.run(["wpa_cli", "-i", INTERFACE, "save_config"],
                        capture_output=True, timeout=10)
        return True
    except subprocess.TimeoutExpired:
        log.debug("wpa_cli reconnect to %s timed out", ssid)
        return False
    except (FileNotFoundError, IndexError) as e:
        log.debug("wpa_cli reconnect to %s error: %s", ssid, e)
        return False


def _nm_device_state() -> Optional[str]:
    nm = shutil.which("nmcli")
    if not nm:
        return None
    try:
        r = subprocess.run([nm, "-t", "-f", "DEVICE,STATE", "device"], capture_output=True,
                           text=True, timeout=5, env=dict(os.environ, LC_ALL="C"))
    except (subprocess.SubprocessError, OSError):
        return None
    for line in r.stdout.splitlines():
        dev, sep, state = line.partition(":")
        if sep and dev == INTERFACE:
            return state.strip()
    return None


def _nm_busy() -> bool:
    state = _nm_device_state() or ""
    return state.startswith("connecting") or state.startswith("deactivating")


def _hidden_ssids() -> set:
    hidden: set = set()
    try:
        hidden |= {str(n["ssid"]) for n in _conf_networks() if n.get("hidden")}
        hidden |= {str(p["ssid"]) for p in _nm_wifi_profiles() if p.get("hidden")}
    except Exception:
        pass
    return hidden


def _joined_ssid() -> Optional[str]:
    if not _has_carrier():
        return None
    return _current_ssid()


def _attempt_reconnect(networks: List[Dict[str, object]], last_ssid: Optional[str],
                       allow_rejoin: bool = False, interrupt_nm: bool = False) -> None:
    global _reconnecting, _last_absent
    backend = _wifi_backend()
    if backend is None:
        log.warning("Reconnect: neither nmcli nor wpa_cli found — cannot retry")
        _reconnecting = False
        return

    connect_fn = _connect_nmcli if backend == "nmcli" else _connect_wpa_cli

    ordered: List[Dict[str, object]] = []
    if last_ssid:
        for n in networks:
            if n["ssid"] == last_ssid:
                ordered.append(n)
                break
    rank = {"known_good": 0, "failed": 2}
    rest = [n for n in networks if n["ssid"] != last_ssid]
    rest.sort(key=lambda n: rank.get(str(n.get("status")), 1))
    ordered.extend(rest)
    try:
        skip = _autojoin_off_ssids() if backend == "nmcli" else set()
    except Exception:
        skip = set()
    ordered = [n for n in ordered if n["ssid"] not in skip]

    if backend == "nmcli" and ordered and not _shutdown_event.is_set():
        try:
            visible = _visible_ssids()
            hidden = _hidden_ssids()
        except Exception:
            visible, hidden = None, set()
        if visible is not None:
            absent = [str(n["ssid"]) for n in ordered
                      if n["ssid"] not in visible and n["ssid"] not in hidden]
            if absent and absent != _last_absent:
                log.info("Reconnect: not in range, skipped: %s", ", ".join(absent))
            _last_absent = absent
            ordered = [n for n in ordered if n["ssid"] not in absent]

    for n in ordered:
        if _shutdown_event.is_set():
            break
        joined = _joined_ssid()
        if joined and joined == n["ssid"] and not allow_rejoin:
            log.debug("Reconnect: already joined to %s — not rejoining it", n["ssid"])
            continue
        if joined and _ping_once(PING_TARGET)[0]:
            log.info("Reconnect: back online via %s without a retry", joined)
            break
        if backend == "nmcli" and not interrupt_nm and _nm_busy():
            log.info("Reconnect: NetworkManager is already joining a network — leaving it to finish")
            break
        log.info("Reconnect: trying %s (%s)", n["ssid"], backend)
        _wd_incr("reconnect_attempts")
        _wd_update(last_reconnect_at=time.time(), last_reconnect_ssid=n["ssid"],
                   last_reconnect_ok=None)
        if connect_fn(n["ssid"], n["psk"]):
            log.info("Reconnect: %s command succeeded, verifying...", n["ssid"])
            deadline = time.monotonic() + RECONNECT_VERIFY_SECS
            online = False
            while not _shutdown_event.is_set():
                if _shutdown_event.wait(2):
                    break
                if is_connected():
                    online = True
                    break
                if time.monotonic() >= deadline:
                    break
            if online:
                log.info("Reconnect: back online via %s", n["ssid"])
                _wd_update(last_reconnect_ok=True)
                _reconnecting = False
                return
        _wd_update(last_reconnect_ok=False)
        log.debug("Reconnect: %s did not come up", n["ssid"])

    _reconnecting = False


def maybe_reconnect(networks: List[Dict[str, object]], last_ssid: Optional[str],
                    allow_rejoin: bool = False, interrupt_nm: bool = False) -> None:
    global _reconnecting
    if not networks:
        return
    with _reconnect_lock:
        if _reconnecting:
            return
        _reconnecting = True
    threading.Thread(target=_attempt_reconnect, args=(networks, last_ssid, allow_rejoin, interrupt_nm),
                      daemon=True, name="wifi-reconnect").start()


def _current_ssid() -> Optional[str]:
    try:
        r = subprocess.run(["iwgetid", "-r", INTERFACE], capture_output=True,
                            text=True, timeout=5)
        ssid = r.stdout.strip()
        if ssid:
            return ssid
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    try:
        r = subprocess.run(["nmcli", "-t", "-f", "active,ssid", "device", "wifi"],
                            capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if line.startswith("yes:"):
                return line.split(":", 1)[1]
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    return None


def _check_voltage() -> Optional[float]:
    try:
        with open("/sys/class/hwmon/hwmon0/in0_lcrit_alarm", "r") as f:
            if f.read().strip() == "1":
                return 0.80
    except OSError:
        pass

    try:
        r = subprocess.run(["vcgencmd", "measure_volts", "core"], capture_output=True, text=True, timeout=5)
        _, _, val_part = r.stdout.strip().partition("=")
        if val_part:
            volts = float(val_part.rstrip("Vv"))
            if 0.50 <= volts < LOW_VOLTAGE_THRESHOLD:
                return volts
    except (subprocess.SubprocessError, ValueError):
        pass

    return None

def _clear_shutdown_state() -> None:
    try:
        os.remove(SHUTDOWN_STATE_FILE)
    except FileNotFoundError:
        pass
    except OSError as e:
        log.debug("_clear_shutdown_state: %s", e)

def _write_shutdown_state(reason: str, trigger: str) -> None:
    try:
        os.makedirs(SHUTDOWN_STATE_DIR, exist_ok=True)
        payload = {
            "active":  True,
            "reason":  reason,
            "trigger": trigger,
            "since":   time.time(),
        }
        tmp_path = SHUTDOWN_STATE_FILE + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(payload, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, SHUTDOWN_STATE_FILE)
        os.chmod(SHUTDOWN_STATE_FILE, 0o644)
    except OSError as e:
        log.warning("_write_shutdown_state: failed to write state file: %s", e)

def do_shutdown(reason: str, trigger: str) -> None:
    log.critical("Shutting down: %s", reason)
    _write_shutdown_state(reason, trigger)
    _shutdown_report(reason, trigger)
    try:
        subprocess.run(["sync"], timeout=5)
        subprocess.run(["systemctl", "poweroff"], timeout=10)
    except Exception:
        pass
    time.sleep(15)
    subprocess.run(["poweroff", "-f"])


_health_lock = threading.Lock()
_health: Dict[str, object] = {"date": None, "blips": 0, "drops": 0, "chip_stalls": None,
                              "last_stall_at": None, "last_stall_line": None}
_chip_lines: List[Dict[str, object]] = []    # newest 20 chip messages {at, text}
_STALL_RE = re.compile(r"timeout|timed out|err=-110|error -110|halted|crashed|firmware trap", re.I)


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _health_roll_locked() -> None:
    today = _today()
    if _health["date"] != today:
        stalls = 0 if _health["chip_stalls"] is not None else None
        _health.update(date=today, blips=0, drops=0, chip_stalls=stalls,
                       last_stall_at=None, last_stall_line=None)


def _health_save_locked() -> None:
    try:
        os.makedirs(SHUTDOWN_STATE_DIR, exist_ok=True)
        body = json.dumps({"date": _health["date"], "blips": _health["blips"],
                           "drops": _health["drops"]})
        tmp = HEALTH_FILE + ".tmp"
        with open(tmp, "w") as f:
            f.write(body)
        os.replace(tmp, HEALTH_FILE)
    except OSError as e:
        log.debug("Couldn't write %s: %s", HEALTH_FILE, e)


def _health_load() -> None:
    try:
        data = json.loads(_read_text(HEALTH_FILE) or "null")
    except ValueError:
        data = None
    with _health_lock:
        _health_roll_locked()
        if isinstance(data, dict) and data.get("date") == _health["date"]:
            for key in ("blips", "drops"):
                if isinstance(data.get(key), int) and data[key] >= 0:
                    _health[key] = data[key]


def _health_incr(key: str) -> None:
    with _health_lock:
        _health_roll_locked()
        _health[key] = int(_health.get(key) or 0) + 1
        _health_save_locked()


def _health_public(full: bool = False) -> Dict[str, object]:
    with _health_lock:
        _health_roll_locked()
        out = dict(_health)
        if full:
            out["chip_lines"] = [dict(x) for x in _chip_lines]
    return out


_auth_pending_since: Optional[float] = None


def _auth_watch_tick() -> None:
    global _auth_pending_since
    since = _auth_pending_since
    if since is None or time.monotonic() - since < AUTH_WARN_SECS:
        return
    _auth_pending_since = None
    state = _nm_device_state() or ""
    if not state.startswith("connected"):
        log.warning("WiFi still hasn't joined %ds after the password handshake started "
                    "-- the saved password may be wrong or changed", AUTH_WARN_SECS)


def _kmsg_parse(raw: bytes) -> Optional[Tuple[float, str]]:
    try:
        head, _, msg = raw.decode("utf-8", "replace").partition(";")
        ts_us = int(head.split(",")[2])
    except (ValueError, IndexError):
        return None
    return ts_us / 1e6, msg.split("\n", 1)[0].strip()


def _kmsg_loop() -> None:
    try:
        fd = os.open("/dev/kmsg", os.O_RDONLY | os.O_NONBLOCK)
    except OSError as e:
        log.info("WiFi chip stall counting is off (can't read the kernel log: %s)", e)
        return
    try:
        up = float((_read_text("/proc/uptime") or "0").split()[0])
    except ValueError:
        up = 0.0
    boot_wall = time.time() - up
    midnight = time.mktime(time.strptime(_today(), "%Y-%m-%d"))
    last_ts = -1e9
    backlog = True
    backlog_count = 0
    warned_at, unlogged = -1e9, 0
    with _health_lock:
        _health_roll_locked()
        _health["chip_stalls"] = int(_health["chip_stalls"] or 0)
    try:
        while not _shutdown_event.is_set():
            try:
                raw = os.read(fd, 8192)
            except BlockingIOError:
                if backlog:
                    backlog = False
                    if backlog_count:
                        log.info("Kernel log shows %d WiFi chip stall(s) earlier today", backlog_count)
                select.select([fd], [], [], 1.0)
                continue
            except BrokenPipeError:
                continue
            except OSError as e:
                log.warning("Kernel log reader stopped: %s", e)
                return
            parsed = _kmsg_parse(raw)
            if not parsed:
                continue
            ts, text = parsed
            if "brcmf" in text and ("for chip " in text or "Firmware: " in text):
                _pi_chip_boot_lines[("fw" if "Firmware: " in text else "chip")] = text[:300]
            if "brcmf" not in text or not _STALL_RE.search(text):
                continue
            at = boot_wall + ts
            if backlog and at < midnight:
                last_ts = ts
                continue
            new_stall = ts - last_ts > 2.0
            last_ts = ts
            with _health_lock:
                _health_roll_locked()
                _chip_lines.append({"at": at, "text": text[:300]})
                del _chip_lines[:-20]
                if new_stall:
                    _health["chip_stalls"] = int(_health["chip_stalls"] or 0) + 1
                    _health["last_stall_at"] = at
                    _health["last_stall_line"] = text[:300]
            if not new_stall:
                continue
            if backlog:
                backlog_count += 1
                continue
            now = time.monotonic()
            if now - warned_at >= 60:
                more = f" ({unlogged} more since the last note)" if unlogged else ""
                log.warning("WiFi chip stall: %s%s", text[:200], more)
                warned_at, unlogged = now, 0
            else:
                unlogged += 1
    finally:
        os.close(fd)


_pi_chip_boot_lines: Dict[str, str] = {}
_pi_chip_cache: Optional[Dict[str, object]] = None
_ap_chip_cache: Dict[str, object] = {"bssid": None, "info": None, "tried": -1e9}
_SDIO_CHIPS = {"0xa9a6": "BCM43430/BCM43436", "0x4345": "BCM43455"}
_CHIP_OUIS = {
    "00:10:18": "Broadcom", "00:90:4c": "Broadcom",
    "00:03:7f": "Qualcomm Atheros", "00:13:74": "Qualcomm Atheros",
    "8c:fd:f0": "Qualcomm", "00:0a:f5": "Qualcomm",
    "00:0c:e7": "MediaTek", "00:0c:43": "MediaTek (Ralink)",
    "00:e0:4c": "Realtek", "00:50:43": "Marvell", "00:26:86": "Quantenna",
}
_OUI_FILES = ("/usr/share/ieee-data/oui.txt", "/var/lib/ieee-data/oui.txt",
              "/usr/share/misc/oui.txt", "/usr/share/nmap/nmap-mac-prefixes")


def _drvinfo() -> Dict[str, str]:
    buf = array.array("B", struct.pack("I", 0x00000003) + bytes(192))
    addr, _n = buf.buffer_info()
    ifr = struct.pack("16sP", INTERFACE.encode()[:15], addr)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            fcntl.ioctl(sock.fileno(), 0x8946, ifr)
    except OSError:
        return {}
    raw = buf.tobytes()
    field = lambda a: raw[a:a + 32].split(b"\0", 1)[0].decode("utf-8", "replace").strip()
    return {"driver": field(4), "version": field(36), "firmware": field(68), "bus": field(100)}


def _chip_from_line(text: str) -> Optional[str]:
    m = re.search(r"for chip (\S+)", text) or re.search(r"Firmware: (\S+)", text)
    return m.group(1) if m else None


def _pi_chip_info() -> Dict[str, object]:
    global _pi_chip_cache
    if _pi_chip_cache is not None and _pi_chip_cache.get("chip"):
        return _pi_chip_cache
    dev = f"/sys/class/net/{INTERFACE}/device"
    info: Dict[str, object] = {"chip": None, "maker": None, "source": None}
    d = _drvinfo()
    info.update(driver=d.get("driver") or _roam_state().get("driver"),
                firmware=d.get("firmware") or None, bus=d.get("bus") or None)
    lines = dict(_pi_chip_boot_lines)
    if not lines and shutil.which("journalctl") and _pi_chip_cache is None:
        txt = _run_text(["journalctl", "-k", "-b", "-o", "cat", "--no-pager"], timeout=15)
        for line in txt.splitlines():
            if "brcmf" in line and ("for chip " in line or "Firmware: " in line):
                lines["fw" if "Firmware: " in line else "chip"] = line.strip()[:300]
    chip = _chip_from_line(lines.get("chip", "")) or _chip_from_line(lines.get("fw", ""))
    if chip:
        info.update(chip=chip, maker="Broadcom/Cypress/Infineon", source="kernel boot log")
        if not info["firmware"] and lines.get("fw"):
            m = re.search(r"version (\S+)", lines["fw"])
            info["firmware"] = m.group(1) if m else None
    else:
        vendor = (_read_text(dev + "/vendor") or "").strip().lower()
        device = (_read_text(dev + "/device") or "").strip().lower()
        if vendor == "0x02d0" and device:
            info.update(chip=_SDIO_CHIPS.get(device, f"Broadcom SDIO chip {device}"),
                        maker="Broadcom/Cypress/Infineon", source="chip ID")
        else:
            usb = os.path.realpath(dev + "/..")
            maker = (_read_text(usb + "/manufacturer") or "").strip()
            product = (_read_text(usb + "/product") or "").strip()
            ids = [(_read_text(usb + f) or "").strip() for f in ("/idVendor", "/idProduct")]
            if product or maker:
                info.update(chip=product or None, maker=maker or None, source="USB adapter")
            if all(ids):
                info["usb_id"] = f"{ids[0]}:{ids[1]}"
    _pi_chip_cache = info
    return info


def _oui_vendor(mac: str) -> Optional[str]:
    hexes = re.sub(r"[^0-9A-Fa-f]", "", mac or "").upper()
    if len(hexes) < 6:
        return None
    dashed, plain = "-".join(hexes[i:i + 2] for i in (0, 2, 4)), hexes[:6]
    for path in _OUI_FILES:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith(dashed) and "(hex)" in line:
                        return line.split("(hex)", 1)[1].strip() or None
                    if line.startswith(plain + " ") or line.startswith(plain + "\t"):
                        return line[6:].strip() or None
        except OSError:
            continue
    return None


def _parse_scan_dump(txt: str, bssid: Optional[str]) -> Optional[Dict[str, object]]:
    blocks = re.split(r"(?m)^BSS ", txt)
    pick = None
    for b in blocks[1:]:
        head = b.split("\n", 1)[0].lower()
        if "-- associated" in head or (bssid and head.startswith(bssid.lower())):
            pick = b
            if "-- associated" in head:
                break
    if pick is None:
        return None
    mac = pick[:17].lower()
    wps: Dict[str, str] = {}
    for key, name in (("Manufacturer", "maker"), ("Model", "model"), ("Model Number", "model_number"),
                      ("Device name", "device_name")):
        m = re.search(r"\*\s*" + key + r":\s*(.+)", pick)
        if m and m.group(1).strip():
            wps[name] = m.group(1).strip()[:80]
    ouis = [o.lower() for o in re.findall(r"Vendor specific: OUI ([0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2})", pick, re.I)]
    chips: List[str] = []
    for o in ouis:
        name = _CHIP_OUIS.get(o)
        if name and name not in chips:
            chips.append(name)
    local = bool(int(mac[:2], 16) & 2) if re.match(r"[0-9a-f]{2}:", mac) else False
    return {"bssid": mac, "wps": wps, "chip_guess": chips, "local_mac": local,
            "mac_vendor": None if local else _oui_vendor(mac)}


def _ap_chip_info(bssid: Optional[str]) -> Optional[Dict[str, object]]:
    c = _ap_chip_cache
    now = time.monotonic()
    if c["info"] is not None and (bssid is None or c["bssid"] == bssid):
        return c["info"]
    if c["bssid"] == bssid and now - float(c["tried"]) < 60:
        return None
    c.update(bssid=bssid, tried=now, info=None)
    if not shutil.which("iw"):
        return None
    info = _parse_scan_dump(_run_text(["iw", "dev", INTERFACE, "scan", "dump"], timeout=8), bssid)
    if info is not None:
        c.update(bssid=bssid or info["bssid"], info=info)
    return info


def _roam_state() -> Dict[str, object]:
    try:
        driver = os.path.basename(os.readlink(f"/sys/class/net/{INTERFACE}/device/driver"))
    except OSError:
        driver = None
    live_txt = (_read_text("/sys/module/brcmfmac/parameters/roamoff") or "").strip()
    live = None if not live_txt else live_txt in ("1", "Y", "y")
    ours = (_read_text(ROAM_MODPROBE) or "").startswith("# Written by wifimon")
    return {"driver": driver, "roam_off_now": live, "roam_off_next_boot": ours}


def _watchdog_loop() -> None:
    wifi_networks = load_wifi_networks()
    if wifi_networks:
        log.info("Loaded %d known WiFi network(s) from %s for aggressive reconnect",
                  len(wifi_networks), CONFIG_FILE)
    else:
        log.info("No WiFi networks configured in %s — reconnect feature is idle", CONFIG_FILE)
    _wd_update(networks_configured=len(wifi_networks))

    down_since: Optional[float] = None
    low_voltage_since: Optional[float] = None
    last_good_ssid: Optional[str] = None
    last_reconnect_attempt: Optional[float] = None
    last_tagged: Optional[str] = None
    misses = 0
    first_miss_at: Optional[float] = None
    head_start_noted = False
    nm_busy_since: Optional[float] = None
    nm_step_in_noted = False

    while not _shutdown_event.is_set():
        loop_start = time.monotonic()

        try:
            if _networks_changed.is_set():
                _networks_changed.clear()
                wifi_networks = load_wifi_networks()
                _wd_update(networks_configured=len(wifi_networks))
                log.info("Reloaded %d known WiFi network(s)", len(wifi_networks))
                last_tagged = None

            if _timers_reset.is_set():
                _timers_reset.clear()
                if down_since is not None:
                    down_since = loop_start
                    _wd_update(down_since_mono=loop_start)
                if low_voltage_since is not None:
                    low_voltage_since = loop_start
                    _wd_update(lowv_since_mono=loop_start)
                log.info("Watchdog settings changed — running countdowns restarted")

            low_v = _check_voltage()
            if low_v is not None:
                if low_voltage_since is None:
                    low_voltage_since = loop_start
                    log.warning("Low voltage: %.4fV — starting timer", low_v)
                    _wd_update(lowv_since_mono=loop_start, low_v=low_v)
                elif (loop_start - low_voltage_since) >= LOW_VOLTAGE_SHUTDOWN_SECS:
                    _recorder_final("low_voltage")
                    do_shutdown(f"Low voltage ({low_v:.4f}V) sustained for {LOW_VOLTAGE_SHUTDOWN_SECS}s",
                                trigger="low_voltage")
                    break
                else:
                    _wd_update(low_v=low_v)
            else:
                if low_voltage_since is not None:
                    log.info("Voltage restored to normal")
                    low_voltage_since = None
                    _wd_update(lowv_since_mono=None, low_v=None)

            connected = is_connected()
            _wd_update(connected=connected, last_check_at=time.time())
            if connected:
                if misses and down_since is None:
                    log.info("Brief blip: %d missed check(s), back without a drop", misses)
                    _health_incr("blips")
                misses, first_miss_at = 0, None
                head_start_noted, nm_busy_since, nm_step_in_noted = False, None, False
                if down_since is not None:
                    _ps_check.set()
                    log.info("Network restored")
                    down_since = None
                    last_reconnect_attempt = None
                    _wd_update(down_since_mono=None, last_restore_at=time.time())
                ssid_now = _current_ssid()
                if ssid_now:
                    last_good_ssid = ssid_now
                    _wd_update(last_good_ssid=ssid_now)
                    if ssid_now != last_tagged:
                        last_tagged = ssid_now
                        _set_network_status(ssid_now, "known_good")
                if _ps_check.is_set():
                    _ps_check.clear()
                    _keep_powersave_check()
            elif _grace_remaining() > 0 or _hotspot_active():
                misses, first_miss_at = 0, None
                head_start_noted, nm_busy_since, nm_step_in_noted = False, None, False
                if down_since is not None:
                    log.info("Shutdown timer paused — dashboard change in progress")
                    down_since = None
                    last_reconnect_attempt = None
                    _wd_update(down_since_mono=None)
            else:
                link_up = _has_carrier()
                if first_miss_at is None:
                    first_miss_at = loop_start
                misses += 1
                if down_since is None and link_up and misses < MISSES_BEFORE_LOST:
                    log.debug("Connection check missed (%d of %d) — WiFi link still up, waiting",
                              misses, MISSES_BEFORE_LOST)
                else:
                    if down_since is None:
                        down_since = first_miss_at
                        log.warning("Network lost — starting shutdown timer")
                        _health_incr("drops")
                        _wd_update(down_since_mono=down_since, last_drop_at=time.time())
                    if (loop_start - down_since) >= NO_CONN_SHUTDOWN_SECS:
                        _recorder_final("no_conn")
                        do_shutdown(f"No network connection for {NO_CONN_SHUTDOWN_SECS}s",
                                    trigger="no_conn")
                        break

                    stuck = link_up and (loop_start - down_since) >= STUCK_LINK_SECS
                    waiting = False
                    if wifi_networks and not link_up:
                        if (loop_start - down_since) < NM_HEAD_START_SECS:
                            waiting = True
                            if not head_start_noted:
                                head_start_noted = True
                                log.info("Waiting up to %ds for the WiFi to rejoin by itself",
                                         NM_HEAD_START_SECS)
                    step_in = False
                    if wifi_networks and (not link_up or stuck) and not waiting:
                        if _nm_busy():
                            if nm_busy_since is None:
                                nm_busy_since = loop_start
                            if (loop_start - nm_busy_since) < NM_BUSY_MAX_SECS:
                                waiting = True
                            else:
                                step_in = True
                                if not nm_step_in_noted:
                                    nm_step_in_noted = True
                                    log.warning("NetworkManager has been joining for %ds — wifimon is stepping in",
                                                NM_BUSY_MAX_SECS)
                        else:
                            nm_busy_since = None
                    if wifi_networks and (not link_up or stuck) and not waiting and (
                        last_reconnect_attempt is None
                        or (loop_start - last_reconnect_attempt) >= RECONNECT_INTERVAL_SECS
                    ):
                        last_reconnect_attempt = loop_start
                        maybe_reconnect(wifi_networks, last_good_ssid, allow_rejoin=stuck,
                                        interrupt_nm=step_in)

            _auth_watch_tick()
            _recorder_tick(down_since, low_voltage_since, time.monotonic())
        except Exception:
            log.exception("Watchdog pass failed — continuing with the next pass")
            _wd_incr("loop_errors")

        elapsed = time.monotonic() - loop_start
        if _shutdown_event.wait(timeout=max(0.1, CHECK_INTERVAL - elapsed)):
            break


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _read_sys(name: str) -> Optional[str]:
    txt = _read_text(f"/sys/class/net/{INTERFACE}/{name}")
    return txt.strip() if txt is not None else None


def _run_text(cmd: List[str], timeout: float = 5) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.SubprocessError, OSError):
        return ""
    return r.stdout if r.returncode == 0 else ""


def _to_int(s: Optional[str]) -> Optional[int]:
    try:
        return int(str(s).strip())
    except (TypeError, ValueError):
        return None


def _first_num(s: Optional[str]) -> Optional[float]:
    m = _NUM_RE.search(s or "")
    return float(m.group(0)) if m else None


def _first_int(s: Optional[str]) -> Optional[int]:
    v = _first_num(s)
    return int(v) if v is not None else None


def _parse_proc_wireless(text: str, iface: str) -> Dict[str, object]:
    for line in text.splitlines():
        head, sep, rest = line.strip().partition(":")
        if not sep or head.strip() != iface:
            continue
        parts = rest.split()
        if len(parts) < 4:
            return {}

        def num(tok: str) -> Optional[float]:
            try:
                return float(tok.rstrip("."))
            except ValueError:
                return None

        link, level, noise = num(parts[1]), num(parts[2]), num(parts[3])
        if level is not None and level > 0:
            level -= 256
        if noise is not None and noise > 0:
            noise -= 256
        if noise is not None and (noise <= -256 or noise == 0):
            noise = None
        return {"link_quality": link, "proc_signal_dbm": level, "noise_dbm": noise}
    return {}


def _parse_iw_link(text: str) -> Dict[str, object]:
    if not text.strip():
        return {}
    if text.strip().startswith("Not connected"):
        return {"linked": False}
    out: Dict[str, object] = {"linked": True}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Connected to "):
            fields = line.split()
            if len(fields) >= 3:
                out["bssid"] = fields[2].lower()
        elif line.startswith("SSID:"):
            out["ssid_iw"] = line[5:].strip() or None
        elif line.startswith("freq:"):
            out["freq_mhz"] = _first_int(line[5:])
        elif line.startswith("signal:"):
            out["signal_dbm"] = _first_num(line[7:])
        elif line.startswith("rx bitrate:"):
            out["rx_bitrate"] = _first_num(line[11:])
        elif line.startswith("tx bitrate:"):
            out["tx_bitrate"] = _first_num(line[11:])
    return out


def _parse_station_dump(text: str) -> Dict[str, object]:
    out: Dict[str, object] = {}
    stations = 0
    for raw in text.splitlines():
        if raw.startswith("Station "):
            stations += 1
            if stations > 1:
                break
            continue
        key, sep, value = raw.strip().partition(":")
        if not sep:
            continue
        key = key.strip()
        if key == "connected time":
            out["connected_secs"] = _first_int(value)
        elif key == "tx retries":
            out["tx_retries"] = _first_int(value)
        elif key == "tx failed":
            out["tx_failed"] = _first_int(value)
        elif key == "beacon loss":
            out["beacon_loss"] = _first_int(value)
    return out


def _freq_band_channel(freq: Optional[int]) -> Tuple[Optional[str], Optional[int]]:
    if not freq:
        return None, None
    if 2400 <= freq <= 2500:
        return "2.4 GHz", (14 if freq == 2484 else (freq - 2407) // 5)
    if 4900 <= freq < 5925:
        return "5 GHz", (freq - 5000) // 5
    if 5925 <= freq <= 7125:
        return "6 GHz", (freq - 5950) // 5
    return None, None


def _nmcli_split(line: str) -> List[str]:
    fields: List[str] = []
    cur: List[str] = []
    i = 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
            continue
        if c == ":":
            fields.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    fields.append("".join(cur))
    return fields


def _nm_scan_lines() -> List[List[str]]:
    txt = _run_text(["nmcli", "-t", "-f", "IN-USE,SSID,BSSID,CHAN,FREQ,SIGNAL,SECURITY",
                     "device", "wifi", "list", "ifname", INTERFACE, "--rescan", "no"],
                    timeout=8)
    return [f for f in (_nmcli_split(line) for line in txt.splitlines()) if len(f) >= 7]


def _nmcli_active_ap(lines: Optional[List[List[str]]] = None) -> Dict[str, object]:
    for f in (lines if lines is not None else _nm_scan_lines()):
        if f[0].strip() == "*":
            sec = f[6].strip()
            return {
                "nm_ssid": f[1] or None,
                "nm_bssid": f[2].strip().lower() or None,
                "nm_channel": _first_int(f[3]),
                "nm_freq_mhz": _first_int(f[4]),
                "signal_pct": _first_int(f[5]),
                "security": sec if sec and sec != "--" else "Open",
            }
    return {}


def _nmcli_device_info() -> Tuple[Optional[str], List[str]]:
    txt = _run_text(["nmcli", "-t", "-f", "GENERAL.CONNECTION,IP4.DNS",
                     "device", "show", INTERFACE])
    profile: Optional[str] = None
    dns: List[str] = []
    for line in txt.splitlines():
        parts = _nmcli_split(line)
        key, value = parts[0], ":".join(parts[1:]).strip()
        if key == "GENERAL.CONNECTION":
            profile = value if value and value != "--" else None
        elif key.startswith("IP4.DNS") and value:
            dns.append(value)
    return profile, dns


def _nmcli_radio() -> Optional[bool]:
    state = _run_text(["nmcli", "radio", "wifi"]).strip().lower()
    if state == "enabled":
        return True
    if state == "disabled":
        return False
    return None


def _ip4_address() -> Dict[str, object]:
    txt = _run_text(["ip", "-4", "-o", "addr", "show", "dev", INTERFACE])
    m = re.search(r"\binet\s+([\d.]+)/(\d+)", txt)
    if not m:
        return {"ip4": None, "ip4_prefix": None}
    return {"ip4": m.group(1), "ip4_prefix": int(m.group(2))}


def _resolv_dns() -> List[str]:
    txt = _read_text("/etc/resolv.conf") or ""
    out = []
    for line in txt.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == "nameserver":
            out.append(fields[1])
    return out


def _rfkill_wlan() -> Tuple[Optional[bool], Optional[bool]]:
    base = "/sys/class/rfkill"
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return None, None
    soft: Optional[bool] = None
    hard: Optional[bool] = None
    for name in names:
        kind = _read_text(os.path.join(base, name, "type"))
        if not kind or kind.strip() != "wlan":
            continue
        s = _read_text(os.path.join(base, name, "soft"))
        h = _read_text(os.path.join(base, name, "hard"))
        soft = bool(soft) or (s is not None and s.strip() == "1")
        hard = bool(hard) or (h is not None and h.strip() == "1")
    return soft, hard


def _reg_country() -> Optional[str]:
    m = re.search(r"^country\s+([A-Z0-9]{2}):", _run_text(["iw", "reg", "get"]), re.M)
    return m.group(1) if m else None


def _power_save() -> Optional[bool]:
    m = re.search(r"Power save:\s*(on|off)",
                  _run_text(["iw", "dev", INTERFACE, "get", "power_save"]), re.I)
    return (m.group(1).lower() == "on") if m else None


def _wifi_devices() -> List[Dict[str, object]]:
    if shutil.which("nmcli"):
        out: List[Dict[str, object]] = []
        txt = _run_text(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"])
        for line in txt.splitlines():
            f = _nmcli_split(line)
            if len(f) >= 4 and f[1] == "wifi":
                conn = f[3].strip()
                out.append({"device": f[0], "state": f[2],
                            "connection": conn if conn and conn != "--" else None,
                            "hw": _adapter_key(f[0])})
        return out
    out = []
    try:
        names = sorted(os.listdir("/sys/class/net"))
    except OSError:
        return out
    for name in names:
        if os.path.isdir(f"/sys/class/net/{name}/wireless"):
            state = (_read_text(f"/sys/class/net/{name}/operstate") or "").strip() or None
            out.append({"device": name, "state": state, "connection": None,
                        "hw": _adapter_key(name)})
    return out


def _ipv4_map() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in _run_text(["ip", "-4", "-o", "addr", "show"]).splitlines():
        m = re.search(r"^\d+:\s+(\S+?)(?:@\S+)?\s+inet\s+([\d.]+)/", line)
        if m:
            out[m.group(2)] = m.group(1)
    return out


def _read_power() -> Dict[str, object]:
    out: Dict[str, object] = {
        "volts": None, "lcrit_alarm": None, "throttled_raw": None,
        "undervoltage_now": None, "undervoltage_seen": None,
        "throttled_now": None, "freq_capped_now": None,
    }
    alarm = _read_text("/sys/class/hwmon/hwmon0/in0_lcrit_alarm")
    if alarm is not None:
        out["lcrit_alarm"] = alarm.strip() == "1"
    if shutil.which("vcgencmd"):
        m = re.search(r"=\s*([\d.]+)", _run_text(["vcgencmd", "measure_volts", "core"]))
        if m:
            out["volts"] = float(m.group(1))
        m = re.search(r"throttled=(0x[0-9a-fA-F]+)", _run_text(["vcgencmd", "get_throttled"]))
        if m:
            bits = int(m.group(1), 16)
            out.update(
                throttled_raw=m.group(1),
                undervoltage_now=bool(bits & 0x1),
                freq_capped_now=bool(bits & 0x2),
                throttled_now=bool(bits & 0x4),
                undervoltage_seen=bool(bits & 0x10000),
            )
    return out


_slow_refresh = threading.Event()
_status_lock = threading.Lock()
_status: Dict[str, object] = {"fast": {}, "slow": {}, "fast_at": None, "slow_at": None}
_counters_prev: Optional[Tuple[float, int, int]] = None


def _collect_fast() -> Dict[str, object]:
    global _counters_prev
    out: Dict[str, object] = {
        "iface": INTERFACE,
        "mac": _read_sys("address"),
        "operstate": _read_sys("operstate"),
    }
    out.update(_parse_proc_wireless(_read_text("/proc/net/wireless") or "", INTERFACE))
    out.update(_parse_iw_link(_run_text(["iw", "dev", INTERFACE, "link"])))
    out.update(_parse_station_dump(_run_text(["iw", "dev", INTERFACE, "station", "dump"])))

    rx = _to_int(_read_sys("statistics/rx_bytes"))
    tx = _to_int(_read_sys("statistics/tx_bytes"))
    out.update(rx_bytes=rx, tx_bytes=tx, rx_rate=None, tx_rate=None)
    if rx is not None and tx is not None:
        now = time.monotonic()
        prev = _counters_prev
        if prev is not None:
            dt = now - prev[0]
            if dt > 0 and rx >= prev[1] and tx >= prev[2]:
                out["rx_rate"] = (rx - prev[1]) / dt
                out["tx_rate"] = (tx - prev[2]) / dt
        _counters_prev = (now, rx, tx)

    out["power"] = _read_power()
    return out


def _collect_slow() -> Dict[str, object]:
    out: Dict[str, object] = {"backend": _wifi_backend()}
    out.update(_ip4_address())
    out["gateway"] = _get_gateway()
    if shutil.which("nmcli"):
        lines = _nm_scan_lines()
        out.update(_nmcli_active_ap(lines))
        out["scan"] = _scan_from_lines(lines)
        out["profiles"] = _nm_wifi_profiles()
        profile, dns = _nmcli_device_info()
        out["profile"] = profile
        out["dns"] = dns or _resolv_dns()
        out["radio"] = _nmcli_radio()
    else:
        out["ssid_fallback"] = _current_ssid()
        out["dns"] = _resolv_dns()
        out["radio"] = None
    soft, hard = _rfkill_wlan()
    out["rfkill_soft"], out["rfkill_hard"] = soft, hard
    if out["radio"] is None and soft is not None:
        out["radio"] = not (soft or hard)
    out["country"] = _reg_country()
    out["power_save"] = _power_save()
    out["roam"] = _roam_state()
    try:
        out["chips"] = {"pi": _pi_chip_info(),
                        "ap": _ap_chip_info(out.get("nm_bssid")) if out.get("radio") is not False else None}
    except Exception:
        log.debug("chip info failed", exc_info=True)
        out["chips"] = None
    if KEEP_POWERSAVE_OFF and out["power_save"] is True:
        _ps_check.set()
    out["has_5ghz"] = _has_5ghz()
    out["connectivity"] = (_run_text(["nmcli", "networking", "connectivity"]).strip() or None
                           if shutil.which("nmcli") else None)
    out["devices"] = _wifi_devices()
    out["ipmap"] = _ipv4_map()
    return out


def _collector_loop() -> None:
    next_slow = 0.0
    while not _shutdown_event.is_set():
        t0 = time.monotonic()
        try:
            fast = _collect_fast()
            with _status_lock:
                _status["fast"] = fast
                _status["fast_at"] = time.time()
            if t0 >= next_slow or _slow_refresh.is_set():
                _slow_refresh.clear()
                slow = _collect_slow()
                with _status_lock:
                    _status["slow"] = slow
                    _status["slow_at"] = time.time()
                next_slow = t0 + STATUS_SLOW_SECS
        except Exception:
            log.exception("Status collector pass failed — continuing")
        deadline = t0 + STATUS_FAST_SECS
        while not _slow_refresh.is_set() and time.monotonic() < deadline:
            if _shutdown_event.wait(0.5):
                return


def _read_shutdown_state() -> Optional[Dict[str, object]]:
    txt = _read_text(SHUTDOWN_STATE_FILE)
    if not txt:
        return None
    try:
        data = json.loads(txt)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


_started_wall = time.time()
_started_mono = time.monotonic()
_service_info: Dict[str, object] = {"tls": False, "root_pw": "unknown"}


def _build_status() -> Dict[str, object]:
    with _status_lock:
        fast = dict(_status["fast"])
        slow = dict(_status["slow"])
        fast_at, slow_at = _status["fast_at"], _status["slow_at"]
    with _state_lock:
        wd = dict(_wd)
    now_m = time.monotonic()
    now = time.time()

    linked = fast.get("linked")
    bssid = fast.get("bssid") or slow.get("nm_bssid")
    nm_ssid, nm_bssid = slow.get("nm_ssid"), slow.get("nm_bssid")
    if nm_ssid and (not fast.get("bssid") or not nm_bssid or nm_bssid == fast.get("bssid")):
        ssid = nm_ssid
    else:
        ssid = fast.get("ssid_iw") or slow.get("ssid_fallback")
    freq = fast.get("freq_mhz") or slow.get("nm_freq_mhz")
    band, channel = _freq_band_channel(freq)
    if channel is None:
        channel = slow.get("nm_channel")
    signal_dbm = fast.get("signal_dbm")
    if signal_dbm is None:
        signal_dbm = fast.get("proc_signal_dbm")

    wifi: Dict[str, object] = {
        "iface": fast.get("iface", INTERFACE),
        "mac": fast.get("mac"),
        "operstate": fast.get("operstate"),
        "backend": slow.get("backend"),
        "ssid": ssid,
        "profile": slow.get("profile"),
        "bssid": bssid,
        "freq_mhz": freq,
        "band": band,
        "channel": channel,
        "security": slow.get("security"),
        "connected_secs": fast.get("connected_secs"),
        "signal_dbm": signal_dbm,
        "signal_pct": slow.get("signal_pct"),
        "link_quality": fast.get("link_quality"),
        "noise_dbm": fast.get("noise_dbm"),
        "rx_bitrate": fast.get("rx_bitrate"),
        "tx_bitrate": fast.get("tx_bitrate"),
        "tx_retries": fast.get("tx_retries"),
        "tx_failed": fast.get("tx_failed"),
        "beacon_loss": fast.get("beacon_loss"),
        "ip4": slow.get("ip4"),
        "ip4_prefix": slow.get("ip4_prefix"),
        "gateway": slow.get("gateway"),
        "dns": slow.get("dns") or [],
        "rx_bytes": fast.get("rx_bytes"),
        "tx_bytes": fast.get("tx_bytes"),
        "rx_rate": fast.get("rx_rate"),
        "tx_rate": fast.get("tx_rate"),
        "radio": slow.get("radio"),
        "rfkill_soft": slow.get("rfkill_soft"),
        "rfkill_hard": slow.get("rfkill_hard"),
        "country": slow.get("country"),
        "power_save": slow.get("power_save"),
        "has_5ghz": slow.get("has_5ghz"),
        "chips": slow.get("chips"),
        "linked": linked,
    }
    if linked is False:
        for key in ("ssid", "profile", "bssid", "freq_mhz", "band", "channel", "security",
                    "connected_secs", "signal_dbm", "signal_pct", "link_quality",
                    "noise_dbm", "rx_bitrate", "tx_bitrate", "tx_retries", "tx_failed",
                    "beacon_loss"):
            wifi[key] = None

    def remaining(since: object, total: float) -> Optional[float]:
        if since is None:
            return None
        return max(0.0, total - (now_m - float(since)))

    watchdog = {
        "connected": wd["connected"],
        "no_conn_remaining": remaining(wd["down_since_mono"], NO_CONN_SHUTDOWN_SECS),
        "no_conn_total": NO_CONN_SHUTDOWN_SECS,
        "lowv_remaining": remaining(wd["lowv_since_mono"], LOW_VOLTAGE_SHUTDOWN_SECS),
        "lowv_total": LOW_VOLTAGE_SHUTDOWN_SECS,
        "low_v": wd["low_v"],
        "low_v_threshold": LOW_VOLTAGE_THRESHOLD,
        "last_good_ssid": wd["last_good_ssid"],
        "last_drop_at": wd["last_drop_at"],
        "last_restore_at": wd["last_restore_at"],
        "last_check_at": wd["last_check_at"],
        "reconnect_attempts": wd["reconnect_attempts"],
        "reconnecting": bool(_reconnecting),
        "last_reconnect_at": wd["last_reconnect_at"],
        "last_reconnect_ssid": wd["last_reconnect_ssid"],
        "last_reconnect_ok": wd["last_reconnect_ok"],
        "networks_configured": wd["networks_configured"],
        "check_interval": CHECK_INTERVAL,
        "settings": _settings_public(),
        "reconnect_interval": RECONNECT_INTERVAL_SECS,
        "loop_errors": wd["loop_errors"],
        "interface": INTERFACE,
        "recording": _recording_public(),
    }
    net = {
        "internet": wd["internet"],
        "via": wd["via"],
        "ping_ms": wd["ping_ms"],
        "ping_target": PING_TARGET,
        "connectivity": slow.get("connectivity") if DETECT_LOGIN_PAGES else None,
        "login_detect": bool(DETECT_LOGIN_PAGES),
    }
    service = {
        "version": APP_VERSION,
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "started_at": _started_wall,
        "uptime_secs": now_m - _started_mono,
        "tls": bool(_service_info.get("tls")),
        "tls_wanted": bool(USE_TLS),
        "port": HTTP_PORT,
        "is_root": os.geteuid() == 0,
        "systemd": bool(os.environ.get("INVOCATION_ID")),
        "root_pw": _service_info.get("root_pw"),
    }
    devices, absent = _devices_public(slow.get("devices") or [])
    return {
        "now": now,
        "fast_at": fast_at,
        "slow_at": slow_at,
        "wifi": wifi,
        "net": net,
        "watchdog": watchdog,
        "power": fast.get("power") or {},
        "shutdown": _read_shutdown_state(),
        "health": dict(_health_public(), roam=slow.get("roam") or {}),
        "service": service,
        "devices": devices,
        "adapters_absent": absent,
        "control": _control_public(),
        "saved": _saved_public(slow, wifi["ssid"]),
        "scan": {"networks": slow.get("scan") or [], "at": slow_at},
        "job": _job_public(),
        "log_seq": _activity_since(1 << 62)["seq"],
        "reports_stamp": _reports_stamp(),
        "hotspot": _hotspot_public(),
        "last_report": _last_report_banner(),
    }


_KEEP_MIN_SECS = 5
_IFACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,14}$")
_action_lock = threading.Lock()
_change_lock = threading.Lock()
_grace_until: Optional[float] = None
_pending: Optional[Dict[str, object]] = None
_last_result: Optional[Dict[str, object]] = None


def _grace_start(reason: str) -> None:
    global _grace_until
    until = time.monotonic() + CHANGE_GRACE_SECS
    with _change_lock:
        if _grace_until is None or until > _grace_until:
            _grace_until = until
    log.info("Shutdown timer paused for %d s: %s", CHANGE_GRACE_SECS, reason)


def _grace_remaining() -> float:
    with _change_lock:
        until = _grace_until
    return 0.0 if until is None else max(0.0, until - time.monotonic())


def _nmcli_ok(args: List[str], timeout: float = 30) -> Tuple[bool, str]:
    nm = shutil.which("nmcli")
    if not nm:
        return False, "nmcli not found"
    try:
        r = subprocess.run([nm] + args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"nmcli timed out after {int(timeout)} s"
    except (subprocess.SubprocessError, OSError) as e:
        return False, _log_safe(e)
    msg = (r.stderr or r.stdout or "").strip()
    return r.returncode == 0, _log_safe(msg[:300])


def _save_state(data: Dict[str, object]) -> None:
    merged: Dict[str, object] = {}
    try:
        old = json.loads(_read_text(STATE_FILE) or "{}")
        if isinstance(old, dict):
            merged.update(old)
    except ValueError:
        pass
    merged.update(data)
    body = json.dumps(merged, sort_keys=True)
    if _read_text(STATE_FILE) == body:
        return
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(body)
    os.replace(tmp, STATE_FILE)


def _set_interface(name: str, persist: bool = True) -> None:
    global INTERFACE, _counters_prev
    if name == INTERFACE:
        return
    log.info("Watchdog now watching %s (was %s)", name, INTERFACE)
    INTERFACE = name
    _counters_prev = None
    if persist:
        try:
            _save_state({"interface": name})
        except OSError as e:
            log.warning("Couldn't save the chosen WiFi device to %s: %s", STATE_FILE, e)


def _load_saved_interface() -> None:
    txt = _read_text(STATE_FILE)
    if not txt:
        return
    try:
        name = json.loads(txt).get("interface")
    except (ValueError, AttributeError):
        return
    if isinstance(name, str) and _IFACE_RE.match(name) \
            and os.path.isdir(f"/sys/class/net/{name}/wireless"):
        _set_interface(name, persist=False)
    elif name:
        log.warning("Saved WiFi device %r not found — using %s", name, INTERFACE)


def _pending_persist(p: Optional[Dict[str, object]]) -> None:
    try:
        if p is None:
            os.remove(PENDING_FILE)
            return
        os.makedirs(SHUTDOWN_STATE_DIR, exist_ok=True)
        tmp = PENDING_FILE + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"id": p["id"], "kind": p["kind"], "desc": p["desc"],
                       "undo": p["undo"]}, f)
        os.replace(tmp, PENDING_FILE)
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("Couldn't update %s: %s", PENDING_FILE, e)


def _begin_change(kind: str, desc: str, undo: Dict[str, object]) -> Dict[str, object]:
    global _pending
    p: Dict[str, object] = {
        "id": secrets.token_hex(6), "kind": kind, "desc": desc, "undo": undo,
        "keep_after": float("inf"), "deadline": float("inf"),
    }
    with _change_lock:
        _pending = p
    _pending_persist(p)
    return p


def _arm_change(p: Dict[str, object]) -> None:
    now = time.monotonic()
    with _change_lock:
        p["keep_after"] = now + _KEEP_MIN_SECS
        p["deadline"] = now + float(p.get("undo_secs") or CHANGE_UNDO_SECS)
    threading.Thread(target=_pending_watch, args=(p["id"],), name="undo-timer",
                     daemon=True).start()
    log.info("Pending change: %s (undoes itself in %d s unless the page checks in)",
             p["desc"], int(p.get("undo_secs") or CHANGE_UNDO_SECS))


def _drop_change(p: Dict[str, object]) -> None:
    global _pending
    with _change_lock:
        if _pending is p:
            _pending = None
    _pending_persist(None)


def _finish_change(p: Dict[str, object], outcome: str, ok: bool, message: str) -> None:
    global _pending, _last_result
    with _change_lock:
        if _pending is not None and _pending.get("id") == p.get("id"):
            _pending = None
        _last_result = {"id": p.get("id"), "desc": p.get("desc"), "outcome": outcome,
                        "ok": ok, "message": message, "at": time.time()}
    _pending_persist(None)
    level = logging.INFO if ok else logging.WARNING
    log.log(level, "Change %s: %s (%s)", outcome, p.get("desc"), message)


def _apply_undo(undo: Dict[str, object]) -> Tuple[bool, str]:
    ok_all, notes = True, []
    dm = undo.get("dev_mode")
    if isinstance(dm, dict) and dm.get("mode") in _DEV_MODES and isinstance(dm.get("key"), str) \
            and _DEV_KEY_RE.match(dm["key"]) and isinstance(dm.get("name"), str) and _IFACE_RE.match(dm["name"]):
        _set_dev_mode(dm["key"], dm["name"], dm["mode"])
        ok, msg = _nmcli_ok(["device", "set", dm["name"], "autoconnect",
                             "no" if dm["mode"] == "off" else "yes"])
        if not ok:
            notes.append("adapter setting: " + msg)
    if undo.get("country"):
        code = str(undo["country"])
        if code == "00":
            ok, msg = _nmcli_free_run(["iw", "reg", "set", "00"])
            try:
                if (_read_text(COUNTRY_MODPROBE) or "").startswith("# Written by wifimon"):
                    os.remove(COUNTRY_MODPROBE)
            except OSError:
                pass
        else:
            ok, msg, _v = _country_apply(code)
        ok_all &= ok
        if not ok:
            notes.append("country: " + msg)
    if undo.get("nm_restore"):
        rest = undo["nm_restore"]
        for uuid_, props in rest["props"].items():
            args = ["connection", "modify", "uuid", uuid_]
            for k, v in props.items():
                args += [k, v]
            ok, msg = _nmcli_ok(args)
            ok_all &= ok
            if not ok:
                notes.append("restore: " + msg)
        if rest.get("activate"):
            ok, msg = _nmcli_ok(["--wait", str(WM_CONNECT_WAIT), "connection", "up", "uuid",
                                 str(rest["activate"]), "ifname", INTERFACE],
                                timeout=WM_CONNECT_WAIT + 15)
            ok_all &= ok
            if not ok:
                notes.append("reconnect: " + msg)
    if undo.get("radio_on"):
        ok, msg = _nmcli_ok(["radio", "wifi", "on"])
        ok_all &= ok
        if not ok:
            notes.append("radio on: " + msg)
        time.sleep(3)
    if undo.get("interface"):
        _set_interface(str(undo["interface"]))
    if undo.get("disconnect"):
        ok, msg = _nmcli_ok(["device", "disconnect", str(undo["disconnect"])])
        if not ok:
            notes.append("disconnect: " + msg)
    if undo.get("reconnect"):
        dev, prof = str(undo["reconnect"]), undo.get("profile")
        if prof:
            ok, msg = _nmcli_ok(["connection", "up", "id", str(prof), "ifname", dev], timeout=45)
        else:
            ok, msg = _nmcli_ok(["device", "connect", dev], timeout=45)
        ok_all &= ok
        if not ok:
            notes.append("reconnect: " + msg)
    return ok_all, "; ".join(notes)


def _undo_change(change_id: str, why: str) -> bool:
    with _action_lock:
        with _change_lock:
            p = _pending
        if p is None or p.get("id") != change_id:
            return False
        _grace_start("undoing a dashboard change")
        ok, msg = _apply_undo(p["undo"])
        _finish_change(p, "undone", ok, why if ok else f"{why}; undo had problems: {msg}")
        _slow_refresh.set()
        return True


def _pending_watch(change_id: str) -> None:
    while not _shutdown_event.wait(0.5):
        with _change_lock:
            p = _pending
            if p is None or p.get("id") != change_id:
                return
            due = time.monotonic() >= float(p["deadline"])
        if due:
            _undo_change(change_id, f"the page didn't check in within {CHANGE_UNDO_SECS} s")
            return


def _recover_pending_change() -> None:
    global _last_result
    txt = _read_text(PENDING_FILE)
    if not txt:
        return
    try:
        data = json.loads(txt)
        undo = data["undo"]
        assert isinstance(undo, dict)
    except (ValueError, KeyError, AssertionError, TypeError):
        _pending_persist(None)
        return
    log.warning("A dashboard change was still pending when wifimon stopped (%s) — undoing it",
                _log_safe(data.get("desc")))
    _grace_start("undoing a change left pending by a restart")
    ok, msg = _apply_undo(undo)
    with _change_lock:
        _last_result = {"id": data.get("id"), "desc": data.get("desc"), "outcome": "undone",
                        "ok": ok, "message": "wifimon restarted before the change was kept"
                        + ("" if ok else f"; undo had problems: {msg}"), "at": time.time()}
    _pending_persist(None)


def _pending_public() -> Optional[Dict[str, object]]:
    with _change_lock:
        p = dict(_pending) if _pending else None
    if not p:
        return None
    now = time.monotonic()
    armed = p["deadline"] != float("inf")
    return {
        "id": p["id"], "kind": p["kind"], "desc": p["desc"], "armed": armed,
        "remaining": max(0.0, float(p["deadline"]) - now) if armed else None,
        "keep_after": max(0.0, float(p["keep_after"]) - now) if armed else None,
        "total": p.get("undo_secs") or CHANGE_UNDO_SECS,
        "open_url": p.get("open_url"),
    }


def _control_public() -> Dict[str, object]:
    grace = _grace_remaining()
    with _change_lock:
        last = dict(_last_result) if _last_result else None
    return {
        "available": bool(shutil.which("nmcli")),
        "pending": _pending_public(),
        "grace_remaining": grace if grace > 0 else None,
        "grace_total": CHANGE_GRACE_SECS,
        "undo_secs": CHANGE_UNDO_SECS,
        "last_result": last,
    }


def _connected_state(state: object) -> bool:
    return isinstance(state, str) and state.startswith("connected")


_DEV_MODES = ("auto", "on", "off")
_DEV_MODE_WORDS = {"auto": "Auto", "on": "Keep on", "off": "Keep off"}
_DEV_KEY_RE = re.compile(r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$|^if:[A-Za-z0-9][A-Za-z0-9_.-]{0,14}$")
_devmode_lock = threading.Lock()
_dev_modes: Dict[str, Dict[str, str]] = {}
_devmode_wake = threading.Event()
_devmode_last_try: Dict[str, float] = {}
_devmode_notes: Dict[str, str] = {}
_devmode_off_log: Dict[str, List[float]] = {}
_devmode_applied: set = set()


def _adapter_key(name: str) -> Optional[str]:
    buf = array.array("B", struct.pack("II", 0x00000020, 32) + bytes(32))
    addr, _n = buf.buffer_info()
    ifr = struct.pack("16sP", name.encode()[:15], addr)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            fcntl.ioctl(sock.fileno(), 0x8946, ifr)
        size = struct.unpack_from("I", buf.tobytes(), 4)[0]
        data = buf.tobytes()[8:8 + size]
        if size == 6 and any(data):
            return ":".join(f"{b:02x}" for b in data)
    except (OSError, struct.error):
        pass
    if (_read_text(f"/sys/class/net/{name}/addr_assign_type") or "").strip() == "0":
        mac = (_read_text(f"/sys/class/net/{name}/address") or "").strip().lower()
        if _DEV_KEY_RE.match(mac) and mac != "00:00:00:00:00:00":
            return mac
    return f"if:{name}" if _IFACE_RE.match(name) else None


def _dev_mode_of(key: Optional[str]) -> str:
    if not key:
        return "auto"
    with _devmode_lock:
        m = _dev_modes.get(key)
    return m["mode"] if m else "auto"


def _save_dev_modes() -> None:
    with _devmode_lock:
        data = {k: dict(v) for k, v in _dev_modes.items()}
    try:
        _save_state({"device_modes": data})
    except OSError as e:
        log.warning("Couldn't save the adapter settings to %s: %s", STATE_FILE, e)


def _set_dev_mode(key: str, name: str, mode: str, persist: bool = True) -> None:
    with _devmode_lock:
        if mode == "auto":
            _dev_modes.pop(key, None)
        else:
            _dev_modes[key] = {"mode": mode, "name": name}
        _devmode_notes.pop(key, None)
        _devmode_last_try.pop(key, None)
        _devmode_applied.discard(key)
    if persist:
        _save_dev_modes()
    _devmode_wake.set()


def _load_dev_modes() -> None:
    txt = _read_text(STATE_FILE)
    if not txt:
        return
    try:
        raw = json.loads(txt).get("device_modes") or {}
    except (ValueError, AttributeError):
        return
    if not isinstance(raw, dict):
        return
    loaded = {}
    for key, v in raw.items():
        if not (isinstance(key, str) and _DEV_KEY_RE.match(key) and isinstance(v, dict)):
            continue
        mode, name = v.get("mode"), v.get("name")
        if mode in ("on", "off") and isinstance(name, str) and _IFACE_RE.match(name):
            loaded[key] = {"mode": mode, "name": name}
    with _devmode_lock:
        _dev_modes.clear()
        _dev_modes.update(loaded)
    for key, v in loaded.items():
        log.info("Adapter setting: %s (%s) is set to %s", v["name"], key, _DEV_MODE_WORDS[v["mode"]])


def _devmode_note(key: str, text: Optional[str]) -> None:
    with _devmode_lock:
        if text:
            _devmode_notes[key] = text
        else:
            _devmode_notes.pop(key, None)


def _devmode_log_off(name: str) -> None:
    now = time.monotonic()
    times = [t for t in _devmode_off_log.get(name, []) if now - t < 60]
    if not times:
        log.info("Keep off: %s was joining or had joined a network again -- disconnected it", name)
    times.append(now)
    if len(times) == 5:
        log.warning("Keep off: %s keeps trying to connect (5 times in a minute)", name)
    _devmode_off_log[name] = times


def _job_running() -> bool:
    with _change_lock:
        return bool(_job and _job.get("state") == "running")


def _keep_on_join(name: str) -> Tuple[bool, str]:
    active = set()
    for line in _run_text(["nmcli", "-t", "-f", "UUID", "connection", "show", "--active"]).splitlines():
        if line.strip():
            active.add(line.strip())
    visible = {f[1] for f in _nm_scan_lines() if len(f) > 1 and f[1]}
    cands = [p for p in _nm_wifi_profiles()
             if p["uuid"] not in active and p.get("autoconnect", True)
             and (p.get("hidden") or not visible or p["ssid"] in visible)]
    if not cands:
        return False, "no free saved network in range (each one is off, out of range, or in use on another adapter)"
    cands.sort(key=lambda p: -(p.get("nm_priority") or 0))
    last = ""
    for p in cands[:3]:
        ok, msg = _nmcli_ok(["--wait", "20", "connection", "up", "uuid", str(p["uuid"]),
                             "ifname", name], timeout=30)
        if ok:
            return True, str(p["ssid"])
        last = msg
    return False, last or "couldn't join"


def _devmode_tick() -> None:
    with _devmode_lock:
        modes = {k: dict(v) for k, v in _dev_modes.items()}
    if not modes or not shutil.which("nmcli") or _hotspot_active():
        return
    if not _action_lock.acquire(blocking=False):
        return
    try:
        with _change_lock:
            if _pending is not None:
                return
        devs = _wifi_devices()
        renamed = False
        for d in devs:
            key = d.get("hw")
            m = modes.get(key) if key else None
            if m and m["name"] != d["device"]:
                log.info("Adapter %s is now called %s (was %s) -- its %s setting follows it",
                         key, d["device"], m["name"], _DEV_MODE_WORDS[m["mode"]])
                with _devmode_lock:
                    if key in _dev_modes:
                        _dev_modes[key]["name"] = d["device"]
                renamed = True
        if renamed:
            _save_dev_modes()
        for d in devs:
            key = d.get("hw")
            m = modes.get(key) if key else None
            if not m:
                continue
            name, state = str(d["device"]), str(d.get("state") or "")
            if state == "unmanaged":
                _devmode_note(key, "NetworkManager isn't managing this adapter, so wifimon can't control it.")
                continue
            if m["mode"] == "off":
                if name == INTERFACE:
                    alt = None
                    for pref in ("on", "connected", "any"):
                        for o in devs:
                            om = _dev_mode_of(o.get("hw"))
                            if o["device"] == name or om == "off" or o.get("state") == "unmanaged":
                                continue
                            if pref == "on" and om != "on":
                                continue
                            if pref == "connected" and not _connected_state(o.get("state")):
                                continue
                            alt = str(o["device"])
                            break
                        if alt:
                            break
                    if not alt:
                        _devmode_note(key, "The watchdog is using this adapter and there's no other one "
                                           "to move it to, so it isn't being kept off.")
                        continue
                    log.warning("%s is set to Keep off but the watchdog was using it "
                                "(adapter names may have changed) -- watchdog moved to %s", name, alt)
                    _grace_start(f"watchdog moved from {name} to {alt} (Keep off)")
                    _set_interface(alt)
                _devmode_note(key, None)
                if key not in _devmode_applied:
                    ok, _m = _nmcli_ok(["device", "set", name, "autoconnect", "no"])
                    if ok:
                        _devmode_applied.add(key)
                if state.startswith("connect"):
                    ok, msg = _nmcli_ok(["device", "disconnect", name])
                    if ok:
                        _devmode_log_off(name)
                    else:
                        log.warning("Keep off: couldn't disconnect %s: %s", name, msg)
                continue
            if key not in _devmode_applied:
                ok, _m = _nmcli_ok(["device", "set", name, "autoconnect", "yes"])
                if ok:
                    _devmode_applied.add(key)
            if name == INTERFACE:
                _devmode_note(key, None)
                continue
            if state.startswith("connected"):
                _devmode_note(key, None)
                continue
            if state != "disconnected" or _job_running():
                continue
            now = time.monotonic()
            if now - _devmode_last_try.get(key, -1e9) < RECONNECT_INTERVAL_SECS:
                continue
            _devmode_last_try[key] = now
            ok, msg = _keep_on_join(name)
            if ok:
                log.info("Keep on: %s had dropped -- joined it to %s", name, msg)
                _devmode_note(key, None)
            else:
                log.warning("Keep on: couldn't join %s: %s", name, msg)
                _devmode_note(key, "Last try to join failed: " + msg)
        _slow_refresh.set()
    finally:
        _action_lock.release()


def _devmode_loop() -> None:
    while not _shutdown_event.is_set():
        try:
            _devmode_tick()
        except Exception:
            log.exception("Adapter keep on/off check failed -- continuing")
        _devmode_wake.wait(DEVMODE_CHECK_SECS)
        _devmode_wake.clear()


def _devices_public(devs: List[Dict[str, object]]) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    with _devmode_lock:
        modes = {k: dict(v) for k, v in _dev_modes.items()}
        notes = dict(_devmode_notes)
    present = set()
    out = []
    for d in devs:
        key = d.get("hw")
        present.add(key)
        m = modes.get(key) if key else None
        out.append(dict(d, watched=(d.get("device") == INTERFACE),
                        mode=m["mode"] if m else "auto", mode_note=notes.get(key) if key else None))
    absent = [{"key": k, "name": v["name"], "mode": v["mode"]}
              for k, v in sorted(modes.items()) if k not in present]
    return out, absent


_conf_lock = threading.Lock()
_networks_changed = threading.Event()
_job: Optional[Dict[str, object]] = None
_STATUS_KNOWN = ("known_good", "unverified", "failed")
_SECURITY_KEYMGMT = {"open": None, "wpa2": "wpa-psk", "wpa3": "sae"}


def _conf_networks() -> List[Dict[str, object]]:
    if not os.path.exists(CONFIG_FILE):
        return []
    return load_wifi_networks()


def _set_network_status(ssid: str, status: str) -> None:
    with _conf_lock:
        nets = _conf_networks()
        changed = False
        for n in nets:
            if n["ssid"] == ssid and n.get("status") != status:
                n["status"] = status
                changed = True
        if changed:
            save_wifi_networks(nets, quiet=True)
            _mark_networks_changed()
            log.info("Network %s tagged %s", ssid, status)


def _security_label(key_mgmt: Optional[str]) -> str:
    return {"": "Open", "none": "Open", "wpa-psk": "WPA2", "sae": "WPA3",
            "wpa-eap": "Enterprise", "owe": "Open (OWE)"}.get((key_mgmt or "").strip(),
                                                              key_mgmt or "Open")


def _nm_wifi_profiles() -> List[Dict[str, object]]:
    uuids = []
    for line in _run_text(["nmcli", "-t", "-f", "UUID,TYPE", "connection", "show"]).splitlines():
        f = _nmcli_split(line)
        if len(f) >= 2 and f[1] == "802-11-wireless":
            uuids.append(f[0])
    if not uuids:
        return []
    args = ["nmcli", "-t", "-f",
            "connection.id,connection.uuid,802-11-wireless.ssid,802-11-wireless.hidden,"
            "802-11-wireless-security.key-mgmt,connection.autoconnect-priority,"
            "connection.autoconnect,802-11-wireless.powersave,ipv4.method,ipv4.addresses,"
            "ipv4.gateway,ipv4.dns,ipv4.ignore-auto-dns,802-11-wireless.cloned-mac-address,"
            "802-11-wireless.band,802-11-wireless.mode",
            "connection", "show"]
    for u in uuids:
        args += ["uuid", u]
    out: List[Dict[str, object]] = []
    cur: Dict[str, object] = {}
    for line in _run_text(args, timeout=10).splitlines():
        parts = _nmcli_split(line)
        key, value = parts[0], ":".join(parts[1:])
        if key == "connection.id":
            cur = {"name": value}
            out.append(cur)
        elif key == "connection.uuid":
            cur["uuid"] = value
        elif key == "802-11-wireless.ssid":
            cur["ssid"] = value if value and value != "--" else None
        elif key == "802-11-wireless.hidden":
            cur["hidden"] = value.strip().lower() == "yes"
        elif key == "802-11-wireless-security.key-mgmt":
            cur["security"] = _security_label(value if value != "--" else "")
        elif key == "connection.autoconnect-priority":
            cur["nm_priority"] = _to_int(value)
        elif key == "connection.autoconnect":
            cur["autoconnect"] = value.strip().lower() != "no"
        elif key == "802-11-wireless.powersave":
            cur["powersave"] = _powersave_code(value)
        elif key in _OPTION_KEYS:
            cur[key] = "" if value.strip() == "--" else value.strip()
    return [p for p in out if p.get("ssid") and p.get("uuid") and p.get("802-11-wireless.mode") != "ap"]


def _scan_from_lines(lines: List[List[str]]) -> List[Dict[str, object]]:
    best: Dict[str, Dict[str, object]] = {}
    for f in lines:
        ssid = f[1]
        if not ssid:
            continue
        signal = _first_int(f[5]) or 0
        freq = _first_int(f[4])
        band, _chan = _freq_band_channel(freq)
        sec = f[6].strip()
        entry = {"ssid": ssid, "signal": signal, "band": band,
                 "security": sec if sec and sec != "--" else "Open",
                 "in_use": f[0].strip() == "*"}
        old = best.get(ssid)
        if old is None or signal > int(old["signal"]) or entry["in_use"]:
            entry["in_use"] = entry["in_use"] or bool(old and old["in_use"])
            best[ssid] = entry
    return sorted(best.values(), key=lambda e: -int(e["signal"]))


def _saved_public(slow: Dict[str, object], active_ssid: object) -> Dict[str, object]:
    rows: Dict[str, Dict[str, object]] = {}
    order: List[str] = []
    for n in _conf_networks():
        ssid = str(n["ssid"])
        if ssid in rows:
            continue
        status = n.get("status") if n.get("status") in _STATUS_KNOWN else "unverified"
        rows[ssid] = {"ssid": ssid, "priority": n["priority"], "status": status,
                      "hidden": bool(n.get("hidden")), "security": n.get("security"),
                      "in_conf": True, "in_nm": False}
        order.append(ssid)
    nm_only: List[str] = []
    for prof in slow.get("profiles") or []:
        ssid = str(prof["ssid"])
        row = rows.get(ssid)
        if row is None:
            row = {"ssid": ssid, "priority": None, "status": None,
                   "hidden": bool(prof.get("hidden")), "security": prof.get("security"),
                   "in_conf": False, "in_nm": True}
            rows[ssid] = row
            nm_only.append(ssid)
        row["in_nm"] = True
        row["hidden"] = bool(row["hidden"] or prof.get("hidden"))
        if not row.get("security"):
            row["security"] = prof.get("security")
    by_ssid: Dict[str, List[Dict[str, object]]] = {}
    for prof in slow.get("profiles") or []:
        by_ssid.setdefault(str(prof["ssid"]), []).append(prof)
    scan = {e["ssid"]: e for e in (slow.get("scan") or [])}
    result = []
    for ssid in order + sorted(nm_only, key=str.lower):
        row = rows[ssid]
        profs = by_ssid.get(ssid, [])
        row["autojoin"] = all(p.get("autoconnect", True) for p in profs) if profs else None
        row["powersave"] = (("off" if all(p.get("powersave") == 2 for p in profs) else "default")
                            if profs else None)
        row["options"] = _options_public(profs[0]) if profs else None
        row["in_use"] = ssid == active_ssid
        row["signal"] = scan[ssid]["signal"] if ssid in scan else None
        row["security"] = row.get("security") or (scan[ssid]["security"] if ssid in scan else None)
        result.append(row)
    return {"available": bool(shutil.which("nmcli")), "networks": result,
            "test_secs": NEW_NETWORK_TEST_SECS, "fallback_secs": FALLBACK_TEST_SECS}


def _keyfile_escape(value: str) -> str:
    out = value.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
    if out.startswith(" "):
        out = "\\s" + out[1:]
    return out


def _nm_add_profile(ssid: str, security: str, password: str, hidden: bool,
                    autoconnect: bool = True, powersave: Optional[int] = None,
                    real_mac: bool = False) -> Tuple[bool, str]:
    if not os.path.isdir(NM_CONN_DIR):
        return False, f"{NM_CONN_DIR} not found"
    con_uuid = str(uuid.uuid4())
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", ssid)[:24] or "wifi"
    path = os.path.join(NM_CONN_DIR, f"{safe}-wifimon-{con_uuid[:8]}.nmconnection")
    lines = [
        "[connection]",
        f"id={_keyfile_escape(ssid)}",
        f"uuid={con_uuid}",
        "type=wifi",
        "autoconnect=" + ("true" if autoconnect else "false"),
        "",
        "[wifi]",
        "mode=infrastructure",
        "ssid=" + ";".join(str(b) for b in ssid.encode("utf-8")) + ";",
    ]
    if hidden:
        lines.append("hidden=true")
    if powersave is not None:
        lines.append(f"powersave={int(powersave)}")
    if real_mac:
        lines.append("cloned-mac-address=permanent")
    key_mgmt = _SECURITY_KEYMGMT[security]
    if key_mgmt:
        lines += ["", "[wifi-security]", f"key-mgmt={key_mgmt}", f"psk={_keyfile_escape(password)}"]
    lines += ["", "[ipv4]", "method=auto", "", "[ipv6]", "method=auto", ""]
    tmp = path + ".tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        os.replace(tmp, path)
    except OSError as e:
        return False, f"couldn't write the profile: {e}"
    ok, msg = _nmcli_ok(["connection", "load", path])
    if not ok:
        try:
            os.remove(path)
        except OSError:
            pass
        return False, msg or "nmcli couldn't load the profile"
    return True, con_uuid


def _profiles_for(ssid: str) -> List[Dict[str, object]]:
    return [p for p in _nm_wifi_profiles() if p["ssid"] == ssid]


def _activate_and_check(ssid: str, secs: int) -> Tuple[bool, str]:
    deadline = time.monotonic() + secs
    profiles = _profiles_for(ssid)
    if profiles:
        ok, msg = _nmcli_ok(["--wait", str(secs), "connection", "up",
                             "uuid", str(profiles[0]["uuid"]), "ifname", INTERFACE],
                            timeout=secs + 15)
    else:
        conf = next((n for n in _conf_networks() if n["ssid"] == ssid), None)
        if conf is None:
            return False, "no saved profile"
        ok, msg = _connect_nmcli(ssid, str(conf.get("psk") or "")), ""
    if not ok:
        return False, msg or "couldn't join"
    while True:
        if is_connected():
            return True, ""
        if time.monotonic() >= deadline:
            return False, _no_internet_reason()
        time.sleep(2)


def _visible_ssids() -> Optional[set]:
    _nmcli_ok(["device", "wifi", "rescan", "ifname", INTERFACE], timeout=15)
    time.sleep(3)
    names = {f[1] for f in _nm_scan_lines() if f[1]}
    return names or None


def _job_public() -> Optional[Dict[str, object]]:
    with _change_lock:
        if _job is None:
            return None
        job = dict(_job)
        job["steps"] = [dict(st) for st in _job["steps"]]
    return job


def _job_step(job: Dict[str, object], ssid: str, role: str, result: str, note: str = "") -> Dict[str, object]:
    step = {"ssid": ssid, "role": role, "result": result, "note": note}
    with _change_lock:
        job["steps"].append(step)
        if result == "trying":
            job["phase"] = f"Trying {ssid}"
    return step


def _job_finish(job: Dict[str, object], state: str, message: str) -> None:
    with _change_lock:
        job["state"] = state
        job["message"] = message
        job["ended_at"] = time.time()
        job["phase"] = None
    level = logging.INFO if state in ("ok", "fallback") else logging.WARNING
    log.log(level, "Connect job: %s", message)


def _try_network(job: Dict[str, object], ssid: str, role: str, secs: int) -> bool:
    _grace_start(f"trying {ssid} from the dashboard")
    step = _job_step(job, ssid, role, "trying")
    ok, note = _activate_and_check(ssid, secs)
    with _change_lock:
        step["result"] = "ok" if ok else "failed"
        step["note"] = note
    return ok


def _connect_job(job: Dict[str, object], previous: Optional[str]) -> None:
    target = str(job["target"])
    try:
        if _try_network(job, target, "target", NEW_NETWORK_TEST_SECS):
            _set_network_status(target, "known_good")
            done = "Reconnected to" if job.get("kind") == "reconnect" else "Switched to"
            _job_finish(job, "ok", f"{done} {target}.")
            return
        _set_network_status(target, "failed")
        with _change_lock:
            why = str(job["steps"][0].get("note") or "") if job["steps"] else ""
        why = f" ({why})" if why else ""

        candidates: List[Tuple[str, str]] = []
        if previous and previous != target:
            candidates.append((previous, "return"))
        no_auto = _autojoin_off_ssids()
        for n in _conf_networks():
            if n.get("status") == "known_good" and n["ssid"] not in (target, previous) \
                    and n["ssid"] not in no_auto:
                candidates.append((str(n["ssid"]), "fallback"))
        hidden = {str(n["ssid"]) for n in _conf_networks() if n.get("hidden")}
        hidden |= {str(p["ssid"]) for p in _nm_wifi_profiles() if p.get("hidden")}
        visible = _visible_ssids() if candidates else None

        for ssid, role in candidates:
            if _shutdown_event.is_set():
                break
            if visible is not None and ssid not in visible and ssid not in hidden:
                _job_step(job, ssid, role, "skipped", "not in range")
                continue
            if _try_network(job, ssid, role, FALLBACK_TEST_SECS):
                _set_network_status(ssid, "known_good")
                _job_finish(job, "fallback", f"{target} didn't connect{why}, so the node went back to {ssid}.")
                return

        _grace_clear()
        _job_finish(job, "failed", f"{target} didn't connect{why}, and no known-good network came back. "
                                   "The watchdog has taken over.")
    except Exception:
        log.exception("Connect job crashed")
        _grace_clear()
        _job_finish(job, "failed", "The connect job hit an unexpected error. The watchdog has taken over.")
    finally:
        _slow_refresh.set()
        _action_lock.release()


def _start_connect_job(target: str, kind: str = "connect") -> Dict[str, object]:
    global _job
    active = _nmcli_active_ap().get("nm_ssid") or _current_ssid()
    job: Dict[str, object] = {
        "id": secrets.token_hex(6), "target": target, "state": "running", "kind": kind,
        "phase": f"Trying {target}", "steps": [], "started_at": time.time(),
        "ended_at": None, "message": None, "previous": active,
    }
    with _change_lock:
        _job = job
    log.info("Connect job: %s (return point: %s)", target, active or "none")
    threading.Thread(target=_connect_job, args=(job, active), name="connect-job",
                     daemon=True).start()
    return job


def _grace_clear() -> None:
    global _grace_until
    with _change_lock:
        _grace_until = None
    log.info("Shutdown timer pause ended")


_SSID_BAD_RE = re.compile(r"[\x00-\x1f\x7f]")


def _check_new_network(body: Dict[str, object]) -> Tuple[Optional[Dict[str, object]], str]:
    ssid, security = body.get("ssid"), body.get("security")
    password, hidden = body.get("password") or "", body.get("hidden") is True
    if not isinstance(ssid, str) or not ssid:
        return None, "Enter the network name."
    if len(ssid.encode("utf-8")) > 32:
        return None, "Network names can be at most 32 bytes."
    if _SSID_BAD_RE.search(ssid) or ssid != ssid.strip():
        return None, "That network name has characters wifimon can't store (control characters, or a space at the start or end)."
    if security not in _SECURITY_KEYMGMT:
        return None, "Pick the security type."
    if not isinstance(password, str):
        return None, "Bad password."
    if security == "open":
        password = ""
    elif not (8 <= len(password) <= 63 and all(" " <= c <= "~" for c in password)) \
            and not (security == "wpa2" and re.fullmatch(r"[0-9A-Fa-f]{64}", password)):
        return None, "WiFi passwords are 8 to 63 ordinary characters (letters, numbers, symbols)."
    return {"ssid": ssid, "security": security, "password": password, "hidden": hidden}, ""


_SETTINGS_SPEC: Dict[str, Tuple[str, type, Optional[float], Optional[float]]] = {
    "no_conn_shutdown_secs":     ("NO_CONN_SHUTDOWN_SECS", int, 60, 86400),
    "low_voltage_shutdown_secs": ("LOW_VOLTAGE_SHUTDOWN_SECS", int, 10, 3600),
    "low_voltage_threshold":     ("LOW_VOLTAGE_THRESHOLD", float, 0.70, 1.00),
    "reconnect_interval_secs":   ("RECONNECT_INTERVAL_SECS", int, 5, 600),
    "check_interval":            ("CHECK_INTERVAL", int, 2, 60),
    "ping_target":               ("PING_TARGET", str, None, None),
    "detect_login_pages":        ("DETECT_LOGIN_PAGES", bool, None, None),
    "keep_powersave_off":        ("KEEP_POWERSAVE_OFF", bool, None, None),
}
_SETTING_DEFAULTS: Dict[str, object] = {k: globals()[g] for k, (g, _t, _a, _b) in _SETTINGS_SPEC.items()}
_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
_timers_reset = threading.Event()


def _settings_current() -> Dict[str, object]:
    return {k: globals()[g] for k, (g, _t, _a, _b) in _SETTINGS_SPEC.items()}


def _settings_public() -> Dict[str, object]:
    return {"values": _settings_current(), "defaults": dict(_SETTING_DEFAULTS),
            "limits": {k: [lo, hi] for k, (_g, _t, lo, hi) in _SETTINGS_SPEC.items()
                       if lo is not None}}


def _validate_settings(raw: object) -> Tuple[Optional[Dict[str, object]], str]:
    if not isinstance(raw, dict):
        return None, "No settings given."
    out: Dict[str, object] = {}
    for key, value in raw.items():
        if key not in _SETTINGS_SPEC:
            return None, f"Unknown setting: {key}"
        _g, kind, lo, hi = _SETTINGS_SPEC[key]
        if kind is bool:
            if not isinstance(value, bool):
                return None, f"{key} must be on or off."
            out[key] = value
            continue
        if kind is str:
            if not isinstance(value, str) or not _HOST_RE.match(value.strip()):
                return None, "The internet-check address must be a host name or IP address."
            out[key] = value.strip()
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, f"{key} must be a number."
        if kind is int:
            if value != int(value):
                return None, f"{key} must be a whole number."
            value = int(value)
        else:
            value = round(float(value), 3)
        if not (lo <= value <= hi):
            return None, f"{key} must be between {lo} and {hi}."
        out[key] = value
    return out, ""


def _apply_settings(values: Dict[str, object], persist: bool = True) -> Optional[str]:
    before = _settings_current()
    for key, value in values.items():
        globals()[_SETTINGS_SPEC[key][0]] = value
    if any(before[k] != v for k, v in values.items()
           if k not in ("detect_login_pages", "keep_powersave_off")):
        _timers_reset.set()
    notes: List[str] = []
    if "detect_login_pages" in values:
        notes.append(_apply_login_page_detection(bool(values["detect_login_pages"])) or "")
    if "keep_powersave_off" in values:
        notes.append(_apply_keep_powersave_off(bool(values["keep_powersave_off"])) or "")
    if persist:
        _save_state({"settings": _settings_current()})
    return " ".join(n for n in notes if n) or None


def _load_saved_settings() -> None:
    try:
        data = json.loads(_read_text(STATE_FILE) or "{}")
    except ValueError:
        return
    saved = data.get("settings") if isinstance(data, dict) else None
    if not saved:
        return
    values, err = _validate_settings(saved)
    if values is None:
        log.warning("Ignoring saved watchdog settings in %s: %s", STATE_FILE, err)
        return
    _apply_settings(values, persist=False)
    log.info("Loaded watchdog settings from %s", STATE_FILE)


def _nm_secret(ssid: str) -> str:
    for prof in _profiles_for(ssid):
        txt = _run_text(["nmcli", "-s", "--escape", "no", "-g",
                         "802-11-wireless-security.psk", "connection", "show",
                         "uuid", str(prof["uuid"])])
        secret = txt.rstrip("\n")
        if secret:
            return secret
    return ""


def _move_network(ssid: str, direction: str) -> Optional[str]:
    with _conf_lock:
        nets = _conf_networks()
        idx = next((i for i, n in enumerate(nets) if n["ssid"] == ssid), None)
        if idx is None:
            return f"{ssid} isn't in the reconnect list."
        other = idx - 1 if direction == "up" else idx + 1
        if not 0 <= other < len(nets):
            return None
        nets[idx], nets[other] = nets[other], nets[idx]
        for i, n in enumerate(nets, start=1):
            n["priority"] = i
        save_wifi_networks(nets, quiet=True)
    _mark_networks_changed()
    return None


def _track_networks(ssids: List[str]) -> List[str]:
    added: List[str] = []
    with _conf_lock:
        nets = _conf_networks()
        have = {str(n["ssid"]) for n in nets}
        profiles = _nm_wifi_profiles()
        for ssid in ssids:
            prof = next((p for p in profiles if p["ssid"] == ssid), None)
            if ssid in have or prof is None:
                continue
            nets.append({"ssid": ssid, "psk": _nm_secret(ssid),
                         "priority": max((int(n["priority"]) for n in nets), default=0) + 1,
                         "status": "unverified", "hidden": bool(prof.get("hidden")),
                         "security": prof.get("security") or ""})
            have.add(ssid)
            added.append(ssid)
        if added:
            save_wifi_networks(nets, quiet=True)
    if added:
        _mark_networks_changed()
    return added


_SECURITY_FROM_LABEL = {"Open": "open", "WPA2": "wpa2", "WPA3": "wpa3"}


_rec_lock = threading.Lock()
_rec: Dict[str, object] = {"active": False}


def _cpu_temp() -> Optional[float]:
    raw = _read_text("/sys/class/thermal/thermal_zone0/temp")
    try:
        return round(int(str(raw).strip()) / 1000.0, 1)
    except (TypeError, ValueError):
        return None


def _snapshot(label: str) -> Dict[str, object]:
    st = _build_status()
    now = float(st["now"])
    wd = {k: v for k, v in dict(st["watchdog"]).items()
          if k not in ("settings", "recording")}
    return {
        "label": label,
        "at": now,
        "interface": INTERFACE,
        "wifi": st["wifi"],
        "net": st["net"],
        "watchdog": wd,
        "power": st["power"],
        "temp_c": _cpu_temp(),
        "data_age_secs": {
            "fast": round(now - st["fast_at"], 1) if st.get("fast_at") else None,
            "slow": round(now - st["slow_at"], 1) if st.get("slow_at") else None,
        },
    }


_TRIGGER_WORDS = {"no_conn": "no connection", "low_voltage": "low voltage"}


def _recorder_tick(down_since: Optional[float], lowv_since: Optional[float], now_mono: float) -> None:
    trigger = "low_voltage" if lowv_since is not None else ("no_conn" if down_since is not None else None)
    with _rec_lock:
        active = bool(_rec.get("active"))
        current = _rec.get("trigger")
        last = _rec.get("last_mono")
    if trigger is None:
        if active:
            with _rec_lock:
                n = len(_rec.get("items") or []) + 1
                _rec.clear()
                _rec["active"] = False
            log.info("Problem cleared -- %d recorded snapshot(s) discarded", n)
        return
    if not active:
        _slow_refresh.set()
        snap = _snapshot("problem started")
        with _rec_lock:
            _rec.clear()
            _rec.update(active=True, trigger=trigger, started_at=time.time(), first=snap,
                        items=[], last_mono=now_mono, final=None)
        log.info("Recording details in case of a shutdown (%s)", _TRIGGER_WORDS[trigger])
        return
    if trigger != current:
        with _rec_lock:
            _rec["trigger"] = trigger
        log.info("Recording continues -- now %s", _TRIGGER_WORDS[trigger])
    every = SNAPSHOT_LOWV_EVERY_SECS if trigger == "low_voltage" else SNAPSHOT_EVERY_SECS
    if last is not None and now_mono - float(last) < every:
        return
    if trigger == "no_conn":
        _slow_refresh.set()
    snap = _snapshot("during countdown")
    with _rec_lock:
        items = _rec.setdefault("items", [])
        items.append(snap)
        del items[:-SNAPSHOT_KEEP]
        _rec["last_mono"] = now_mono


def _recorder_final(trigger: str) -> None:
    try:
        fast = _collect_fast()
        with _status_lock:
            _status["fast"] = fast
            _status["fast_at"] = time.time()
        if trigger != "low_voltage":
            slow = _collect_slow()
            with _status_lock:
                _status["slow"] = slow
                _status["slow_at"] = time.time()
    except Exception:
        log.exception("Couldn't refresh details for the final snapshot")
    snap = _snapshot("shutdown decided")
    with _rec_lock:
        if not _rec.get("active"):
            _rec.clear()
            _rec.update(active=True, trigger=trigger, started_at=time.time(), first=None, items=[])
        _rec["trigger"] = trigger
        _rec["final"] = snap
    log.info("Final snapshot taken before shutdown")


def _recording_public(full: bool = False) -> Optional[Dict[str, object]]:
    with _rec_lock:
        if not _rec.get("active"):
            return None
        items = list(_rec.get("items") or [])
        out: Dict[str, object] = {
            "trigger": _rec.get("trigger"),
            "started_at": _rec.get("started_at"),
            "count": len(items) + (1 if _rec.get("first") else 0) + (1 if _rec.get("final") else 0),
            "final": _rec.get("final") is not None,
        }
        if full:
            out["snapshots"] = ([_rec["first"]] if _rec.get("first") else []) + items + \
                               ([_rec["final"]] if _rec.get("final") else [])
    return out


_REPORT_NAME_RE = re.compile(r"^(shutdown|test|unclean)-\d{8}-\d{6}(-\d+)?\.json$")
_report_lock = threading.Lock()
_report_cache: Dict[str, Tuple[float, Dict[str, object]]] = {}
_KIND_WORDS = {"shutdown": "Shutdown", "test": "Test report", "unclean": "Unclean stop"}


def _durable_write(path: str, data: bytes, dir_mode: int = 0o700) -> None:
    folder = os.path.dirname(path)
    os.makedirs(folder, mode=dir_mode, exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        view = memoryview(data)
        while view:
            n = os.write(fd, view)
            view = view[n:]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    try:
        dfd = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def _report_files() -> List[str]:
    try:
        names = [n for n in os.listdir(REPORT_DIR) if _REPORT_NAME_RE.match(n)]
    except OSError:
        return []
    def mtime(n: str) -> float:
        try:
            return os.stat(os.path.join(REPORT_DIR, n)).st_mtime
        except OSError:
            return 0.0
    return sorted(names, key=lambda n: (mtime(n), n))


def _report_path(name: object) -> Optional[str]:
    if not isinstance(name, str) or not _REPORT_NAME_RE.match(name):
        return None
    return os.path.join(REPORT_DIR, name)


def _fit_report(report: Dict[str, object]) -> bytes:
    data = json.dumps(report, indent=1).encode("utf-8")
    while len(data) > REPORT_MAX_BYTES:
        diag = report.get("diagnostics") or {}
        snaps = report.get("snapshots") or []
        acts = report.get("activity") or []
        if diag:
            key = max(diag, key=lambda k: len(str(diag[k])))
            text = str(diag[key])
            if len(text) > 400:
                diag[key] = "...(shortened)\n" + text[-(len(text) // 2):]
            else:
                del diag[key]
        elif len(snaps) > 2:
            snaps.pop(1)
        elif acts:
            acts.pop(0)
        else:
            break
        report["trimmed"] = True
        data = json.dumps(report, indent=1).encode("utf-8")
    return data


def _save_report(report: Dict[str, object], name: Optional[str] = None) -> str:
    with _report_lock:
        if name is None:
            base = f"{report['kind']}-{time.strftime('%Y%m%d-%H%M%S', time.localtime(float(report['created_at'])))}"
            name, n = base + ".json", 1
            while os.path.exists(os.path.join(REPORT_DIR, name)):
                name, n = f"{base}-{n}.json", n + 1
        _durable_write(os.path.join(REPORT_DIR, name), _fit_report(report))
        for old in _report_files()[:-REPORT_KEEP]:
            try:
                os.remove(os.path.join(REPORT_DIR, old))
            except OSError:
                pass
    return name


def _build_report(kind: str, trigger: str, reason: str) -> Dict[str, object]:
    rec = _recording_public(full=True) or {}
    snaps = list(rec.get("snapshots") or [])
    if not snaps and kind == "test":
        snaps = [_snapshot("test (now)")]
    return {
        "format": 1,
        "kind": kind,
        "trigger": trigger,
        "reason": reason,
        "created_at": time.time(),
        "host": socket.gethostname(),
        "wifimon_version": APP_VERSION,
        "interface": INTERFACE,
        "problem_started_at": rec.get("started_at"),
        "settings": _settings_current(),
        "snapshots": snaps,
        "activity": _activity_since(0)["entries"],
        "health": _health_public(full=True),
        "diagnostics": {},
    }


def _diagnostics(budget: float) -> Dict[str, str]:
    deadline = time.monotonic() + budget
    nm = bool(shutil.which("nmcli"))
    cmds = [
        ("WiFi link", ["iw", "dev", INTERFACE, "link"]),
        ("Devices", ["nmcli", "-t", "device"] if nm else ["ip", "-br", "link"]),
        ("Addresses", ["ip", "addr", "show"]),
        ("Routes", ["ip", "route", "show"]),
        ("Radio blocks", ["rfkill", "list"]),
        ("NetworkManager log" if nm else "wpa_supplicant log",
         ["journalctl", "-u", "NetworkManager" if nm else "wpa_supplicant", "-n", "50",
          "--no-pager", "-o", "short-iso"]),
        ("Kernel messages", ["journalctl", "-k", "-n", "40", "--no-pager", "-o", "short-iso"]),
    ]
    out: Dict[str, str] = {}
    for label, cmd in cmds:
        left = deadline - time.monotonic()
        if left < 0.5:
            out[label] = "(skipped: out of time before power-off)"
            continue
        if not shutil.which(cmd[0]):
            continue
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                               timeout=min(5.0, left))
            text = (r.stdout or "") + (r.stderr or "")
        except subprocess.TimeoutExpired:
            text = "(timed out)"
        except OSError as e:
            text = f"({e})"
        out[label] = text[-8000:] if len(text) > 8000 else text
    return out


def _shutdown_report(reason: str, trigger: str) -> None:
    try:
        report = _build_report("shutdown", trigger, reason)
        name = _save_report(report)
        log.info("Shutdown report saved: %s/%s", REPORT_DIR, name)
        report["diagnostics"] = _diagnostics(5.0 if trigger == "low_voltage" else 10.0)
        report["activity"] = _activity_since(0)["entries"]
        _save_report(report, name)
    except Exception:
        log.exception("Couldn't save the shutdown report")


def _report_summary(name: str) -> Optional[Dict[str, object]]:
    path = os.path.join(REPORT_DIR, name)
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return None
    cached = _report_cache.get(name)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    summary = {
        "name": name, "kind": data.get("kind"), "trigger": data.get("trigger"),
        "reason": data.get("reason"), "created_at": data.get("created_at"),
        "size": os.path.getsize(path), "snapshots": len(data.get("snapshots") or []),
    }
    _report_cache[name] = (mtime, summary)
    return summary


def _reports_list() -> List[Dict[str, object]]:
    out = [s for s in (_report_summary(n) for n in reversed(_report_files())) if s]
    for stale in set(_report_cache) - {str(s["name"]) for s in out}:
        _report_cache.pop(stale, None)
    return out


def _reports_stamp() -> str:
    files = _report_files()
    return f"{len(files)}:{files[-1] if files else ''}"


def _last_report_banner() -> Optional[Dict[str, object]]:
    for s in _reports_list():
        if s["kind"] in ("shutdown", "unclean"):
            at = float(s.get("created_at") or 0)
            if at < _started_wall and time.time() - at < 7 * 86400:
                return s
            return None
    return None


def _fmt_time(t: object) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(t)))
    except (TypeError, ValueError):
        return "unknown"


def _report_text(r: Dict[str, object]) -> str:
    kind = _KIND_WORDS.get(str(r.get("kind")), str(r.get("kind")))
    lines = [f"wifimon {kind.lower()}", "=" * 40,
             f"Node:           {r.get('host')} ({r.get('interface')}), wifimon {r.get('wifimon_version')}",
             f"What happened:  {r.get('reason')}",
             f"Saved at:       {_fmt_time(r.get('created_at'))}"]
    if r.get("problem_started_at"):
        secs = float(r["created_at"]) - float(r["problem_started_at"])
        lines.append(f"Problem began:  {_fmt_time(r['problem_started_at'])} ({int(secs)} s before)")
    st = r.get("settings") or {}
    if st:
        lines.append("Limits:         no connection {no_conn_shutdown_secs} s, low voltage {low_voltage_shutdown_secs} s "
                     "below {low_voltage_threshold} V, internet check {ping_target}".format(**st))
    if r.get("previous_run"):
        pr = r["previous_run"]
        lines.append(f"Previous run:   started {_fmt_time(pr.get('started_at'))}, wifimon {pr.get('version')}")
    hl = r.get("health") or {}
    if hl:
        stalls = hl.get("chip_stalls")
        lines.append(f"WiFi today:     {hl.get('blips', 0)} brief blip(s), {hl.get('drops', 0)} drop(s), "
                     f"{'n/a' if stalls is None else stalls} WiFi chip stall(s)")
    if r.get("trimmed"):
        lines.append("Note:           this report was shortened to fit the size limit")
    snaps = r.get("snapshots") or []
    lines += ["", f"Timeline ({len(snaps)} snapshots)", "-" * 40,
              f"{'Time':<9} {'Network':<18} {'Signal':>8} {'IP address':<16} {'Internet':<10} {'Volts':>6} {'Temp':>6}  Note"]
    for sn in snaps:
        w, n, p = sn.get("wifi") or {}, sn.get("net") or {}, sn.get("power") or {}
        net = "yes" if n.get("internet") else ("router" if n.get("via") == "gateway" else "no")
        sig = f"{w['signal_dbm']:.0f} dBm" if isinstance(w.get("signal_dbm"), (int, float)) else "-"
        lines.append(f"{time.strftime('%H:%M:%S', time.localtime(sn.get('at', 0))):<9} "
                     f"{str(w.get('ssid') or '(none)')[:18]:<18} {sig:>8} {str(w.get('ip4') or '-'):<16} {net:<10} "
                     f"{str(p.get('volts') or '-'):>6} {str(sn.get('temp_c') or '-'):>6}  {sn.get('label', '')}")
    acts = r.get("activity") or []
    lines += ["", f"Activity log ({len(acts)} lines)", "-" * 40]
    for a in acts:
        lines.append(f"{time.strftime('%H:%M:%S', time.localtime(a.get('at', 0)))} {str(a.get('level')).upper():<8} {a.get('msg')}")
    chip = hl.get("chip_lines") or []
    if chip:
        lines += ["", f"Recent WiFi chip messages ({len(chip)})", "-" * 40]
        for c in chip:
            lines.append(f"{_fmt_time(c.get('at'))}  {c.get('text')}")
    for label, text in (r.get("diagnostics") or {}).items():
        lines += ["", f"--- {label} ---", str(text).rstrip()]
    lines += ["", "Full detail (every value of every snapshot) is in the JSON version of this report."]
    return "\n".join(lines) + "\n"


def _boot_id() -> str:
    return (_read_text("/proc/sys/kernel/random/boot_id") or "").strip()


def _marker_check_and_set() -> None:
    try:
        prev = json.loads(_read_text(RUN_MARKER) or "null")
    except ValueError:
        prev = None
    if isinstance(prev, dict):
        started = float(prev.get("started_at") or 0)
        explained = any(s["kind"] == "shutdown" and float(s.get("created_at") or 0) >= started
                        for s in _reports_list())
        if not explained:
            same_boot = bool(prev.get("boot_id")) and prev.get("boot_id") == _boot_id()
            if same_boot:
                reason = "wifimon stopped unexpectedly (crashed or was killed); the node kept running"
                cmd = ["journalctl", "-u", "wifimon", "-n", "40", "--no-pager", "-o", "short-iso"]
                label = "wifimon log (end)"
            else:
                reason = "The node lost power or restarted without a clean shutdown"
                cmd = ["journalctl", "-b", "-1", "-n", "60", "--no-pager", "-o", "short-iso"]
                label = "Previous boot log (end)"
            diag: Dict[str, str] = {}
            if shutil.which("journalctl"):
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=10)
                    text = (r.stdout or "") + (r.stderr or "")
                except (subprocess.SubprocessError, OSError) as e:
                    text = f"({e})"
                if not same_boot and ("No journal boot entry" in text or not text.strip()):
                    text = ("The system journal isn't kept across restarts on this node, so there is "
                            "no log from before the power loss.\n" + text)
                diag[label] = text[-8000:]
            report = {
                "format": 1, "kind": "unclean", "trigger": "unclean", "reason": reason,
                "created_at": time.time(), "host": socket.gethostname(), "wifimon_version": APP_VERSION,
                "interface": INTERFACE, "problem_started_at": None, "settings": _settings_current(),
                "previous_run": prev, "snapshots": [], "activity": [], "diagnostics": diag,
            }
            try:
                name = _save_report(report)
                log.warning("%s -- report saved: %s/%s", reason, REPORT_DIR, name)
            except OSError as e:
                log.warning("%s (couldn't save a report: %s)", reason, e)
    marker = {"started_at": _started_wall, "boot_id": _boot_id(), "pid": os.getpid(),
              "version": APP_VERSION}
    try:
        _durable_write(RUN_MARKER, json.dumps(marker).encode("utf-8"), dir_mode=0o755)
    except OSError as e:
        log.warning("Couldn't write %s: %s", RUN_MARKER, e)


def _marker_clear() -> None:
    try:
        os.remove(RUN_MARKER)
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("Couldn't remove %s: %s", RUN_MARKER, e)


_nm_sync_wanted = threading.Event()


def _mark_networks_changed() -> None:
    _networks_changed.set()
    _nm_sync_wanted.set()


def _sync_nm_priorities() -> None:
    if not shutil.which("nmcli"):
        return
    with _conf_lock:
        nets = _conf_networks()
    want: Dict[str, int] = {}
    for i, net in enumerate(nets):
        want.setdefault(str(net["ssid"]), len(nets) - i)
    changed = []
    for prof in _nm_wifi_profiles():
        target = want.get(str(prof["ssid"]))
        if target is None or prof.get("nm_priority") == target:
            continue
        ok, msg = _nmcli_ok(["connection", "modify", "uuid", str(prof["uuid"]),
                             "connection.autoconnect-priority", str(target)])
        if ok:
            changed.append(f"{prof['name']}={target}")
        else:
            log.warning("Couldn't set NetworkManager join order for %s: %s", prof["ssid"], msg)
    if changed:
        log.info("NetworkManager join order updated to match the reconnect list: %s",
                 ", ".join(changed))


def _nm_sync_loop() -> None:
    while not _shutdown_event.is_set():
        if not _nm_sync_wanted.wait(timeout=1.0):
            continue
        if _shutdown_event.wait(1.0):
            return
        _nm_sync_wanted.clear()
        try:
            _sync_nm_priorities()
        except Exception:
            log.exception("NetworkManager join-order sync failed")


def _nm_event(line: str) -> Optional[Tuple[int, str]]:
    line = line.strip()
    if not line:
        return None
    if line.startswith("Connectivity is now"):
        m = re.search(r"'(\w+)'", line)
        state = m.group(1) if m else ""
        return (logging.WARNING if state in ("portal", "limited", "none") else logging.INFO, line)
    if "primary connection" in line:
        return logging.INFO, line
    dev, sep, rest = line.partition(": ")
    if not sep or dev.startswith("p2p-dev-") or not (dev.startswith("wl") or dev == INTERFACE):
        return None
    rest = rest.strip()
    if rest.startswith("using connection"):
        return logging.INFO, line
    if rest == "connecting (need authentication)":
        return logging.INFO, f"{line} (password handshake)"
    if rest in ("connected", "disconnected"):
        return logging.INFO, line
    if rest in ("unavailable", "unmanaged", "device removed"):
        return logging.WARNING, line
    return None


_NM_EVENT_REPEAT_SECS = 10.0
_NM_EVENT_PER_MIN = 30
_nm_event_last: Dict[str, float] = {}
_nm_event_times: List[float] = []
_nm_monitor_proc: Optional[subprocess.Popen] = None


def _nm_event_log(line: str) -> None:
    global _auth_pending_since
    stripped = line.strip()
    if _dev_modes and stripped.startswith("wl") and ": " in stripped \
            and not stripped.startswith("p2p-dev-"):
        _devmode_wake.set()
    if KEEP_POWERSAVE_OFF and stripped == f"{INTERFACE}: connected":
        _ps_check.set()
    if stripped == f"{INTERFACE}: connecting (need authentication)":
        if _auth_pending_since is None:
            _auth_pending_since = time.monotonic()
    elif stripped.startswith(f"{INTERFACE}: connected"):
        _auth_pending_since = None
    event = _nm_event(line)
    if event is None:
        return
    level, text = event
    now = time.monotonic()
    if now - _nm_event_last.get(text, -1e9) < _NM_EVENT_REPEAT_SECS:
        return
    _nm_event_last[text] = now
    if len(_nm_event_last) > 200:
        for k in [k for k, t in _nm_event_last.items() if now - t > _NM_EVENT_REPEAT_SECS]:
            del _nm_event_last[k]
    _nm_event_times[:] = [t for t in _nm_event_times if now - t < 60]
    if len(_nm_event_times) >= _NM_EVENT_PER_MIN:
        if len(_nm_event_times) == _NM_EVENT_PER_MIN:
            _nm_event_times.append(now)
            log.warning("NetworkManager: too many events -- skipping more for a minute")
        return
    _nm_event_times.append(now)
    log.log(level, "NetworkManager: %s", text[:300])


def _nm_monitor_loop() -> None:
    global _nm_monitor_proc
    delay = 5
    while not _shutdown_event.is_set():
        nm = shutil.which("nmcli")
        if not nm:
            if _shutdown_event.wait(60):
                return
            continue
        started = time.monotonic()
        try:
            proc = subprocess.Popen([nm, "monitor"], stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                    errors="replace", bufsize=1,
                                    env=dict(os.environ, LC_ALL="C"))
        except OSError as e:
            log.warning("Couldn't start nmcli monitor: %s", e)
            proc = None
        if proc is not None:
            _nm_monitor_proc = proc
            try:
                for line in proc.stdout:
                    if _shutdown_event.is_set():
                        break
                    _nm_event_log(line)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                _nm_monitor_proc = None
        if _shutdown_event.is_set():
            return
        delay = 5 if time.monotonic() - started > 300 else min(delay * 2, 300)
        log.warning("nmcli monitor stopped -- restarting it in %d s", delay)
        if _shutdown_event.wait(delay):
            return


_NM_CONF_BODY = """# Written by wifimon ("Detect login pages" setting). wifimon owns this
# file: turning the setting off in wifimon removes it.
[connectivity]
enabled=true
uri=http://nmcheck.gnome.org/check_network_status.txt
interval=300
"""


def _apply_login_page_detection(enabled: bool) -> Optional[str]:
    try:
        current = _read_text(NM_CONF_FILE)
        if enabled:
            if current == _NM_CONF_BODY:
                return None
            conf_dir = os.path.dirname(NM_CONF_FILE)
            if not os.path.isdir(conf_dir):
                return f"Login-page detection needs NetworkManager ({conf_dir} not found)."
            tmp = NM_CONF_FILE + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            with os.fdopen(fd, "w") as f:
                f.write(_NM_CONF_BODY)
            os.replace(tmp, NM_CONF_FILE)
        else:
            if current is None:
                return None
            os.remove(NM_CONF_FILE)
    except OSError as e:
        log.warning("Couldn't update %s: %s", NM_CONF_FILE, e)
        return f"Couldn't update NetworkManager's settings: {e}"
    ok, msg = _nmcli_ok(["general", "reload", "conf"])
    log.info("Login-page detection turned %s", "on" if enabled else "off")
    if not ok:
        log.warning("nmcli general reload conf failed: %s", msg)
        return "NetworkManager will pick this up after its next restart."
    return None


_POWERSAVE_WORDS = {"default": 0, "ignore": 1, "disable": 2, "enable": 3}


def _powersave_code(value: str) -> Optional[int]:
    value = (value or "").strip().lower()
    m = re.match(r"(\d+)", value)
    if m:
        return int(m.group(1))
    for word, code in _POWERSAVE_WORDS.items():
        if word in value:
            return code
    return None


def _autojoin_off_ssids() -> set:
    if not shutil.which("nmcli"):
        return set()
    seen: Dict[str, bool] = {}
    for p in _nm_wifi_profiles():
        ssid = str(p["ssid"])
        seen[ssid] = seen.get(ssid, False) or bool(p.get("autoconnect", True))
    return {ssid for ssid, any_on in seen.items() if not any_on}


def _iw_power_save_off() -> bool:
    iw = shutil.which("iw")
    if not iw:
        return False
    try:
        r = subprocess.run([iw, "dev", INTERFACE, "set", "power_save", "off"],
                           capture_output=True, text=True, timeout=10)
    except (subprocess.SubprocessError, OSError):
        return False
    return r.returncode == 0


_NM_PS_CONF_BODY = """# Written by wifimon ("Keep WiFi power save off" setting). wifimon owns
# this file: turning the setting off in wifimon removes it.
[connection-wifimon-powersave]
wifi.powersave=2
"""
_ps_check = threading.Event()       # v5.18: "check the live power-save state soon"
_ps_warned_at = -1e9


def _apply_keep_powersave_off(enabled: bool) -> Optional[str]:
    note = None
    try:
        current = _read_text(NM_PS_CONF_FILE)
        changed = False
        if enabled and current != _NM_PS_CONF_BODY:
            conf_dir = os.path.dirname(NM_PS_CONF_FILE)
            if not os.path.isdir(conf_dir):
                note = f"Power save setting: NetworkManager not found ({conf_dir}); only the live WiFi is kept off."
            else:
                tmp = NM_PS_CONF_FILE + ".tmp"
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
                with os.fdopen(fd, "w") as f:
                    f.write(_NM_PS_CONF_BODY)
                os.replace(tmp, NM_PS_CONF_FILE)
                changed = True
        elif not enabled and current is not None:
            os.remove(NM_PS_CONF_FILE)
            changed = True
    except OSError as e:
        log.warning("Couldn't update %s: %s", NM_PS_CONF_FILE, e)
        return f"Couldn't update NetworkManager's settings: {e}"
    if changed:
        ok, msg = _nmcli_ok(["general", "reload", "conf"])
        log.info("Keep power save off turned %s", "on" if enabled else "off")
        if not ok:
            log.warning("nmcli general reload conf failed: %s", msg)
            note = "NetworkManager will pick up the power save default after its next restart."
    if enabled and shutil.which("nmcli"):
        fixed = 0
        for p in _nm_wifi_profiles():
            if p.get("powersave") in (1, 3):
                ok, msg = _nmcli_ok(["connection", "modify", "uuid", str(p["uuid"]),
                                     "802-11-wireless.powersave", "2"])
                if ok:
                    fixed += 1
                else:
                    log.warning("Couldn't turn power save off for %s: %s", p.get("ssid"), msg)
        if fixed:
            log.info("Power save turned off in %d saved network(s)", fixed)
    if enabled:
        _ps_check.set()
    return note


def _keep_powersave_check() -> None:
    global _ps_warned_at
    if not KEEP_POWERSAVE_OFF or _hotspot_active():
        return
    if _power_save() is not True:
        return
    if _iw_power_save_off() and _power_save() is not True:
        log.info("Power save had come back on — turned it off again")
        _slow_refresh.set()
        return
    now = time.monotonic()
    if now - _ps_warned_at >= 600:
        _ps_warned_at = now
        log.warning("Power save is on and couldn't be turned off (iw failed)")


def _no_internet_reason() -> str:
    if DETECT_LOGIN_PAGES and shutil.which("nmcli"):
        state = _run_text(["nmcli", "networking", "connectivity", "check"], timeout=20).strip()
        if state == "portal":
            return "it wants a login page, which the node can't fill in by itself"
        if state in ("limited", "none"):
            return f"joined, but no internet ({state})"
    return "joined, but the connection check didn't pass in time"


_OPTION_KEYS = ("ipv4.method", "ipv4.addresses", "ipv4.gateway", "ipv4.dns",
                "ipv4.ignore-auto-dns", "802-11-wireless.cloned-mac-address",
                "802-11-wireless.band", "802-11-wireless.mode")
WM_CONNECT_WAIT = 30
_OPTIONS_UNDO_SECS = 120
_has_5ghz_cache: Dict[str, Optional[bool]] = {}


def _has_5ghz() -> Optional[bool]:
    if INTERFACE in _has_5ghz_cache:
        return _has_5ghz_cache[INTERFACE]
    m = re.search(r"wiphy (\d+)", _run_text(["iw", "dev", INTERFACE, "info"]))
    result: Optional[bool] = None
    if m:
        info = _run_text(["iw", "phy", f"phy{m.group(1)}", "info"], timeout=10)
        if info:
            result = any(re.search(r"\b5\d{3}(\.\d+)? MHz", line) and "disabled" not in line
                         for line in info.splitlines())
    _has_5ghz_cache[INTERFACE] = result
    return result


def _split_list(value: str) -> List[str]:
    return [v for v in re.split(r"[,\s]+", value or "") if v]


def _options_public(prof: Dict[str, object]) -> Dict[str, object]:
    method = str(prof.get("ipv4.method") or "auto")
    ignore = str(prof.get("ipv4.ignore-auto-dns") or "no").lower() == "yes"
    dns = _split_list(str(prof.get("ipv4.dns") or ""))
    addrs = _split_list(str(prof.get("ipv4.addresses") or ""))
    if method == "manual":
        mode = "fixed"
    elif ignore and dns:
        mode = "auto_dns"
    else:
        mode = "auto"
    band = str(prof.get("802-11-wireless.band") or "")
    return {
        "ip_mode": mode,
        "address": addrs[0] if addrs else "",
        "gateway": str(prof.get("ipv4.gateway") or ""),
        "dns": dns,
        "real_mac": str(prof.get("802-11-wireless.cloned-mac-address") or "") == "permanent",
        "band": band if band in ("a", "bg") else "any",
    }


def _options_props(body: Dict[str, object]) -> Tuple[Optional[Dict[str, str]], str]:
    import ipaddress
    mode = body.get("ip_mode")
    if mode not in ("auto", "fixed", "auto_dns"):
        return None, "Pick how the address is set."
    dns_raw = body.get("dns") or []
    if isinstance(dns_raw, str):
        dns_raw = _split_list(dns_raw)
    if not isinstance(dns_raw, list) or len(dns_raw) > 3:
        return None, "Give up to three DNS servers."
    dns = []
    for d in dns_raw:
        try:
            dns.append(str(ipaddress.IPv4Address(str(d).strip())))
        except ValueError:
            return None, f"{d} isn't an IPv4 address."
    props: Dict[str, str] = {}
    if mode == "fixed":
        try:
            iface = ipaddress.IPv4Interface(str(body.get("address") or "").strip())
        except ValueError:
            return None, "Address must look like 192.168.1.50/24."
        if not 8 <= iface.network.prefixlen <= 30:
            return None, "The prefix (after the /) must be 8 to 30."
        if iface.ip in (iface.network.network_address, iface.network.broadcast_address):
            return None, "That address is the network's own or broadcast address."
        try:
            gw = ipaddress.IPv4Address(str(body.get("gateway") or "").strip())
        except ValueError:
            return None, "Gateway must look like 192.168.1.1."
        if gw not in iface.network or gw == iface.ip:
            return None, f"The gateway must be another address inside {iface.network}."
        if not dns:
            dns = [str(gw)]
        props.update({"ipv4.method": "manual", "ipv4.addresses": str(iface),
                      "ipv4.gateway": str(gw), "ipv4.dns": ",".join(dns), "ipv4.ignore-auto-dns": "no"})
    elif mode == "auto_dns":
        if not dns:
            return None, "Give at least one DNS server."
        props.update({"ipv4.method": "auto", "ipv4.addresses": "", "ipv4.gateway": "",
                      "ipv4.dns": ",".join(dns), "ipv4.ignore-auto-dns": "yes"})
    else:
        props.update({"ipv4.method": "auto", "ipv4.addresses": "", "ipv4.gateway": "",
                      "ipv4.dns": "", "ipv4.ignore-auto-dns": "no"})
    props["802-11-wireless.cloned-mac-address"] = "permanent" if body.get("real_mac") is True else ""
    band = body.get("band", "any")
    if band not in ("any", "bg", "a"):
        return None, "Pick a band."
    if band == "a" and _has_5ghz() is False:
        return None, "This WiFi device can't use 5 GHz."
    props["802-11-wireless.band"] = "" if band == "any" else str(band)
    return props, ""


def _norm_opt(key: str, value: object) -> str:
    v = str(value or "").strip()
    if key == "ipv4.dns":
        return ",".join(_split_list(v))
    if key == "ipv4.addresses":
        return ",".join(_split_list(v))
    if key == "ipv4.ignore-auto-dns":
        return "yes" if v.lower() == "yes" else "no"
    if key == "ipv4.method":
        return v or "auto"
    return "" if v == "--" else v


def _changed_options(prof: Dict[str, object], props: Dict[str, str]) -> Dict[str, str]:
    return {k: v for k, v in props.items() if _norm_opt(k, prof.get(k)) != _norm_opt(k, v)}


def _nm_active_uuid() -> Optional[str]:
    for line in _run_text(["nmcli", "-t", "-f", "UUID,DEVICE", "connection", "show", "--active"]).splitlines():
        f = _nmcli_split(line)
        if len(f) >= 2 and f[1] == INTERFACE:
            return f[0]
    return None


def _copy_nm_options(old: Dict[str, object], new_uuid: str) -> List[str]:
    props = {k: _norm_opt(k, old.get(k)) for k in _OPTION_KEYS}
    props = {k: v for k, v in props.items()
             if v and not (k == "ipv4.method" and v == "auto") and not (k == "ipv4.ignore-auto-dns" and v == "no")}
    if not props:
        return []
    args = ["connection", "modify", "uuid", new_uuid]
    for k, v in props.items():
        args += [k, v]
    ok, msg = _nmcli_ok(args)
    return [] if ok else [f"couldn't carry the network options over: {msg}"]


_COUNTRY_LIST = """AD Andorra|AE United Arab Emirates|AF Afghanistan|AG Antigua and Barbuda|AI Anguilla|AL Albania|AM Armenia|AO Angola|AQ Antarctica|AR Argentina|AS American Samoa|AT Austria|AU Australia|AW Aruba|AX Åland Islands|AZ Azerbaijan|BA Bosnia and Herzegovina|BB Barbados|BD Bangladesh|BE Belgium|BF Burkina Faso|BG Bulgaria|BH Bahrain|BI Burundi|BJ Benin|BL Saint Barthélemy|BM Bermuda|BN Brunei|BO Bolivia|BQ Caribbean Netherlands|BR Brazil|BS Bahamas|BT Bhutan|BV Bouvet Island|BW Botswana|BY Belarus|BZ Belize|CA Canada|CC Cocos (Keeling) Islands|CD Congo (DRC)|CF Central African Republic|CG Congo (Republic)|CH Switzerland|CI Côte d'Ivoire|CK Cook Islands|CL Chile|CM Cameroon|CN China|CO Colombia|CR Costa Rica|CU Cuba|CV Cabo Verde|CW Curaçao|CX Christmas Island|CY Cyprus|CZ Czechia|DE Germany|DJ Djibouti|DK Denmark|DM Dominica|DO Dominican Republic|DZ Algeria|EC Ecuador|EE Estonia|EG Egypt|EH Western Sahara|ER Eritrea|ES Spain|ET Ethiopia|FI Finland|FJ Fiji|FK Falkland Islands|FM Micronesia|FO Faroe Islands|FR France|GA Gabon|GB United Kingdom|GD Grenada|GE Georgia|GF French Guiana|GG Guernsey|GH Ghana|GI Gibraltar|GL Greenland|GM Gambia|GN Guinea|GP Guadeloupe|GQ Equatorial Guinea|GR Greece|GS South Georgia and the South Sandwich Islands|GT Guatemala|GU Guam|GW Guinea-Bissau|GY Guyana|HK Hong Kong|HM Heard Island and McDonald Islands|HN Honduras|HR Croatia|HT Haiti|HU Hungary|ID Indonesia|IE Ireland|IL Israel|IM Isle of Man|IN India|IO British Indian Ocean Territory|IQ Iraq|IR Iran|IS Iceland|IT Italy|JE Jersey|JM Jamaica|JO Jordan|JP Japan|KE Kenya|KG Kyrgyzstan|KH Cambodia|KI Kiribati|KM Comoros|KN Saint Kitts and Nevis|KP North Korea|KR South Korea|KW Kuwait|KY Cayman Islands|KZ Kazakhstan|LA Laos|LB Lebanon|LC Saint Lucia|LI Liechtenstein|LK Sri Lanka|LR Liberia|LS Lesotho|LT Lithuania|LU Luxembourg|LV Latvia|LY Libya|MA Morocco|MC Monaco|MD Moldova|ME Montenegro|MF Saint Martin|MG Madagascar|MH Marshall Islands|MK North Macedonia|ML Mali|MM Myanmar|MN Mongolia|MO Macao|MP Northern Mariana Islands|MQ Martinique|MR Mauritania|MS Montserrat|MT Malta|MU Mauritius|MV Maldives|MW Malawi|MX Mexico|MY Malaysia|MZ Mozambique|NA Namibia|NC New Caledonia|NE Niger|NF Norfolk Island|NG Nigeria|NI Nicaragua|NL Netherlands|NO Norway|NP Nepal|NR Nauru|NU Niue|NZ New Zealand|OM Oman|PA Panama|PE Peru|PF French Polynesia|PG Papua New Guinea|PH Philippines|PK Pakistan|PL Poland|PM Saint Pierre and Miquelon|PN Pitcairn Islands|PR Puerto Rico|PS Palestine|PT Portugal|PW Palau|PY Paraguay|QA Qatar|RE Réunion|RO Romania|RS Serbia|RU Russia|RW Rwanda|SA Saudi Arabia|SB Solomon Islands|SC Seychelles|SD Sudan|SE Sweden|SG Singapore|SH Saint Helena|SI Slovenia|SJ Svalbard and Jan Mayen|SK Slovakia|SL Sierra Leone|SM San Marino|SN Senegal|SO Somalia|SR Suriname|SS South Sudan|ST São Tomé and Príncipe|SV El Salvador|SX Sint Maarten|SY Syria|SZ Eswatini|TC Turks and Caicos Islands|TD Chad|TF French Southern Territories|TG Togo|TH Thailand|TJ Tajikistan|TK Tokelau|TL Timor-Leste|TM Turkmenistan|TN Tunisia|TO Tonga|TR Türkiye|TT Trinidad and Tobago|TV Tuvalu|TW Taiwan|TZ Tanzania|UA Ukraine|UG Uganda|UM U.S. Minor Outlying Islands|US United States|UY Uruguay|UZ Uzbekistan|VA Vatican City|VC Saint Vincent and the Grenadines|VE Venezuela|VG British Virgin Islands|VI U.S. Virgin Islands|VN Vietnam|VU Vanuatu|WF Wallis and Futuna|WS Samoa|YE Yemen|YT Mayotte|ZA South Africa|ZM Zambia|ZW Zimbabwe"""
COUNTRIES: Dict[str, str] = {e[:2]: e[3:] for e in _COUNTRY_LIST.split("|")}


def _nmcli_free_run(cmd: List[str], timeout: float = 30) -> Tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"{cmd[0]} timed out"
    except OSError as e:
        return False, _log_safe(e)
    return r.returncode == 0, _log_safe(((r.stderr or r.stdout) or "").strip()[:300])


def _country_now() -> Optional[str]:
    m = re.search(r"^country\s+([A-Z0-9]{2}):", _run_text(["iw", "reg", "get"]), re.M)
    return m.group(1) if m else None


def _write_if_changed(path: str, body: str, mode: int = 0o644) -> None:
    if _read_text(path) == body:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w") as f:
        f.write(body)
    os.replace(tmp, path)


def _country_apply(code: str) -> Tuple[bool, str, Optional[str]]:
    if shutil.which("raspi-config"):
        ok, msg = _nmcli_free_run(["raspi-config", "nonint", "do_wifi_country", code], timeout=60)
        if not ok:
            return False, msg or "raspi-config failed", _country_now()
    else:
        ok, msg = _nmcli_free_run(["iw", "reg", "set", code])
        if not ok:
            return False, msg or "iw reg set failed", _country_now()
        try:
            _write_if_changed(COUNTRY_MODPROBE, "# Written by wifimon (WiFi country code). Used at boot.\n"
                                                f"options cfg80211 ieee80211_regdom={code}\n")
        except OSError as e:
            return False, f"set for now, but couldn't save it for the next boot: {e}", _country_now()
    if _wifi_backend() == "wpa_cli":
        for conf in WPA_CONFS:
            txt = _read_text(conf)
            if txt is None:
                continue
            if re.search(r"^country=", txt, re.M):
                new = re.sub(r"^country=.*$", f"country={code}", txt, count=1, flags=re.M)
            else:
                new = f"country={code}\n" + txt
            try:
                _write_if_changed(conf, new, 0o600)
            except OSError as e:
                log.warning("Couldn't update %s: %s", conf, e)
    time.sleep(1)
    return True, "", _country_now()


HOTSPOT_FILE = os.path.join(SHUTDOWN_STATE_DIR, "hotspot.json")
COUNTRY_MODPROBE = "/etc/modprobe.d/wifimon-country.conf"
WPA_CONFS = ("/etc/wpa_supplicant/wpa_supplicant.conf", "/etc/wpa_supplicant/wpa_supplicant-wlan0.conf")
_hotspot: Dict[str, object] = {}
_hotspot_lock = threading.Lock()


def _hotspot_active() -> bool:
    with _hotspot_lock:
        return bool(_hotspot.get("active"))


def _hotspot_ready() -> Tuple[bool, str]:
    if not shutil.which("nmcli"):
        return False, "The hotspot needs NetworkManager (nmcli)."
    if not (shutil.which("dnsmasq") or os.path.exists("/usr/sbin/dnsmasq")):
        return False, "The hotspot needs dnsmasq to hand out addresses (sudo apt install dnsmasq-base)."
    return True, ""


def _hotspot_public() -> Dict[str, object]:
    ok, why = _hotspot_ready()
    with _hotspot_lock:
        h = dict(_hotspot)
    out: Dict[str, object] = {"available": ok, "why": why, "active": bool(h.get("active")),
                              "default_name": f"{socket.gethostname()}-setup"[:32]}
    if h.get("active"):
        out.update(ssid=h.get("ssid"), previous=h.get("previous"), address=h.get("address"),
                   remaining=max(0.0, float(h["stop_at"]) - time.monotonic()),
                   minutes=h.get("minutes"))
    return out


def _hotspot_profiles() -> List[str]:
    uuids = []
    for line in _run_text(["nmcli", "-t", "-f", "UUID,NAME,TYPE", "connection", "show"]).splitlines():
        f = _nmcli_split(line)
        if len(f) >= 3 and f[2] == "802-11-wireless" and f[1] == "wifimon-hotspot":
            uuids.append(f[0])
    return uuids


def _hotspot_persist() -> None:
    try:
        with _hotspot_lock:
            h = dict(_hotspot)
        if not h.get("active"):
            os.remove(HOTSPOT_FILE)
            return
        os.makedirs(SHUTDOWN_STATE_DIR, exist_ok=True)
        tmp = HOTSPOT_FILE + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({k: h.get(k) for k in ("uuid", "ssid", "previous")}, f)
        os.replace(tmp, HOTSPOT_FILE)
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("Couldn't update %s: %s", HOTSPOT_FILE, e)


def _hotspot_keyfile(ssid: str, password: str) -> Tuple[bool, str]:
    if not os.path.isdir(NM_CONN_DIR):
        return False, f"{NM_CONN_DIR} not found"
    for u in _hotspot_profiles():
        _nmcli_ok(["connection", "delete", "uuid", u])
    con_uuid = str(uuid.uuid4())
    path = os.path.join(NM_CONN_DIR, f"wifimon-hotspot-{con_uuid[:8]}.nmconnection")
    lines = ["[connection]", "id=wifimon-hotspot", f"uuid={con_uuid}", "type=wifi",
             "autoconnect=false", f"interface-name={INTERFACE}", "",
             "[wifi]", "mode=ap", "band=bg",
             "ssid=" + ";".join(str(b) for b in ssid.encode("utf-8")) + ";", "",
             "[wifi-security]", "key-mgmt=wpa-psk", "proto=rsn", "pairwise=ccmp", "group=ccmp",
             f"psk={_keyfile_escape(password)}", "",
             "[ipv4]", "method=shared", "", "[ipv6]", "method=ignore", ""]
    try:
        fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        os.replace(path + ".tmp", path)
    except OSError as e:
        return False, f"couldn't write the hotspot profile: {e}"
    ok, msg = _nmcli_ok(["connection", "load", path])
    if not ok:
        try:
            os.remove(path)
        except OSError:
            pass
        return False, msg or "NetworkManager couldn't load the hotspot profile"
    return True, con_uuid


def _hotspot_timer(token: str) -> None:
    while not _shutdown_event.wait(1.0):
        with _hotspot_lock:
            if not _hotspot.get("active") or _hotspot.get("token") != token:
                return
            due = time.monotonic() >= float(_hotspot["stop_at"])
        if due:
            if not _action_lock.acquire(timeout=5):
                continue
            log.info("Hotspot auto-stop time reached")
            _hotspot_stop(None, "auto-stop")
            return


def _hotspot_stop(connect_to: Optional[str], why: str) -> str:
    with _hotspot_lock:
        h = dict(_hotspot)
        _hotspot.clear()
    _hotspot_persist()
    if h.get("uuid"):
        _nmcli_ok(["connection", "down", "uuid", str(h["uuid"])])
    log.info("Hotspot stopped (%s)", why)
    target = connect_to or h.get("previous")
    if target and (_profiles_for(str(target)) or any(n["ssid"] == target for n in _conf_networks())):
        _start_connect_job(str(target), kind="return")
        return f"Hotspot stopped. Connecting to {target}…"
    _action_lock.release()
    _grace_clear()
    return "Hotspot stopped. The watchdog will reconnect to a known network."


def _hotspot_recover() -> None:
    txt = _read_text(HOTSPOT_FILE)
    if not txt:
        return
    try:
        data = json.loads(txt)
    except ValueError:
        data = {}
    if data.get("uuid"):
        _nmcli_ok(["connection", "down", "uuid", str(data["uuid"])])
    try:
        os.remove(HOTSPOT_FILE)
    except OSError:
        pass
    log.warning("A hotspot was still on when wifimon stopped -- it has been taken down")


_PAM_SERVICE = "wifimon"
_PAM_PROMPT_ECHO_OFF = 1
_PAM_BUF_ERR = 5
_crypt_lock = threading.Lock()


def _load_lib(name: str, fallback: str) -> Optional[ctypes.CDLL]:
    path = ctypes.util.find_library(name) or fallback
    try:
        return ctypes.CDLL(path)
    except OSError:
        return None


def _pam_authenticate(user: str, password: str) -> Optional[bool]:
    libpam = _load_lib("pam", "libpam.so.0")
    libc = _load_lib("c", "libc.so.6")
    if libpam is None or libc is None:
        return None

    class PamHandle(ctypes.Structure):
        _fields_ = [("handle", ctypes.c_void_p)]

    class PamMessage(ctypes.Structure):
        _fields_ = [("msg_style", ctypes.c_int), ("msg", ctypes.c_char_p)]

    class PamResponse(ctypes.Structure):
        _fields_ = [("resp", ctypes.c_void_p), ("resp_retcode", ctypes.c_int)]

    conv_t = ctypes.CFUNCTYPE(
        ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.POINTER(PamMessage)),
        ctypes.POINTER(ctypes.POINTER(PamResponse)),
        ctypes.c_void_p,
    )

    class PamConv(ctypes.Structure):
        _fields_ = [("conv", conv_t), ("appdata_ptr", ctypes.c_void_p)]

    calloc = libc.calloc
    calloc.restype = ctypes.c_void_p
    calloc.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
    pw = password.encode("utf-8")

    def _conv(n, msgs, resp, _appdata):
        addr = calloc(n, ctypes.sizeof(PamResponse))
        if not addr:
            return _PAM_BUF_ERR
        resp[0] = ctypes.cast(addr, ctypes.POINTER(PamResponse))
        for i in range(n):
            if msgs[i].contents.msg_style == _PAM_PROMPT_ECHO_OFF:
                buf = calloc(len(pw) + 1, 1)
                if not buf:
                    return _PAM_BUF_ERR
                ctypes.memmove(buf, pw, len(pw))
                resp[0][i].resp = buf
                resp[0][i].resp_retcode = 0
        return 0

    conv_cb = conv_t(_conv)
    conv = PamConv(conv_cb, None)
    handle = PamHandle()

    pam_start = libpam.pam_start
    pam_start.restype = ctypes.c_int
    pam_start.argtypes = [ctypes.c_char_p, ctypes.c_char_p,
                          ctypes.POINTER(PamConv), ctypes.POINTER(PamHandle)]
    pam_authenticate = libpam.pam_authenticate
    pam_authenticate.restype = ctypes.c_int
    pam_authenticate.argtypes = [PamHandle, ctypes.c_int]
    pam_end = libpam.pam_end
    pam_end.restype = ctypes.c_int
    pam_end.argtypes = [PamHandle, ctypes.c_int]

    rc = pam_start(_PAM_SERVICE.encode(), user.encode(), ctypes.byref(conv), ctypes.byref(handle))
    if rc != 0:
        return None
    try:
        rc = pam_authenticate(handle, 0)
    finally:
        pam_end(handle, rc)
    return rc == 0


def _shadow_authenticate(user: str, password: str) -> Optional[bool]:
    txt = _read_text("/etc/shadow")
    if txt is None:
        return None
    stored = None
    for line in txt.splitlines():
        parts = line.split(":")
        if len(parts) > 1 and parts[0] == user:
            stored = parts[1]
            break
    if not stored or stored[0] in "!*":
        return False
    libcrypt = _load_lib("crypt", "libcrypt.so.1")
    if libcrypt is None:
        return None
    crypt_fn = libcrypt.crypt
    crypt_fn.restype = ctypes.c_char_p
    crypt_fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    with _crypt_lock:
        out = crypt_fn(password.encode("utf-8"), stored.encode("utf-8"))
    if not out:
        return False
    return hmac.compare_digest(out, stored.encode("utf-8"))


def _verify_root_password(password: str) -> bool:
    if not password:
        return False
    result = _pam_authenticate("root", password)
    if result is None:
        result = _shadow_authenticate("root", password)
    return bool(result)


def _root_password_status() -> str:
    txt = _read_text("/etc/shadow")
    if txt is None:
        return "unknown"
    for line in txt.splitlines():
        parts = line.split(":")
        if parts and parts[0] == "root":
            stored = parts[1] if len(parts) > 1 else ""
            return "none" if (not stored or stored[0] in "!*") else "set"
    return "unknown"


_COOKIE_NAME = "wifimon_session"
_MAX_SESSIONS = 50
_sessions_lock = threading.Lock()
_sessions: Dict[str, float] = {}


def _session_new() -> str:
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _sessions_lock:
        for t in [t for t, exp in _sessions.items() if exp <= now]:
            del _sessions[t]
        while len(_sessions) >= _MAX_SESSIONS:
            del _sessions[min(_sessions, key=_sessions.get)]
        _sessions[token] = now + SESSION_TTL_SECS
    return token


def _session_touch(token: str) -> bool:
    now = time.monotonic()
    with _sessions_lock:
        exp = _sessions.get(token)
        if exp is None:
            return False
        if exp <= now:
            del _sessions[token]
            return False
        _sessions[token] = now + SESSION_TTL_SECS
        return True


def _session_drop(token: str) -> None:
    with _sessions_lock:
        _sessions.pop(token, None)


def _cookie_header(token: str, max_age: int) -> str:
    parts = [f"{_COOKIE_NAME}={token}", "Path=/", "HttpOnly", "SameSite=Strict",
             f"Max-Age={max_age}"]
    if _service_info.get("tls"):
        parts.append("Secure")
    return "; ".join(parts)


_AUTH_LOCK_AFTER = 5
_AUTH_LOCK_BASE = 5.0
_AUTH_LOCK_CAP = 300.0
_AUTH_TRACK_MAX = 1000
_auth_lock = threading.Lock()
_auth_failures: Dict[str, List[float]] = {}


def _lockout_remaining(ip: str) -> float:
    with _auth_lock:
        rec = _auth_failures.get(ip)
        if not rec:
            return 0.0
        return max(0.0, rec[1] - time.monotonic())


def _auth_record_failure(ip: str) -> None:
    now = time.monotonic()
    with _auth_lock:
        if ip not in _auth_failures and len(_auth_failures) >= _AUTH_TRACK_MAX:
            del _auth_failures[min(_auth_failures, key=lambda k: _auth_failures[k][1])]
        rec = _auth_failures.setdefault(ip, [0, 0.0])
        rec[0] += 1
        if rec[0] >= _AUTH_LOCK_AFTER:
            delay = min(_AUTH_LOCK_CAP, _AUTH_LOCK_BASE * (2 ** (rec[0] - _AUTH_LOCK_AFTER)))
            rec[1] = now + delay


def _auth_record_success(ip: str) -> None:
    with _auth_lock:
        _auth_failures.pop(ip, None)


_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,62}$")


def _ensure_tls_cert() -> bool:
    if os.path.exists(TLS_CERT) and os.path.exists(TLS_KEY):
        return True
    openssl = shutil.which("openssl")
    if not openssl:
        log.warning("openssl not found — can't create the dashboard's HTTPS certificate")
        return False
    host = socket.gethostname()
    if not _HOSTNAME_RE.match(host):
        host = "wifimon"
    try:
        os.makedirs(TLS_DIR, mode=0o700, exist_ok=True)
        os.chmod(TLS_DIR, 0o700)
    except OSError as e:
        log.warning("Can't create %s: %s", TLS_DIR, e)
        return False
    key_tmp, cert_tmp = TLS_KEY + ".tmp", TLS_CERT + ".tmp"
    cmd = [openssl, "req", "-x509", "-newkey", "ec",
           "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
           "-keyout", key_tmp, "-out", cert_tmp, "-days", "3650",
           "-subj", f"/CN={host}",
           "-addext", f"subjectAltName=DNS:{host},DNS:{host}.local"]
    old_umask = os.umask(0o077)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (subprocess.SubprocessError, OSError) as e:
        log.warning("openssl failed: %s", e)
        return False
    finally:
        os.umask(old_umask)
    if r.returncode != 0 or not (os.path.exists(key_tmp) and os.path.exists(cert_tmp)):
        log.warning("openssl failed: %s", _log_safe(r.stderr.strip()[:300]))
        for p in (key_tmp, cert_tmp):
            try:
                os.remove(p)
            except OSError:
                pass
        return False
    os.chmod(key_tmp, 0o600)
    os.chmod(cert_tmp, 0o644)
    os.replace(key_tmp, TLS_KEY)
    os.replace(cert_tmp, TLS_CERT)
    log.info("Created self-signed HTTPS certificate for %s in %s", host, TLS_DIR)
    return True


def _make_ssl_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(TLS_CERT, TLS_KEY)
    return ctx


_MAX_BODY = 16 * 1024
_LOG_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

_SECURITY_HEADERS = (
    ("X-Frame-Options", "DENY"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Content-Security-Policy",
     "default-src 'self'; script-src 'self' 'unsafe-inline'; "
     "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
     "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"),
)


def _log_safe(text: object) -> str:
    return _LOG_CONTROL_RE.sub(" ", str(text))


class _Handler(BaseHTTPRequestHandler):
    server_version = "wifimon"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = 30
    _refresh_cookie: Optional[str] = None
    _defer = False
    _deferred: Optional[Tuple[int, object, Optional[List[Tuple[str, str]]]]] = None

    def log_message(self, fmt: str, *args: object) -> None:
        log.debug("http %s %s", self.client_address[0], _log_safe(fmt % args))

    def end_headers(self) -> None:
        for name, value in _SECURITY_HEADERS:
            self.send_header(name, value)
        super().end_headers()

    def _send(self, status: int, body: bytes, ctype: str,
              extra: Optional[List[Tuple[str, str]]] = None) -> None:
        extra = extra or []
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in extra:
            self.send_header(name, value)
        if self.close_connection:
            self.send_header("Connection", "close")
        if self._refresh_cookie and not any(n.lower() == "set-cookie" for n, _ in extra):
            self.send_header("Set-Cookie", self._refresh_cookie)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj: object,
              extra: Optional[List[Tuple[str, str]]] = None) -> None:
        if self._defer:
            self._deferred = (status, obj, extra)
            return
        if status in (400, 413):
            self.close_connection = True
        self._send(status, json.dumps(obj).encode("utf-8"),
                   "application/json; charset=utf-8", extra)

    def _session_token(self) -> Optional[str]:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        jar = http.cookies.SimpleCookie()
        try:
            jar.load(raw)
        except http.cookies.CookieError:
            return None
        morsel = jar.get(_COOKIE_NAME)
        return morsel.value if morsel and morsel.value else None

    def _authed(self) -> bool:
        token = self._session_token()
        if token and _session_touch(token):
            self._refresh_cookie = _cookie_header(token, SESSION_TTL_SECS)
            return True
        return False

    def _csrf_ok(self) -> bool:
        if self.headers.get("X-Requested-With") != "XMLHttpRequest":
            return False
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return False
        origin = self.headers.get("Origin")
        if origin:
            host = (self.headers.get("Host") or "").lower()
            if urlsplit(origin).netloc.lower() != host:
                return False
        return True

    def do_GET(self) -> None:
        self._refresh_cookie = None
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, _page_bytes(), "text/html; charset=utf-8")
        elif path == "/api/whoami":
            self._json(200, {"auth": self._authed(), "version": APP_VERSION})
        elif path == "/api/status":
            if not self._authed():
                self._json(401, {"error": "Log in first."})
                return
            status = _build_status()
            status["client"] = self._client_path()
            self._json(200, status)
        elif path == "/api/countries":
            self._json(200, {"countries": COUNTRIES})
        elif path in ("/api/reports", "/api/report"):
            if not self._authed():
                self._json(401, {"error": "Log in first."})
                return
            self._get_reports(path)
        elif path == "/api/snapshots":
            if not self._authed():
                self._json(401, {"error": "Log in first."})
                return
            self._json(200, {"recording": _recording_public(full=True)})
        elif path == "/api/log":
            if not self._authed():
                self._json(401, {"error": "Log in first."})
                return
            query = dict(p.split("=", 1) for p in urlsplit(self.path).query.split("&") if "=" in p)
            after = _to_int(query.get("after")) or 0
            self._json(200, _activity_since(max(0, after)))
        else:
            self._json(404, {"error": "Not found."})

    def _get_reports(self, path: str) -> None:
        if path == "/api/reports":
            self._json(200, {"reports": _reports_list(), "keep": REPORT_KEEP, "dir": REPORT_DIR})
            return
        query = dict(p.split("=", 1) for p in urlsplit(self.path).query.split("&") if "=" in p)
        name = urllib_unquote(query.get("name", ""))
        rpath = _report_path(name)
        if rpath is None or not os.path.isfile(rpath):
            self._json(404, {"error": "No such report."})
            return
        try:
            with open(rpath, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            self._json(500, {"error": "That report can't be read."})
            return
        if query.get("format") == "json":
            self._json(200, data)
            return
        extra = []
        if query.get("download") == "1":
            extra.append(("Content-Disposition", f'attachment; filename="wifimon-{name[:-5]}.txt"'))
        self._send(200, _report_text(data).encode("utf-8"), "text/plain; charset=utf-8", extra)

    def _client_path(self) -> Dict[str, object]:
        try:
            local = self.connection.getsockname()[0]
        except OSError:
            local = None
        with _status_lock:
            ipmap = dict(_status["slow"].get("ipmap") or {})
            wifi_names = {d.get("device") for d in (_status["slow"].get("devices") or [])}
        iface = ipmap.get(local) if local else None
        return {"local_ip": local, "via_iface": iface, "via_wifi": iface in wifi_names}

    def do_POST(self) -> None:
        self._refresh_cookie = None
        self._defer, self._deferred = False, None
        path = urlsplit(self.path).path
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > _MAX_BODY:
            self.close_connection = True
            self._json(413, {"error": "Request too large."})
            return
        raw = self.rfile.read(length) if length else b""

        if not self._csrf_ok():
            self._json(403, {"error": "Blocked: this request didn't come from the dashboard page."})
            return
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, ValueError):
            body = None
        if not isinstance(body, dict):
            self._json(400, {"error": "Bad request body."})
            return

        if path == "/api/login":
            self._handle_login(body)
        elif path == "/api/logout":
            self._handle_logout()
        elif not self._authed():
            self._json(401, {"error": "Log in first."})
        elif path == "/api/service/restart":
            self._handle_restart(body)
        elif path == "/api/radio":
            self._handle_radio(body)
        elif path == "/api/device/disconnect":
            self._handle_disconnect(body)
        elif path == "/api/device/switch":
            self._handle_switch(body)
        elif path == "/api/device/mode":
            self._handle_devmode(body)
        elif path == "/api/device/forget":
            self._handle_devforget(body)
        elif path == "/api/change/keep":
            self._handle_keep(body)
        elif path == "/api/change/undo":
            self._handle_undo(body)
        elif path == "/api/scan":
            self._handle_scan(body)
        elif path == "/api/network/connect":
            self._handle_net_connect(body)
        elif path == "/api/network/add":
            self._handle_net_add(body)
        elif path == "/api/network/delete":
            self._handle_net_delete(body)
        elif path == "/api/network/password":
            self._handle_net_password(body)
        elif path == "/api/network/move":
            self._handle_net_move(body)
        elif path == "/api/network/track":
            self._handle_net_track(body)
        elif path == "/api/network/untrack":
            self._handle_net_untrack(body)
        elif path == "/api/network/edit":
            self._handle_net_edit(body)
        elif path == "/api/network/reconnect":
            self._handle_reconnect(body)
        elif path == "/api/powersave":
            self._handle_powersave(body)
        elif path == "/api/country":
            self._handle_country(body)
        elif path == "/api/roaming":
            self._handle_roaming(body)
        elif path == "/api/hotspot/start":
            self._handle_hotspot_start(body)
        elif path == "/api/hotspot/stop":
            self._handle_hotspot_stop(body)
        elif path == "/api/network/options":
            self._handle_options(body)
        elif path == "/api/network/autojoin":
            self._handle_autojoin(body)
        elif path == "/api/reports/delete":
            self._handle_report_delete(body)
        elif path == "/api/reports/test":
            self._handle_report_test(body)
        elif path == "/api/settings":
            self._handle_settings(body)
        elif path == "/api/settings/reset":
            self._handle_settings_reset(body)
        else:
            self._json(404, {"error": "Not found."})

    def _handle_login(self, body: Dict[str, object]) -> None:
        ip = self.client_address[0]
        wait = _lockout_remaining(ip)
        if wait > 0:
            secs = int(wait) + 1
            self._json(429, {"error": f"Too many wrong passwords. Try again in {secs} s.",
                             "retry_after": secs}, [("Retry-After", str(secs))])
            return
        password = body.get("password")
        if not isinstance(password, str) or not password or len(password) > 1024:
            self._json(400, {"error": "Enter the root password."})
            return
        if _verify_root_password(password):
            _auth_record_success(ip)
            token = _session_new()
            log.info("Dashboard login from %s", ip)
            self._json(200, {"ok": True},
                       [("Set-Cookie", _cookie_header(token, SESSION_TTL_SECS))])
        else:
            _auth_record_failure(ip)
            log.warning("Failed dashboard login from %s", ip)
            self._json(401, {"error": "That password didn't work."})

    def _handle_logout(self) -> None:
        token = self._session_token()
        if token:
            _session_drop(token)
        self._json(200, {"ok": True}, [("Set-Cookie", _cookie_header("", 0))])

    def _handle_restart(self, body: Dict[str, object]) -> None:
        if body.get("confirm") is not True:
            self._json(400, {"error": "Restart needs confirmation."})
            return
        if not os.environ.get("INVOCATION_ID"):
            self._json(409, {"error": "wifimon isn't running as a systemd service here, "
                                      "so it can't restart itself. Restart it from the terminal."})
            return
        run_bin, sctl = shutil.which("systemd-run"), shutil.which("systemctl")
        if not run_bin or not sctl:
            self._json(500, {"error": "systemd-run or systemctl not found."})
            return
        unit = f"wifimon-restart-{int(time.time())}"
        try:
            r = subprocess.run([run_bin, "--quiet", "--collect", f"--unit={unit}",
                                "--on-active=2", sctl, "restart", "wifimon.service"],
                               capture_output=True, text=True, timeout=10)
        except (subprocess.SubprocessError, OSError) as e:
            self._json(500, {"error": f"Restart failed: {e}"})
            return
        if r.returncode != 0:
            msg = _log_safe(r.stderr.strip()[:200]) or f"exit code {r.returncode}"
            log.warning("Dashboard restart failed: %s", msg)
            self._json(500, {"error": f"Restart failed: {msg}"})
            return
        log.info("Service restart requested from the dashboard by %s", self.client_address[0])
        self._json(200, {"ok": True, "message": "Restarting in about 2 seconds."})

    def _change_begin_checks(self, body: Dict[str, object], allow_hotspot: bool = False) -> bool:
        if _hotspot_active() and not allow_hotspot:
            self._json(409, {"error": "The hotspot is on. Stop it first (Radio & device card)."})
            return False
        if body.get("confirm") is not True:
            self._json(400, {"error": "This change needs confirmation."})
            return False
        if not shutil.which("nmcli"):
            self._json(409, {"error": "This needs NetworkManager (nmcli), which isn't installed."})
            return False
        if not _action_lock.acquire(blocking=False):
            self._json(409, {"error": "Another change is running. Try again in a moment."})
            return False
        with _change_lock:
            busy = _pending is not None
        if busy:
            _action_lock.release()
            self._json(409, {"error": "A change is still waiting to be kept or undone. "
                                      "Finish that one first."})
            return False
        self._defer = True
        return True

    def _release_and_send(self, release: bool = True) -> None:
        if release:
            _action_lock.release()
        self._defer = False
        if self._deferred is not None:
            status, obj, extra = self._deferred
            self._deferred = None
            self._json(status, obj, extra)

    def _device_from_body(self, body: Dict[str, object]) -> Optional[Dict[str, object]]:
        name = body.get("device")
        if not isinstance(name, str) or not _IFACE_RE.match(name):
            self._json(400, {"error": "Pick a WiFi device."})
            return None
        for d in _wifi_devices():
            if d["device"] == name:
                return d
        self._json(400, {"error": f"{name} isn't a WiFi device on this node."})
        return None

    def _change_result(self, p: Dict[str, object], ok: bool, msg: str, done_text: str) -> None:
        _slow_refresh.set()
        if ok:
            _arm_change(p)
            self._json(200, {"ok": True, "message": done_text, "pending": _pending_public()})
        else:
            _drop_change(p)
            self._json(500, {"error": f"That didn't work: {msg or 'nmcli failed'}"})

    def _handle_radio(self, body: Dict[str, object]) -> None:
        on = body.get("on")
        if not isinstance(on, bool):
            self._json(400, {"error": "Say whether to turn the radio on or off."})
            return
        if not self._change_begin_checks(body):
            return
        try:
            log.info("Dashboard: WiFi radio %s requested by %s", "on" if on else "off",
                     self.client_address[0])
            _grace_start("WiFi radio turned " + ("on" if on else "off") + " from the dashboard")
            if on:
                ok, msg = _nmcli_ok(["radio", "wifi", "on"])
                _slow_refresh.set()
                if ok:
                    self._json(200, {"ok": True, "message": "WiFi radio turned on."})
                else:
                    self._json(500, {"error": f"That didn't work: {msg or 'nmcli failed'}"})
                return
            profile = None
            for d in _wifi_devices():
                if d["device"] == INTERFACE:
                    profile = d["connection"]
            p = _begin_change("radio_off", "WiFi radio turned off",
                              {"radio_on": True, "reconnect": INTERFACE, "profile": profile})
            ok, msg = _nmcli_ok(["radio", "wifi", "off"])
            self._change_result(p, ok, msg, "WiFi radio turned off.")
        finally:
            self._release_and_send()

    def _handle_disconnect(self, body: Dict[str, object]) -> None:
        if not self._change_begin_checks(body):
            return
        try:
            dev = self._device_from_body(body)
            if dev is None:
                return
            if not _connected_state(dev["state"]):
                self._json(409, {"error": f"{dev['device']} isn't connected."})
                return
            if _dev_mode_of(dev.get("hw")) == "on":
                self._json(409, {"error": f"{dev['device']} is set to Keep on, so it would just rejoin. "
                                          "Set it to Auto or Keep off instead."})
                return
            name, profile = str(dev["device"]), dev["connection"]
            log.info("Dashboard: disconnect %s requested by %s", name, self.client_address[0])
            _grace_start(f"{name} disconnected from the dashboard")
            p = _begin_change("disconnect",
                              f"Disconnected {name}" + (f" from {profile}" if profile else ""),
                              {"reconnect": name, "profile": profile})
            ok, msg = _nmcli_ok(["device", "disconnect", name])
            self._change_result(p, ok, msg, f"{name} disconnected.")
        finally:
            self._release_and_send()

    def _handle_switch(self, body: Dict[str, object]) -> None:
        if not self._change_begin_checks(body):
            return
        try:
            dev = self._device_from_body(body)
            if dev is None:
                return
            name = str(dev["device"])
            if name == INTERFACE:
                self._json(409, {"error": f"{name} is already the device in use."})
                return
            if _dev_mode_of(dev.get("hw")) == "off":
                self._json(409, {"error": f"{name} is set to Keep off. Set it to Auto or Keep on first."})
                return
            previous = INTERFACE
            was_connected = _connected_state(dev["state"])
            log.info("Dashboard: switch %s -> %s requested by %s", previous, name,
                     self.client_address[0])
            _grace_start(f"switching WiFi device to {name} from the dashboard")
            p = _begin_change("switch", f"Switched WiFi device from {previous} to {name}",
                              {"interface": previous,
                               "disconnect": None if was_connected else name})
            ok, msg = True, ""
            if not was_connected:
                ok, msg = _nmcli_ok(["device", "connect", name], timeout=45)
            if ok:
                _set_interface(name)
            self._change_result(p, ok, msg, f"Now using {name}.")
        finally:
            self._release_and_send()

    def _handle_devmode(self, body: Dict[str, object]) -> None:
        mode = body.get("mode")
        if mode not in _DEV_MODES:
            self._json(400, {"error": "Pick Auto, Keep on or Keep off."})
            return
        if not self._change_begin_checks(body):
            return
        try:
            dev = self._device_from_body(body)
            if dev is None:
                return
            name, key = str(dev["device"]), dev.get("hw")
            word = _DEV_MODE_WORDS[str(mode)]
            if not key:
                self._json(409, {"error": f"Couldn't identify the {name} adapter."})
                return
            prev = _dev_mode_of(key)
            if prev == mode:
                self._json(200, {"ok": True, "message": f"{name} is already set to {word}."})
                return
            if mode == "off" and name == INTERFACE:
                self._json(409, {"error": f"The watchdog is using {name}. Press \"Use this device\" on "
                                          "another adapter first, then set this one to Keep off."})
                return
            state = str(dev.get("state") or "")
            undo: Dict[str, object] = {"dev_mode": {"key": key, "name": name, "mode": prev}}
            if mode == "off" and _connected_state(state):
                undo["reconnect"] = name
                undo["profile"] = dev["connection"]
            log.info("Dashboard: %s set to %s by %s", name, word, self.client_address[0])
            _grace_start(f"{name} set to {word} from the dashboard")
            p = _begin_change("device_mode", f"{name} set to {word}", undo)
            _set_dev_mode(key, name, str(mode))
            ok, msg = _nmcli_ok(["device", "set", name, "autoconnect", "no" if mode == "off" else "yes"])
            if ok:
                _devmode_applied.add(key)
            if ok and mode == "off" and state.startswith("connect"):
                ok, msg = _nmcli_ok(["device", "disconnect", name])
            if not ok:
                _set_dev_mode(key, name, prev)
            done = f"{name} set to {word}."
            if mode == "on" and name != INTERFACE and not _connected_state(state):
                done += " wifimon will join it to a saved network in a few seconds."
            elif mode == "on" and name == INTERFACE:
                done += " The watchdog already reconnects this adapter; NetworkManager may now rejoin it too."
            self._change_result(p, ok, msg, done)
        finally:
            self._release_and_send()

    def _handle_devforget(self, body: Dict[str, object]) -> None:
        key = body.get("key")
        if not isinstance(key, str) or not _DEV_KEY_RE.match(key):
            self._json(400, {"error": "Pick an adapter."})
            return
        with _devmode_lock:
            m = dict(_dev_modes[key]) if key in _dev_modes else None
        if m is None:
            self._json(409, {"error": "That adapter has no saved setting."})
            return
        if any(d.get("hw") == key for d in _wifi_devices()):
            self._json(409, {"error": f"{m['name']} is plugged in. Set it to Auto instead."})
            return
        _set_dev_mode(key, m["name"], "auto")
        log.info("Dashboard: forgot the %s setting for unplugged adapter %s (was %s) -- by %s",
                 _DEV_MODE_WORDS[m["mode"]], key, m["name"], self.client_address[0])
        _slow_refresh.set()
        self._json(200, {"ok": True, "message": f"Forgot the setting for {m['name']} ({key})."})

    def _handle_keep(self, body: Dict[str, object]) -> None:
        change_id = body.get("id")
        with _change_lock:
            p = _pending
            if p is None or p.get("id") != change_id:
                self._json(409, {"error": "No matching change is waiting."})
                return
            wait = float(p["keep_after"]) - time.monotonic()
        if wait > 0:
            self._json(409, {"error": "Too soon to confirm.",
                             "wait": None if wait == float("inf") else round(wait, 1)})
            return
        _finish_change(p, "kept", True, f"confirmed by the dashboard from {self.client_address[0]}")
        self._json(200, {"ok": True, "message": f"Change kept: {p['desc']}."})

    def _saved_row(self, ssid: object) -> Optional[Dict[str, object]]:
        if not isinstance(ssid, str) or not ssid:
            self._json(400, {"error": "Pick a network."})
            return None
        with _status_lock:
            slow = dict(_status["slow"])
        slow["profiles"] = _nm_wifi_profiles()
        for row in _saved_public(slow, None)["networks"]:
            if row["ssid"] == ssid:
                return row
        self._json(404, {"error": f"{ssid} isn't a saved network."})
        return None

    def _in_use_ssid(self) -> Optional[str]:
        return _nmcli_active_ap().get("nm_ssid") or _current_ssid()

    def _handle_scan(self, body: Dict[str, object]) -> None:
        if not shutil.which("nmcli"):
            self._json(409, {"error": "Scanning needs NetworkManager (nmcli)."})
            return
        if not _action_lock.acquire(blocking=False):
            self._json(409, {"error": "Busy with another change. Try again in a moment."})
            return
        try:
            ok, msg = _nmcli_ok(["device", "wifi", "rescan", "ifname", INTERFACE], timeout=15)
        finally:
            _action_lock.release()
        _slow_refresh.set()
        if ok:
            self._json(200, {"ok": True, "message": "Scanning. The list updates in a few seconds."})
        else:
            self._json(500, {"error": f"Scan didn't start: {msg or 'nmcli failed'}"})

    def _handle_net_connect(self, body: Dict[str, object]) -> None:
        if not self._change_begin_checks(body):
            return
        started = False
        try:
            row = self._saved_row(body.get("ssid"))
            if row is None:
                return
            if row["ssid"] == self._in_use_ssid():
                self._json(409, {"error": f"Already connected to {row['ssid']}."})
                return
            job = _start_connect_job(str(row["ssid"]))
            started = True
            self._json(202, {"ok": True, "message": f"Connecting to {row['ssid']}…", "job": job["id"]})
        finally:
            self._release_and_send(release=not started)

    def _handle_net_add(self, body: Dict[str, object]) -> None:
        net, err = _check_new_network(body)
        if net is None:
            self._json(400, {"error": err})
            return
        connect = body.get("connect") is True
        if not self._change_begin_checks({"confirm": True} if not connect else body,
                                         allow_hotspot=not connect):
            return
        started = False
        try:
            ssid = str(net["ssid"])
            with _status_lock:
                slow = dict(_status["slow"])
            slow["profiles"] = _nm_wifi_profiles()
            if any(r["ssid"] == ssid for r in _saved_public(slow, None)["networks"]):
                self._json(409, {"error": f"{ssid} is already saved. Use Connect, or delete it first."})
                return
            ok, result = _nm_add_profile(ssid, str(net["security"]), str(net["password"]),
                                         bool(net["hidden"]), real_mac=body.get("real_mac") is True)
            if not ok:
                self._json(500, {"error": f"Couldn't save {ssid}: {result}"})
                return
            with _conf_lock:
                nets = _conf_networks()
                nets.append({"ssid": ssid, "psk": net["password"],
                             "priority": max((int(n["priority"]) for n in nets), default=0) + 1,
                             "status": "unverified", "hidden": net["hidden"],
                             "security": {"open": "Open", "wpa2": "WPA2", "wpa3": "WPA3"}[str(net["security"])]})
                save_wifi_networks(nets, quiet=True)
            _mark_networks_changed()
            _slow_refresh.set()
            log.info("Dashboard: saved network %s (%s) from %s", ssid, net["security"],
                     self.client_address[0])
            if not connect:
                self._json(200, {"ok": True, "message": f"Saved {ssid}."})
                return
            job = _start_connect_job(ssid)
            started = True
            self._json(202, {"ok": True, "message": f"Saved {ssid}. Connecting…", "job": job["id"]})
        finally:
            self._release_and_send(release=not started)

    def _handle_net_delete(self, body: Dict[str, object]) -> None:
        if not self._change_begin_checks(body):
            return
        try:
            row = self._saved_row(body.get("ssid"))
            if row is None:
                return
            ssid = str(row["ssid"])
            if ssid == self._in_use_ssid():
                self._json(409, {"error": f"{ssid} is in use. Connect to another network first."})
                return
            problems = []
            for prof in _profiles_for(ssid):
                ok, msg = _nmcli_ok(["connection", "delete", "uuid", str(prof["uuid"])])
                if not ok:
                    problems.append(msg)
            with _conf_lock:
                nets = _conf_networks()
                kept = [n for n in nets if n["ssid"] != ssid]
                if len(kept) != len(nets):
                    save_wifi_networks(kept, quiet=True)
                    _mark_networks_changed()
            _slow_refresh.set()
            log.info("Dashboard: deleted network %s (from %s)", ssid, self.client_address[0])
            if problems:
                self._json(500, {"error": f"Deleted with problems: {'; '.join(problems)}"})
            else:
                self._json(200, {"ok": True, "message": f"Deleted {ssid}."})
        finally:
            self._release_and_send()

    def _handle_net_password(self, body: Dict[str, object]) -> None:
        ip = self.client_address[0]
        wait = _lockout_remaining(ip)
        if wait > 0:
            secs = int(wait) + 1
            self._json(429, {"error": f"Too many wrong passwords. Try again in {secs} s."},
                       [("Retry-After", str(secs))])
            return
        login_pw = body.get("password")
        if not isinstance(login_pw, str) or not login_pw or len(login_pw) > 1024:
            self._json(400, {"error": "Enter the root password."})
            return
        if not _verify_root_password(login_pw):
            _auth_record_failure(ip)
            log.warning("Failed password check for Show password from %s", ip)
            self._json(401, {"error": "That password didn't work."})
            return
        _auth_record_success(ip)
        row = self._saved_row(body.get("ssid"))
        if row is None:
            return
        ssid = str(row["ssid"])
        secret = _nm_secret(ssid)
        if not secret:
            conf = next((n for n in _conf_networks() if n["ssid"] == ssid), None)
            secret = str(conf.get("psk") or "") if conf else ""
        log.info("Dashboard: password for %s shown to %s", ssid, ip)
        if not secret:
            self._json(404, {"error": f"No password is saved for {ssid}."})
            return
        self._json(200, {"ok": True, "ssid": ssid, "password": secret})

    def _handle_net_move(self, body: Dict[str, object]) -> None:
        ssid, direction = body.get("ssid"), body.get("dir")
        if not isinstance(ssid, str) or direction not in ("up", "down"):
            self._json(400, {"error": "Pick a network and a direction."})
            return
        err = _move_network(ssid, str(direction))
        _slow_refresh.set()
        if err:
            self._json(409, {"error": err})
        else:
            self._json(200, {"ok": True})

    def _handle_net_track(self, body: Dict[str, object]) -> None:
        if not shutil.which("nmcli"):
            self._json(409, {"error": "This needs NetworkManager (nmcli)."})
            return
        if body.get("all") is True:
            conf = {str(n["ssid"]) for n in _conf_networks()}
            wanted = sorted({str(p["ssid"]) for p in _nm_wifi_profiles()} - conf, key=str.lower)
        elif isinstance(body.get("ssid"), str):
            wanted = [str(body["ssid"])]
        else:
            self._json(400, {"error": "Pick a network."})
            return
        added = _track_networks(wanted)
        _slow_refresh.set()
        if added:
            log.info("Dashboard: added to reconnect list: %s", ", ".join(added))
            self._json(200, {"ok": True, "message": "Added to the reconnect list: " + ", ".join(added) + "."})
        else:
            self._json(409, {"error": "Nothing to add."})

    def _handle_net_untrack(self, body: Dict[str, object]) -> None:
        if body.get("confirm") is not True:
            self._json(400, {"error": "This change needs confirmation."})
            return
        ssid = body.get("ssid")
        if not isinstance(ssid, str) or not _profiles_for(ssid):
            self._json(409, {"error": "Only networks NetworkManager also has can be taken off the "
                                      "list. Use Delete instead."})
            return
        with _conf_lock:
            nets = _conf_networks()
            kept = [n for n in nets if n["ssid"] != ssid]
            if len(kept) != len(nets):
                for i, n in enumerate(kept, start=1):
                    n["priority"] = i
                save_wifi_networks(kept, quiet=True)
        if len(kept) == len(nets):
            self._json(409, {"error": f"{ssid} isn't in the reconnect list."})
            return
        _mark_networks_changed()
        _slow_refresh.set()
        log.info("Dashboard: %s taken off the reconnect list", ssid)
        self._json(200, {"ok": True, "message": f"{ssid} taken off the reconnect list."})

    def _handle_net_edit(self, body: Dict[str, object]) -> None:
        if not self._change_begin_checks(body):
            return
        try:
            row = self._saved_row(body.get("ssid"))
            if row is None:
                return
            ssid = str(row["ssid"])
            if ssid == self._in_use_ssid():
                self._json(409, {"error": f"{ssid} is in use. Connect to another network before editing it."})
                return
            if row.get("security") and row["security"] not in _SECURITY_FROM_LABEL:
                self._json(409, {"error": f"{row['security']} networks can't be edited here."})
                return
            security = body.get("security")
            password = body.get("password") or ""
            if security in ("wpa2", "wpa3") and not password:
                password = _nm_secret(ssid) or next(
                    (str(n.get("psk") or "") for n in _conf_networks() if n["ssid"] == ssid), "")
                if not password:
                    self._json(400, {"error": "No saved password to keep. Enter the password."})
                    return
            net, err = _check_new_network({"ssid": ssid, "security": security,
                                           "password": password, "hidden": body.get("hidden") is True})
            if net is None:
                self._json(400, {"error": err})
                return
            old = _profiles_for(ssid)
            autoconnect = all(p.get("autoconnect", True) for p in old) if old else True
            ps_choice = body.get("powersave")
            if ps_choice == "off":
                powersave: Optional[int] = 2
            elif ps_choice == "default":
                powersave = None
            else:
                kept = [p.get("powersave") for p in old if p.get("powersave")]
                powersave = kept[0] if kept else None
            if row.get("in_nm") or not row.get("in_conf"):
                ok, result = _nm_add_profile(ssid, str(net["security"]), str(net["password"]),
                                             bool(net["hidden"]), autoconnect=autoconnect,
                                             powersave=powersave)
                if not ok:
                    self._json(500, {"error": f"Couldn't save the change: {result}"})
                    return
            problems = []
            if old and (row.get("in_nm") or not row.get("in_conf")):
                problems += _copy_nm_options(old[0], result)
            for prof in old:
                ok, msg = _nmcli_ok(["connection", "delete", "uuid", str(prof["uuid"])])
                if not ok:
                    problems.append(msg)
            with _conf_lock:
                nets = _conf_networks()
                changed = False
                for n in nets:
                    if n["ssid"] == ssid:
                        n.update(psk=net["password"], hidden=net["hidden"], status="unverified",
                                 security={"open": "Open", "wpa2": "WPA2", "wpa3": "WPA3"}[str(net["security"])])
                        changed = True
                if changed:
                    save_wifi_networks(nets, quiet=True)
            _mark_networks_changed()
            _slow_refresh.set()
            log.info("Dashboard: edited network %s (from %s)", ssid, self.client_address[0])
            if problems:
                self._json(500, {"error": "Saved, but the old profile couldn't be removed: " + "; ".join(problems)})
            else:
                self._json(200, {"ok": True, "message": f"Saved changes to {ssid}."})
        finally:
            self._release_and_send()

    def _handle_roaming(self, body: Dict[str, object]) -> None:
        if body.get("confirm") is not True:
            self._json(400, {"error": "This change needs confirmation."})
            return
        off = body.get("off")
        if not isinstance(off, bool):
            self._json(400, {"error": "Bad roaming request."})
            return
        st = _roam_state()
        if st["driver"] != "brcmfmac":
            self._json(409, {"error": "This only applies to the Pi's built-in Broadcom WiFi (brcmfmac driver)."})
            return
        current = _read_text(ROAM_MODPROBE)
        try:
            if off:
                _write_if_changed(ROAM_MODPROBE, "# Written by wifimon (Stop chip roaming). Used at boot.\n"
                                                 "options brcmfmac roamoff=1\n")
            elif current is not None:
                if not current.startswith("# Written by wifimon"):
                    self._json(409, {"error": f"{ROAM_MODPROBE} wasn't written by wifimon, so it was left alone."})
                    return
                os.remove(ROAM_MODPROBE)
        except OSError as e:
            self._json(500, {"error": f"Couldn't update {ROAM_MODPROBE}: {e}"})
            return
        _slow_refresh.set()
        log.info("Dashboard: chip roaming set to %s after the next reboot by %s",
                 "off" if off else "on", self.client_address[0])
        now_same = st["roam_off_now"] is off
        msg = ("Saved. " + ("Chip roaming is already " + ("off" if off else "on") + " now." if now_same
                            else "It takes effect after the next reboot."))
        self._json(200, {"ok": True, "message": msg})

    def _handle_country(self, body: Dict[str, object]) -> None:
        code = body.get("code")
        if not isinstance(code, str) or code.upper() not in COUNTRIES:
            self._json(400, {"error": "Pick a country from the list."})
            return
        code = code.upper()
        if not shutil.which("iw") and not shutil.which("raspi-config"):
            self._json(409, {"error": "Setting the country needs iw or raspi-config."})
            return
        before = _country_now() or "00"
        if before == code:
            self._json(200, {"ok": True, "message": f"The country code is already {code}."})
            return
        if not self._change_begin_checks(body):
            return
        try:
            log.info("Dashboard: WiFi country %s -> %s requested by %s", before, code, self.client_address[0])
            _grace_start(f"setting the WiFi country to {code} from the dashboard")
            p = _begin_change("country", f"WiFi country code set to {code} (was {before})",
                              {"country": before})
            ok, msg, now = _country_apply(code)
            if ok and now != code:
                note = f"Set to {code}, but the node still reports {now or 'no code'}. A reboot may be needed."
            else:
                note = f"WiFi country code set to {code} ({COUNTRIES[code]})."
            _slow_refresh.set()
            self._change_result(p, ok, msg, note)
        finally:
            self._release_and_send()

    def _handle_hotspot_start(self, body: Dict[str, object]) -> None:
        ready, why = _hotspot_ready()
        if not ready:
            self._json(409, {"error": why})
            return
        ssid, password, minutes = body.get("name"), body.get("password"), body.get("minutes")
        if not isinstance(ssid, str) or not ssid or len(ssid.encode("utf-8")) > 32 \
                or _SSID_BAD_RE.search(ssid) or ssid != ssid.strip():
            self._json(400, {"error": "Hotspot names are 1 to 32 characters, no control characters or edge spaces."})
            return
        if not isinstance(password, str) or not (8 <= len(password) <= 63) \
                or not all(" " <= c <= "~" for c in password):
            self._json(400, {"error": "The hotspot password must be 8 to 63 ordinary characters."})
            return
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not 5 <= minutes <= 240:
            self._json(400, {"error": "Auto-stop must be 5 to 240 minutes."})
            return
        if _hotspot_active():
            self._json(409, {"error": "The hotspot is already on."})
            return
        if not self._change_begin_checks(body):
            return
        started_job = False
        try:
            previous = self._in_use_ssid()
            ok, result = _hotspot_keyfile(ssid, password)
            if not ok:
                self._json(500, {"error": f"Couldn't set up the hotspot: {result}"})
                return
            token = secrets.token_hex(6)
            with _hotspot_lock:
                _hotspot.update(active=True, token=token, uuid=result, ssid=ssid, previous=previous,
                                minutes=minutes, stop_at=time.monotonic() + minutes * 60, address=None)
            _hotspot_persist()
            log.info("Dashboard: hotspot %s starting (auto-stop %d min, was on %s) by %s",
                     ssid, minutes, previous or "nothing", self.client_address[0])
            ok, msg = _nmcli_ok(["--wait", str(WM_CONNECT_WAIT), "connection", "up", "uuid", result,
                                 "ifname", INTERFACE], timeout=WM_CONNECT_WAIT + 15)
            if not ok:
                log.warning("Hotspot didn't start: %s", msg)
                note = _hotspot_stop(None, "failed to start")
                started_job = True
                self._json(500, {"error": f"The hotspot didn't start: {msg or 'nmcli failed'}. {note}"})
                return
            addr = _ip4_address().get("ip4") or "10.42.0.1"
            with _hotspot_lock:
                _hotspot["address"] = addr
            threading.Thread(target=_hotspot_timer, args=(token,), name="hotspot-timer", daemon=True).start()
            _slow_refresh.set()
            self._json(200, {"ok": True, "message": f"Hotspot {ssid} is on. Join it and open http://{addr}:{HTTP_PORT}",
                             "url": f"http://{addr}:{HTTP_PORT}"})
        finally:
            self._release_and_send(release=not started_job)

    def _handle_hotspot_stop(self, body: Dict[str, object]) -> None:
        if not _hotspot_active():
            self._json(409, {"error": "The hotspot isn't on."})
            return
        connect_to = body.get("connect_to")
        if connect_to is not None and not isinstance(connect_to, str):
            self._json(400, {"error": "Bad network name."})
            return
        if not self._change_begin_checks(body, allow_hotspot=True):
            return
        log.info("Dashboard: hotspot stop requested by %s", self.client_address[0])
        msg = _hotspot_stop(connect_to or None, "stopped from the dashboard")
        self._json(202, {"ok": True, "message": msg})
        self._release_and_send(release=False)

    def _handle_options(self, body: Dict[str, object]) -> None:
        if body.get("confirm") is not True:
            self._json(400, {"error": "This change needs confirmation."})
            return
        ssid = body.get("ssid")
        profs = _profiles_for(ssid) if isinstance(ssid, str) else []
        if not profs:
            self._json(409, {"error": "Options need a NetworkManager profile for that network."})
            return
        props, err = _options_props(body)
        if props is None:
            self._json(400, {"error": err})
            return
        changes = {str(p["uuid"]): _changed_options(p, props) for p in profs}
        changes = {u: c for u, c in changes.items() if c}
        if not changes:
            self._json(200, {"ok": True, "message": "Nothing changed."})
            return
        old = {u: {k: _norm_opt(k, next(p for p in profs if p["uuid"] == u).get(k)) for k in c}
               for u, c in changes.items()}
        in_use = ssid == self._in_use_ssid()
        if not in_use:
            problems = []
            for u, c in changes.items():
                args = ["connection", "modify", "uuid", u]
                for k, v in c.items():
                    args += [k, v]
                ok, msg = _nmcli_ok(args)
                if not ok:
                    problems.append(msg)
            _slow_refresh.set()
            log.info("Dashboard: options for %s changed by %s", ssid, self.client_address[0])
            if problems:
                self._json(500, {"error": "Couldn't save: " + "; ".join(problems)})
            else:
                self._json(200, {"ok": True, "message": f"Options saved for {ssid}. They apply the next time it connects."})
            return
        if not self._change_begin_checks(body):
            return
        try:
            active = _nm_active_uuid() or next(iter(changes))
            new_ip = props["ipv4.addresses"].split("/")[0] if props["ipv4.method"] == "manual" else ""
            open_url = f"http://{new_ip}:{HTTP_PORT}" if new_ip else ""
            _grace_start(f"changing options for {ssid} from the dashboard")
            p = _begin_change("options", f"New options for {ssid}" + (f" (fixed address {new_ip})" if new_ip else ""),
                              {"nm_restore": {"props": old, "activate": active}})
            with _change_lock:
                p["undo_secs"] = _OPTIONS_UNDO_SECS
                p["open_url"] = open_url or None
            problems = []
            for u, c in changes.items():
                args = ["connection", "modify", "uuid", u]
                for k, v in c.items():
                    args += [k, v]
                ok, msg = _nmcli_ok(args)
                if not ok:
                    problems.append(msg)
            ok, msg = (False, "; ".join(problems)) if problems else _nmcli_ok(
                ["--wait", str(WM_CONNECT_WAIT), "connection", "up", "uuid", active, "ifname", INTERFACE],
                timeout=WM_CONNECT_WAIT + 15)
            if not ok:
                _apply_undo(p["undo"])
                _drop_change(p)
                _slow_refresh.set()
                self._json(500, {"error": f"That didn't work, so the old options were put back: {msg}"})
                return
            log.info("Dashboard: options for %s (in use) changed by %s", ssid, self.client_address[0])
            self._change_result(p, True, "", "Options applied." + (
                f" If this page stops updating, open {open_url} (or http://{socket.gethostname()}.local:{HTTP_PORT}) "
                f"and log in within 2 minutes, or the old options come back." if open_url else ""))
        finally:
            self._release_and_send()

    def _handle_reconnect(self, body: Dict[str, object]) -> None:
        if not self._change_begin_checks(body):
            return
        started = False
        try:
            ssid = self._in_use_ssid()
            if not ssid:
                self._json(409, {"error": "Not connected to a network right now."})
                return
            if not _profiles_for(ssid) and not any(n["ssid"] == ssid for n in _conf_networks()):
                self._json(409, {"error": f"{ssid} isn't saved, so it can't be reconnected from here."})
                return
            log.info("Dashboard: reconnect to %s requested by %s", ssid, self.client_address[0])
            job = _start_connect_job(ssid, kind="reconnect")
            started = True
            self._json(202, {"ok": True, "message": f"Reconnecting to {ssid}…", "job": job["id"]})
        finally:
            self._release_and_send(release=not started)

    def _handle_powersave(self, body: Dict[str, object]) -> None:
        if body.get("confirm") is not True:
            self._json(400, {"error": "This change needs confirmation."})
            return
        if not shutil.which("nmcli"):
            self._json(409, {"error": "This needs NetworkManager (nmcli)."})
            return
        scope, value = body.get("scope"), body.get("value", "off")
        if value not in ("off", "default") or scope not in ("current", "all", "ssid"):
            self._json(400, {"error": "Bad power-save request."})
            return
        profiles = _nm_wifi_profiles()
        in_use = self._in_use_ssid()
        if scope == "current":
            targets = [p for p in profiles if p["ssid"] == in_use]
            what = str(in_use or "the network in use")
        elif scope == "ssid":
            targets = [p for p in profiles if p["ssid"] == body.get("ssid")]
            what = str(body.get("ssid"))
        else:
            targets = profiles
            what = "all saved networks"
        if not targets:
            self._json(409, {"error": f"No NetworkManager profile found for {what}."})
            return
        code = 2 if value == "off" else 0
        problems, changed = [], 0
        for p in targets:
            if (p.get("powersave") or 0) == code:
                continue
            ok, msg = _nmcli_ok(["connection", "modify", "uuid", str(p["uuid"]),
                                 "802-11-wireless.powersave", str(code)])
            if ok:
                changed += 1
            else:
                problems.append(msg)
        now = value == "off" and any(p["ssid"] == in_use for p in targets) and _iw_power_save_off()
        _slow_refresh.set()
        log.info("Dashboard: power save %s for %s (%d profile(s) changed) by %s",
                 value, what, changed, self.client_address[0])
        if problems:
            self._json(500, {"error": "Some networks couldn't be changed: " + "; ".join(problems)})
            return
        if value == "off":
            msg = f"Power save is off for {what}" + (", starting now." if now else
                                                     ". It takes effect the next time it connects.")
        else:
            msg = f"Power save is back to the default for {what}. It takes effect the next time it connects."
        self._json(200, {"ok": True, "message": msg})

    def _handle_autojoin(self, body: Dict[str, object]) -> None:
        ssid, on = body.get("ssid"), body.get("on")
        if not isinstance(ssid, str) or not isinstance(on, bool):
            self._json(400, {"error": "Pick a network and on or off."})
            return
        profs = _profiles_for(ssid)
        if not profs:
            self._json(409, {"error": f"Auto-join needs a NetworkManager profile, and {ssid} has none."})
            return
        problems = []
        for p in profs:
            if bool(p.get("autoconnect", True)) == on:
                continue
            ok, msg = _nmcli_ok(["connection", "modify", "uuid", str(p["uuid"]),
                                 "connection.autoconnect", "yes" if on else "no"])
            if not ok:
                problems.append(msg)
        _slow_refresh.set()
        log.info("Dashboard: auto-join %s for %s by %s", "on" if on else "off", ssid,
                 self.client_address[0])
        if problems:
            self._json(500, {"error": "Couldn't change auto-join: " + "; ".join(problems)})
        elif on:
            self._json(200, {"ok": True, "message": f"Auto-join is on for {ssid}."})
        else:
            self._json(200, {"ok": True, "message": f"Auto-join is off for {ssid}. The node won't join it by "
                                                    "itself; Connect still works."})

    def _handle_report_delete(self, body: Dict[str, object]) -> None:
        if body.get("confirm") is not True:
            self._json(400, {"error": "This change needs confirmation."})
            return
        rpath = _report_path(body.get("name"))
        if rpath is None or not os.path.isfile(rpath):
            self._json(404, {"error": "No such report."})
            return
        with _report_lock:
            os.remove(rpath)
        log.info("Dashboard: report %s deleted by %s", body.get("name"), self.client_address[0])
        self._json(200, {"ok": True, "message": "Report deleted."})

    def _handle_report_test(self, body: Dict[str, object]) -> None:
        if body.get("confirm") is not True:
            self._json(400, {"error": "This needs confirmation."})
            return
        report = _build_report("test", "test", "Test report saved from the dashboard (nothing shut down)")
        report["diagnostics"] = _diagnostics(10.0)
        try:
            name = _save_report(report)
        except OSError as e:
            self._json(500, {"error": f"Couldn't save the report: {e}"})
            return
        log.info("Dashboard: test report %s saved by %s", name, self.client_address[0])
        self._json(200, {"ok": True, "message": "Test report saved.", "name": name})

    def _handle_settings(self, body: Dict[str, object]) -> None:
        if body.get("confirm") is not True:
            self._json(400, {"error": "This change needs confirmation."})
            return
        values, err = _validate_settings(body.get("values"))
        if values is None:
            self._json(400, {"error": err})
            return
        before = _settings_current()
        note = _apply_settings(values)
        changes = [f"{k} {before[k]} -> {v}" for k, v in values.items() if before[k] != v]
        log.info("Dashboard: watchdog settings changed by %s: %s", self.client_address[0],
                 _log_safe(", ".join(changes) or "no change"))
        self._json(200, {"ok": True, "message": "Watchdog settings saved." + (f" {note}" if note else ""),
                         "settings": _settings_public()})

    def _handle_settings_reset(self, body: Dict[str, object]) -> None:
        if body.get("confirm") is not True:
            self._json(400, {"error": "This change needs confirmation."})
            return
        note = _apply_settings(dict(_SETTING_DEFAULTS))
        log.info("Dashboard: watchdog settings reset to defaults by %s", self.client_address[0])
        self._json(200, {"ok": True, "message": "Watchdog settings reset to defaults." + (f" {note}" if note else ""),
                         "settings": _settings_public()})

    def _handle_undo(self, body: Dict[str, object]) -> None:
        change_id = body.get("id")
        if not isinstance(change_id, str) or not _undo_change(change_id, "undone from the dashboard"):
            self._json(409, {"error": "No matching change is waiting."})
            return
        with _change_lock:
            last = dict(_last_result) if _last_result else {}
        if last.get("ok"):
            self._json(200, {"ok": True, "message": f"Undone: {last.get('desc')}."})
        else:
            self._json(500, {"error": f"Undo had problems: {last.get('message')}"})


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True
    request_queue_size = 16

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self._per_ip: Dict[str, int] = {}
        self._per_ip_lock = threading.Lock()

    def _take(self, ip: str) -> bool:
        with self._per_ip_lock:
            if self._per_ip.get(ip, 0) >= MAX_CONNECTIONS_PER_IP:
                return False
            if not self._slots.acquire(blocking=False):
                return False
            self._per_ip[ip] = self._per_ip.get(ip, 0) + 1
            return True

    def _give(self, ip: str) -> None:
        with self._per_ip_lock:
            left = self._per_ip.get(ip, 1) - 1
            if left > 0:
                self._per_ip[ip] = left
            else:
                self._per_ip.pop(ip, None)
            self._slots.release()

    def process_request(self, request, client_address):
        if not self._take(client_address[0]):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._give(client_address[0])
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._give(client_address[0])

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ssl.SSLError, ConnectionError, TimeoutError, socket.timeout)):
            log.debug("Connection from %s dropped: %s", client_address[0], _log_safe(exc))
        else:
            log.exception("Error handling request from %s", client_address[0])


def _start_web() -> Optional[_Server]:
    try:
        httpd = _Server((HTTP_BIND, HTTP_PORT), _Handler)
    except OSError as e:
        log.error("Dashboard disabled — can't listen on port %d: %s (watchdog keeps running)",
                  HTTP_PORT, e)
        return None
    tls = False
    if USE_TLS:
        if _ensure_tls_cert():
            try:
                ctx = _make_ssl_context()
                httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True,
                                               do_handshake_on_connect=False)
                tls = True
            except (ssl.SSLError, OSError) as e:
                log.error("HTTPS setup failed (%s) — serving plain HTTP", e)
        else:
            log.error("No HTTPS certificate — serving plain HTTP")
    if not tls and USE_TLS:
        log.warning("Dashboard is NOT encrypted: passwords cross the network in clear text. "
                    "Use it only on a trusted network.")
    elif not tls:
        log.info("Dashboard uses plain HTTP (USE_TLS is off)")
    _service_info["tls"] = tls
    return httpd


_PAGE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>wifimon</title>
<style>
:root{
  --bg:#0c1726; --panel:#132338; --panel2:#0e1c2e; --line:#264464;
  --text:#e8eef5; --muted:#c6d3e0; --amber:#f2a93b; --cyan:#5fd4ea;
  --good:#52d17f; --warn:#f2a93b; --bad:#f06464;
}
*{box-sizing:border-box}
[hidden]{display:none!important}
html,body{margin:0;background:var(--bg);color:var(--text);
  font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans",sans-serif}
button{font:inherit;cursor:pointer;border-radius:6px;border:1px solid var(--line);
  background:#1b3150;color:var(--text);padding:7px 14px}
button:hover{border-color:var(--cyan)}
button:disabled{opacity:.55;cursor:default}
button.danger{border-color:var(--bad);background:#3a1c26;color:#ffdede}
button:focus-visible,input:focus-visible{outline:2px solid var(--cyan);outline-offset:2px}
.good{color:var(--good)} .warn{color:var(--warn)} .bad{color:var(--bad)}

.login{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;padding:16px}
.login-box{width:100%;max-width:340px;background:var(--panel);border:1px solid var(--line);
  border-top:3px solid var(--amber);border-radius:10px;padding:24px;display:grid;gap:10px}
.login-box h1{margin:0;color:var(--amber);font-size:22px}
.login-box p{margin:0}
label{font-weight:600}
input[type=password]{font:inherit;padding:9px 10px;border-radius:6px;border:1px solid var(--line);
  background:var(--panel2);color:var(--text)}
.err{color:var(--bad);min-height:1.4em}
.muted{color:var(--muted)}

header{display:flex;align-items:center;gap:10px 14px;flex-wrap:wrap;padding:12px 18px;
  background:var(--panel2);border-bottom:2px solid var(--amber)}
header h1{margin:0;font-size:20px;color:var(--amber)}
header .host{color:var(--cyan);font-weight:600}
header .grow{flex:1}
.badge{font-size:12px;padding:2px 9px;border-radius:999px;border:1px solid currentColor;white-space:nowrap}

.banner{max-width:1100px;margin:16px auto 0;padding:12px 16px;border-radius:8px;
  background:#4a1822;border:1px solid var(--bad);color:#ffe4e4;font-weight:600}
main{max-width:1100px;margin:0 auto;padding:16px;display:grid;gap:16px;
  grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 18px;min-width:0}
.card h2{margin:0 0 12px;font-size:16px;color:var(--amber)}
#card-status{grid-column:1/-1}

.ssid{font-size:clamp(22px,5vw,30px);font-weight:700;line-height:1.2;overflow-wrap:anywhere}
.ssid.dim{color:var(--muted);font-weight:600}
.sub{color:var(--muted);min-height:1.4em;margin-top:2px}
.meter{margin:16px 0 4px}
.meter-track{position:relative;height:20px;border-radius:4px;background:var(--panel2);
  border:1px solid var(--line);overflow:hidden}
.meter-track::after{content:"";position:absolute;inset:0;pointer-events:none;
  background:repeating-linear-gradient(90deg,transparent 0 calc(100%/6 - 1px),
  rgba(232,238,245,.22) calc(100%/6 - 1px) calc(100%/6))}
.meter-fill{height:100%;width:0;background:var(--muted);transition:width .6s ease}
.meter-fill.good{background:var(--good)} .meter-fill.warn{background:var(--warn)}
.meter-fill.bad{background:var(--bad)}
.meter-scale{display:flex;justify-content:space-between;font-size:12px;color:var(--muted);
  margin-top:4px;font-variant-numeric:tabular-nums}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:14px}
.fact .k{font-size:13px;color:var(--muted)}
.fact .v{font-size:18px;font-weight:650;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}
.more{margin-top:16px}
.details{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:18px;
  margin-top:14px;padding-top:14px;border-top:1px solid var(--line)}
.group h3{margin:0 0 8px;font-size:14px;color:var(--cyan)}
.kv{display:grid;grid-template-columns:auto 1fr;gap:5px 14px;margin:0}
.kv dt{color:var(--muted)}
.kv dd{margin:0;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}

.timer{padding:10px 0;border-bottom:1px solid var(--line)}
.t-head{display:flex;justify-content:space-between;gap:8px}
.t-val{font-weight:650;color:var(--good);font-variant-numeric:tabular-nums}
.timer.active .t-val{color:var(--bad)}
.timer.idle .t-val{color:var(--muted)}
.t-bar{height:6px;border-radius:3px;background:var(--panel2);margin-top:6px;overflow:hidden}
.t-bar div{height:100%;width:0;background:var(--bad);transition:width 1s linear}
.rules{font-size:13px;color:var(--muted);margin:10px 0 12px}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}

.banner.pending{background:#3b2a0c;border-color:var(--amber);color:#ffedcc;
  display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.banner.pending span{flex:1;min-width:200px}
.timer.paused .t-val{color:var(--amber)}
.grace{margin:10px 0 0;padding:8px 10px;border-radius:6px;border:1px solid var(--amber);
  color:#ffedcc;background:#3b2a0c;font-size:14px}
.radio-row{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.radio-row .v{font-size:18px;font-weight:650;flex:1}
.card h3{margin:16px 0 8px;font-size:14px;color:var(--cyan)}
.dev{padding:10px 0;border-top:1px solid var(--line)}
.dev-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.dev-name{font-weight:650}
.dev-state{color:var(--muted);margin-top:2px;overflow-wrap:anywhere}
.dev .actions{margin-top:8px}
.seg{display:inline-flex;margin-top:8px;border:1px solid var(--line);border-radius:6px;overflow:hidden}
.seg button{border:0;border-radius:0;padding:6px 12px;background:transparent}
.seg button+button{border-left:1px solid var(--line)}
.seg button[aria-pressed="true"]{background:#1b3150;color:var(--cyan);font-weight:650}
.seg button[aria-pressed="true"]:disabled{opacity:1}
.dev-note{color:var(--warn);margin-top:4px;overflow-wrap:anywhere}
.note{margin:0 0 10px;padding:8px 10px;border-radius:6px;border:1px solid var(--line);
  background:var(--panel2);color:var(--muted);font-size:14px}
.wide{grid-column:1/-1}
.card-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px}
.card-head h2{margin:0;flex:1}
.net{padding:10px 0;border-top:1px solid var(--line)}
.net-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.net-name{font-weight:650;overflow-wrap:anywhere}
.prio{min-width:2.2em;text-align:center;font-variant-numeric:tabular-nums;color:var(--cyan);
  border:1px solid var(--line);border-radius:5px;padding:0 5px}
.net-meta{color:var(--muted);margin-top:2px;font-size:14px}
.net .actions{margin-top:8px;align-items:center}
.badge.muted{color:var(--muted)} .badge.cyan{color:var(--cyan)}
.pw{font-family:ui-monospace,"DejaVu Sans Mono",monospace;overflow-wrap:anywhere;
  background:var(--panel2);border:1px solid var(--line);border-radius:5px;padding:2px 8px}
.pw-ask{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.form{display:grid;gap:10px;padding:14px;margin-bottom:12px;border:1px solid var(--cyan);
  border-radius:8px;background:var(--panel2)}
.form .row{display:grid;gap:4px}
.form input[type=text],.form input[type=password],.form select,.pw-ask input{font:inherit;padding:8px 10px;
  border-radius:6px;border:1px solid var(--line);background:var(--panel);color:var(--text)}
.pw-field{display:flex;gap:6px}
.pw-field input{flex:1;min-width:0}
.check{display:flex;gap:8px;align-items:center;font-weight:400}
.sig{display:inline-block;width:52px;height:8px;border-radius:4px;background:var(--panel2);
  border:1px solid var(--line);overflow:hidden;vertical-align:middle}
.sig span{display:block;height:100%}
.steps{margin:6px 0 0;padding-left:20px;font-weight:400}
.banner.job{background:#0f2d3a;border-color:var(--cyan);color:#dff7fd}
.arrow{padding:1px 8px;line-height:1.2}
.form h3{margin:0;font-size:15px;color:var(--cyan)}
.form input[type=number]{font:inherit;padding:8px 10px;border-radius:6px;border:1px solid var(--line);
  background:var(--panel);color:var(--text);width:100%}
.form .hint{font-size:13px;color:var(--muted)}
.log{list-style:none;margin:0;padding:0;max-height:420px;overflow-y:auto;
  border:1px solid var(--line);border-radius:6px;background:var(--panel2)}
.log li{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;padding:6px 10px;
  border-bottom:1px solid var(--line);font-size:14px}
.log li:last-child{border-bottom:0}
.log time{color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}
.log .m{overflow-wrap:anywhere}
.log li.warning .m{color:var(--warn)}
.log li.error .m,.log li.critical .m{color:var(--bad)}
.pre{max-height:460px;overflow:auto;margin:10px 0 0;padding:10px;border-radius:6px;
  border:1px solid var(--line);background:var(--panel2);white-space:pre;
  font:12.5px/1.4 ui-monospace,"DejaVu Sans Mono",monospace}
a.btnlink{display:inline-block;border-radius:6px;border:1px solid var(--line);background:#1b3150;
  color:var(--text);padding:7px 14px;text-decoration:none}
a.btnlink:hover{border-color:var(--cyan)}
.popup{position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);z-index:10;
  background:var(--panel);border:1px solid var(--cyan);border-radius:10px;padding:16px 22px;
  max-width:90vw;box-shadow:0 12px 40px rgba(0,0,0,.55)}
.popup.err{border-color:var(--bad)}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
</head>
<body>

<div id="login" class="login" hidden>
  <form id="login-form" class="login-box">
    <h1>wifimon</h1>
    <p class="muted">WiFi watchdog. Log in with this node's root password.</p>
    <label for="login-pw">Root password</label>
    <input id="login-pw" type="password" autocomplete="current-password">
    <button type="submit" id="login-btn">Log in</button>
    <p id="login-err" class="err" role="alert"></p>
  </form>
</div>

<div id="app" hidden>
  <header>
    <h1>wifimon</h1>
    <span class="host" id="h-host"></span>
    <span class="grow"></span>
    <span class="badge bad" id="h-stale" hidden>Lost contact</span>
    <span class="badge" id="h-tls"></span>
  </header>
  <div id="banner" class="banner" role="alert" hidden></div>
  <div id="portal" class="banner pending" role="status" hidden></div>
  <div id="rep-banner" class="banner pending" role="status" hidden>
    <span id="rep-banner-text"></span>
    <button type="button" id="rep-banner-view">View report</button>
    <button type="button" id="rep-banner-close">Dismiss</button>
  </div>
  <div id="job" class="banner job" role="status" hidden>
    <div id="j-text"></div>
    <ol class="steps" id="j-steps"></ol>
  </div>
  <div id="hs-banner" class="banner job" role="status" hidden></div>
  <div id="pending" class="banner pending" role="status" hidden>
    <span id="p-text"></span>
    <button type="button" id="btn-undo">Undo now</button>
  </div>

  <main>
    <section class="card" id="card-status" aria-labelledby="st-h">
      <h2 id="st-h">Status</h2>
      <div class="ssid" id="s-ssid">Loading…</div>
      <div class="sub" id="s-sub"></div>
      <div class="meter" role="img" id="s-meter" aria-label="Signal strength">
        <div class="meter-track"><div class="meter-fill" id="m-fill"></div></div>
        <div class="meter-scale"><span>-90</span><span>-80</span><span>-70</span><span>-60</span><span>-50</span><span>-40</span><span>-30 dBm</span></div>
      </div>
      <div class="facts">
        <div class="fact"><div class="k">Signal</div><div class="v" id="s-sig">n/a</div></div>
        <div class="fact"><div class="k">IP address</div><div class="v" id="s-ip">n/a</div></div>
        <div class="fact"><div class="k">Internet</div><div class="v" id="s-net">n/a</div></div>
      </div>
      <p class="muted" id="s-today" hidden style="margin:10px 0 0;font-size:13px"></p>
      <div class="note" id="s-ps" hidden style="margin-top:14px">
        Power save is on. That can make the WiFi drop out.
        <div class="actions" style="margin-top:8px">
          <button type="button" id="btn-ps-cur">Turn off for this network</button>
          <button type="button" id="btn-ps-all">Turn off for all saved networks</button>
        </div>
      </div>
      <div class="note" id="s-cc" hidden style="margin-top:14px">
        No WiFi country code is set. That can keep a Pi's WiFi off or limited.
        <button type="button" id="btn-cc-fix" style="margin-left:8px">Fix</button>
      </div>
      <div class="more actions">
        <button type="button" id="btn-details" aria-expanded="false" aria-controls="details">More details</button>
        <button type="button" id="btn-reconnect">Reconnect now</button>
      </div>
      <div class="details" id="details" hidden></div>
      <div id="cc-box" hidden style="margin-top:14px;padding-top:12px;border-top:1px solid var(--line)">
        <h3 style="margin:0 0 6px;font-size:14px;color:var(--cyan)">WiFi country code</h3>
        <div class="radio-row"><span class="v" id="cc-now">n/a</span><button type="button" id="cc-change">Change</button></div>
        <form class="form" id="cc-form" hidden autocomplete="off" style="margin-top:10px">
          <div class="row"><label for="cc-sel">Country</label><select id="cc-sel"></select></div>
          <p class="muted" style="margin:0;font-size:13px">Sets which WiFi channels and power levels are allowed. Use the country the node is in.</p>
          <div class="actions"><button type="button" id="cc-set">Set</button><button type="button" id="cc-cancel">Cancel</button></div>
        </form>
      </div>
      <div id="roam-box" hidden style="margin-top:14px;padding-top:12px;border-top:1px solid var(--line)">
        <h3 style="margin:0 0 6px;font-size:14px;color:var(--cyan)">WiFi chip roaming</h3>
        <div class="radio-row"><span class="v" id="roam-now">n/a</span><button type="button" id="roam-toggle">Stop chip roaming</button></div>
        <p class="muted" style="margin:6px 0 0;font-size:13px">The Pi's WiFi chip keeps looking for a better access point by itself. With one router that only causes short dropouts, so stopping it can help. Takes effect after a reboot.</p>
      </div>
    </section>

    <section class="card wide" id="card-saved" aria-labelledby="sn-h">
      <div class="card-head">
        <h2 id="sn-h">Saved networks</h2>
        <button type="button" id="btn-track-all" hidden>Add all to reconnect list</button>
        <button type="button" id="btn-add">Add network</button>
      </div>
      <p class="note" id="n-note" hidden></p>
      <form class="form" id="add-form" hidden autocomplete="off">
        <h3 id="f-title">Add network</h3>
        <div class="row"><label for="f-ssid">Network name</label>
          <input type="text" id="f-ssid" maxlength="32" spellcheck="false"></div>
        <div class="row"><label for="f-sec">Security</label>
          <select id="f-sec"><option value="wpa2">WPA2</option><option value="wpa3">WPA3</option><option value="open">Open (no password)</option></select></div>
        <div class="row" id="f-pw-row"><label for="f-pw">Password</label>
          <div class="pw-field"><input type="password" id="f-pw" maxlength="64" autocomplete="new-password">
          <button type="button" id="f-eye" aria-pressed="false">Show</button></div></div>
        <label class="check"><input type="checkbox" id="f-hidden"> Hidden network (doesn't broadcast its name)</label>
        <label class="check" id="f-mac-row"><input type="checkbox" id="f-mac"> Use this Pi's real MAC address (for hotels and routers that register devices)</label>
        <div class="row" id="f-ps-row" hidden><label for="f-ps">Power save</label>
          <select id="f-ps"><option value="default">Leave as default</option><option value="off">Off (fewer dropouts)</option></select></div>
        <p class="err" id="f-err" role="alert"></p>
        <div class="actions">
          <button type="button" id="f-connect">Save &amp; connect</button>
          <button type="button" id="f-save">Save only</button>
          <button type="button" id="f-update" hidden>Save changes</button>
          <button type="button" id="f-cancel">Cancel</button>
        </div>
      </form>
      <form class="form" id="opt-form" hidden autocomplete="off">
        <h3 id="o-title">Options</h3>
        <div class="row"><label for="o-mode">IP address</label>
          <select id="o-mode"><option value="auto">Automatic</option><option value="fixed">Fixed address</option><option value="auto_dns">Automatic, with my own DNS servers</option></select></div>
        <div class="row" id="o-addr-row"><label for="o-addr">Address / prefix</label>
          <input type="text" id="o-addr" placeholder="192.168.1.50/24" spellcheck="false"></div>
        <div class="row" id="o-gw-row"><label for="o-gw">Gateway (router)</label>
          <input type="text" id="o-gw" placeholder="192.168.1.1" spellcheck="false"></div>
        <div class="row" id="o-dns-row"><label for="o-dns">DNS servers (up to 3, space separated)</label>
          <input type="text" id="o-dns" placeholder="1.1.1.1 8.8.8.8" spellcheck="false"></div>
        <label class="check"><input type="checkbox" id="o-mac"> Use this Pi's real MAC address (for hotels and routers that register devices)</label>
        <div class="row" id="o-band-row" hidden><label for="o-band">Band</label>
          <select id="o-band"><option value="any">Any</option><option value="bg">2.4 GHz only</option><option value="a">5 GHz only</option></select></div>
        <p class="err" id="o-err" role="alert"></p>
        <div class="actions">
          <button type="button" id="o-save">Save options</button>
          <button type="button" id="o-cancel">Cancel</button>
        </div>
      </form>
      <div id="n-list"><p class="muted">Loading…</p></div>
      <p class="rules" id="n-rules"></p>
    </section>

    <section class="card" id="card-scan" aria-labelledby="sc-h">
      <div class="card-head">
        <h2 id="sc-h">Nearby networks</h2>
        <button type="button" id="btn-scan">Rescan</button>
      </div>
      <p class="rules" id="sc-age"></p>
      <div id="sc-list"><p class="muted">Loading…</p></div>
    </section>

    <section class="card" id="card-radio" aria-labelledby="rd-h">
      <h2 id="rd-h">Radio &amp; device</h2>
      <p class="note" id="r-note" hidden></p>
      <div class="radio-row">
        <span>WiFi radio</span>
        <span class="v" id="r-radio">n/a</span>
        <button type="button" id="btn-radio" disabled>Turn off</button>
      </div>
      <h3>WiFi devices</h3>
      <div id="r-devs"><p class="muted">Loading…</p></div>
      <p class="rules" id="r-rules"></p>
      <h3>Emergency hotspot</h3>
      <p class="note" id="h-note" hidden></p>
      <div id="h-off">
        <p class="muted" style="margin:0 0 8px">The node makes its own WiFi so a phone can reach this page, for example to add a hotel network. It leaves its current WiFi while the hotspot is on.</p>
        <button type="button" id="btn-hs-open">Start hotspot</button>
        <form class="form" id="hs-form" hidden autocomplete="off" style="margin-top:12px">
          <div class="row"><label for="hs-name">Hotspot name</label><input type="text" id="hs-name" maxlength="32" spellcheck="false"></div>
          <div class="row"><label for="hs-pw">Password</label>
            <div class="pw-field"><input type="text" id="hs-pw" maxlength="63" spellcheck="false" autocomplete="off">
            <button type="button" id="hs-new">New</button></div></div>
          <div class="row"><label for="hs-min">Turn off by itself after</label>
            <select id="hs-min"><option value="15">15 minutes</option><option value="30" selected>30 minutes</option><option value="60">1 hour</option><option value="120">2 hours</option></select></div>
          <p class="err" id="hs-err" role="alert"></p>
          <div class="actions"><button type="button" id="hs-start">Start</button><button type="button" id="hs-cancel">Cancel</button></div>
        </form>
      </div>
      <div id="h-on" hidden>
        <p id="h-on-text" style="margin:0 0 8px"></p>
        <div class="row" style="display:grid;gap:4px;margin-bottom:8px"><label for="hs-back">Afterwards connect to</label><select id="hs-back"></select></div>
        <button type="button" class="danger" id="hs-stop">Stop hotspot</button>
      </div>
    </section>

    <section class="card" id="card-watchdog" aria-labelledby="wd-h">
      <h2 id="wd-h">Watchdog</h2>
      <div class="timer idle" id="t-conn">
        <div class="t-head"><span>No connection</span><span class="t-val" id="t-conn-val">Checking…</span></div>
        <div class="t-bar"><div id="t-conn-fill"></div></div>
      </div>
      <div class="timer idle" id="t-lowv">
        <div class="t-head"><span>Low voltage</span><span class="t-val" id="t-lowv-val">Checking…</span></div>
        <div class="t-bar"><div id="t-lowv-fill"></div></div>
      </div>
      <p class="grace" id="w-grace" hidden></p>
      <p class="rules" id="w-rules"></p>
      <dl class="kv" id="w-kv"></dl>
      <div class="actions"><button type="button" id="btn-settings">Change settings</button></div>
      <form class="form" id="set-form" hidden autocomplete="off" style="margin-top:12px">
        <h3>Watchdog settings</h3>
        <div class="row"><label for="s-noconn">Shut down after no connection for (seconds)</label>
          <input type="number" id="s-noconn" data-key="no_conn_shutdown_secs" step="1"><span class="hint"></span></div>
        <div class="row"><label for="s-lowvs">Shut down after low voltage for (seconds)</label>
          <input type="number" id="s-lowvs" data-key="low_voltage_shutdown_secs" step="1"><span class="hint"></span></div>
        <div class="row"><label for="s-lowv">Low voltage means core below (volts)</label>
          <input type="number" id="s-lowv" data-key="low_voltage_threshold" step="0.01"><span class="hint"></span></div>
        <div class="row"><label for="s-recon">Retry WiFi every (seconds) while offline</label>
          <input type="number" id="s-recon" data-key="reconnect_interval_secs" step="1"><span class="hint"></span></div>
        <div class="row"><label for="s-check">Check the connection every (seconds)</label>
          <input type="number" id="s-check" data-key="check_interval" step="1"><span class="hint"></span></div>
        <div class="row"><label for="s-ping">Internet check pings</label>
          <input type="text" id="s-ping" data-key="ping_target" spellcheck="false"><span class="hint"></span></div>
        <div class="row"><label class="check"><input type="checkbox" id="s-portal" data-key="detect_login_pages" data-hint="Default off. When on, NetworkManager fetches a small test page from nmcheck.gnome.org about every 5 minutes."> Detect login pages (hotel and guest WiFi)</label>
          <span class="hint"></span></div>
        <div class="row"><label class="check"><input type="checkbox" id="s-kps" data-key="keep_powersave_off" data-hint="Default off. When on, power save is off for every saved network and any added later, and wifimon turns it off again if a reconnect switches it back on. Turning this off leaves networks as they are; use each network's Options to change one back."> Keep WiFi power save off (all networks)</label>
          <span class="hint"></span></div>
        <p class="err" id="s-err" role="alert"></p>
        <div class="actions">
          <button type="button" id="s-save">Save settings</button>
          <button type="button" id="s-reset">Reset to defaults</button>
          <button type="button" id="s-cancel">Cancel</button>
        </div>
      </form>
    </section>

    <section class="card wide" id="card-log" aria-labelledby="lg-h">
      <div class="card-head">
        <h2 id="lg-h">Activity log</h2>
        <label class="check"><input type="checkbox" id="lg-warn"> Warnings and errors only</label>
        <button type="button" id="btn-copy-log">Copy</button>
      </div>
      <ul class="log" id="lg-list" aria-live="off"></ul>
      <p class="rules">The last 100 events since wifimon started, newest first. Kept in memory only; the full history is in the system journal (journalctl -u wifimon).</p>
      <div class="card-head" style="margin-top:16px">
        <h3 style="margin:0;flex:1">Shutdown reports</h3>
        <button type="button" id="btn-test-report">Save a test report</button>
      </div>
      <div id="rep-list"><p class="muted">Loading…</p></div>
      <div id="rep-view" hidden>
        <div class="card-head" style="margin-top:12px">
          <h3 id="rep-title" style="margin:0;flex:1"></h3>
          <a class="btnlink" id="rep-dl" href="#">Download</a>
          <button type="button" id="rep-close">Close</button>
        </div>
        <pre class="pre" id="rep-text"></pre>
      </div>
      <p class="rules">A report is saved every time wifimon shuts the node down, and after a stop that wasn't clean (power lost or a crash). The newest ones are kept.</p>
    </section>

    <section class="card" id="card-service" aria-labelledby="sv-h">
      <h2 id="sv-h">Service</h2>
      <dl class="kv" id="v-kv"></dl>
      <div class="actions">
        <button type="button" class="danger" id="btn-restart">Restart service</button>
        <button type="button" id="btn-logout">Log out</button>
      </div>
    </section>
  </main>
</div>

<div id="popup" class="popup" role="status" hidden></div>

<script>
"use strict";
(function () {
  const $ = (id) => document.getElementById(id);
  const NA = "n/a";
  const POLL_MS = 5000;
  let polling = false, pollTimer = null, popupTimer = null;
  let detailsOpen = false;
  let lastData = null;
  let busy = false;          // a change request is in flight
  let keepSent = null;       // id of the pending change we've already confirmed
  let pendingView = null;    // pending change + when it arrived, for the 1 s ticker
  let showing = null;        // {ssid, password, until} for Show password
  let askingFor = null;      // ssid whose Show password prompt is open
  const SHOW_SECS = 30;
  let timers = null;   // last countdowns + when they arrived, for the 1 s ticker

  try { detailsOpen = localStorage.getItem("wifimon.details") === "open"; } catch (e) {}

  const has = (x) => x !== null && x !== undefined && x !== "";
  const val = (x, unit) => has(x) ? String(x) + (unit || "") : NA;
  const yesno = (x, y, n) => x === true ? (y || "Yes") : x === false ? (n || "No") : NA;

  function dur(s) {
    if (!has(s)) return NA;
    s = Math.max(0, Math.floor(s));
    const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600),
          m = Math.floor(s % 3600 / 60), sec = s % 60;
    if (d) return d + "d " + h + "h";
    if (h) return h + "h " + m + "m";
    if (m) return m + "m " + sec + "s";
    return sec + "s";
  }
  function clock(s) {
    s = Math.max(0, Math.ceil(s));
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }
  function bytes(n) {
    if (!has(n)) return NA;
    const u = ["B", "KB", "MB", "GB", "TB"];
    let i = 0; n = Number(n);
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return (i ? n.toFixed(1) : String(Math.round(n))) + " " + u[i];
  }
  const rate = (n) => has(n) ? bytes(n) + "/s" : NA;
  const mbit = (x) => has(x) ? String(Number(Number(x).toFixed(1))) + " Mbit/s" : NA;
  const ago = (ts, now) => has(ts) ? dur(now - ts) + " ago" : "Never";

  function sigInfo(dbm) {
    if (!has(dbm)) return { label: NA, cls: "" };
    if (dbm >= -60) return { label: "Strong", cls: "good" };
    if (dbm >= -70) return { label: "Fair", cls: "warn" };
    return { label: "Weak", cls: "bad" };
  }
  function internet(n) {
    if (n.login_detect && n.connectivity === "portal") return { text: "Login page needed", cls: "warn" };
    if (n.internet === true) return { text: "Online", cls: "good" };
    if (n.via === "gateway") return { text: "Router only, no internet", cls: "warn" };
    if (n.internet === false) return { text: "Offline", cls: "bad" };
    return { text: "Checking…", cls: "" };
  }

  async function api(path, body) {
    const opts = { credentials: "same-origin", cache: "no-store" };
    if (body !== undefined) {
      opts.method = "POST";
      opts.headers = { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" };
      opts.body = JSON.stringify(body);
    }
    const r = await fetch(path, opts);
    let data = {};
    try { data = await r.json(); } catch (e) {}
    return { status: r.status, data: data || {} };
  }

  function showPopup(msg, isErr, ms) {
    const p = $("popup");
    p.textContent = msg;
    p.className = "popup" + (isErr ? " err" : "");
    p.hidden = false;
    clearTimeout(popupTimer);
    popupTimer = setTimeout(() => { p.hidden = true; }, ms || 2500);
  }

  // ── Login ────────────────────────────────────────────────────────────
  function showLogin(msg) {
    stopPolling();
    logEntries = []; logSeq = 0;
    $("app").hidden = true;
    $("login").hidden = false;
    $("login-err").textContent = msg || "";
    $("login-pw").focus();
  }
  function showApp() {
    $("login").hidden = true;
    $("app").hidden = false;
    startPolling();
  }
  $("login-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const pw = $("login-pw").value;
    if (!pw) { $("login-err").textContent = "Enter the root password."; return; }
    $("login-btn").disabled = true;
    $("login-err").textContent = "";
    try {
      const r = await api("/api/login", { password: pw });
      if (r.status === 200) { $("login-pw").value = ""; showApp(); }
      else $("login-err").textContent = r.data.error || ("Login failed (" + r.status + ").");
    } catch (e) {
      $("login-err").textContent = "Can't reach wifimon.";
    } finally {
      $("login-btn").disabled = false;
    }
  });

  // ── Polling (paused while the tab is hidden) ────────────────────────
  function startPolling() { if (!polling) { polling = true; tick(); } }
  function stopPolling() { polling = false; clearTimeout(pollTimer); }
  async function tick() {
    clearTimeout(pollTimer);
    if (!polling) return;
    try {
      const r = await api("/api/status");
      if (r.status === 401) { showLogin("Your session ended. Log in again."); return; }
      if (r.status === 200) { render(r.data); $("h-stale").hidden = true; }
      else $("h-stale").hidden = false;
    } catch (e) {
      $("h-stale").hidden = false;
    }
    if (polling && !document.hidden) pollTimer = setTimeout(tick, POLL_MS);
  }
  document.addEventListener("visibilitychange", () => {
    if (!polling) return;
    clearTimeout(pollTimer);
    if (!document.hidden) tick();
  });

  // ── Rendering ───────────────────────────────────────────────────────
  function fillKv(dl, rows) {
    dl.textContent = "";
    for (const [k, v] of rows) {
      const dt = document.createElement("dt"); dt.textContent = k;
      const dd = document.createElement("dd"); dd.textContent = v;
      dl.append(dt, dd);
    }
  }

  function detailGroups(d) {
    const w = d.wifi || {}, n = d.net || {}, wd = d.watchdog || {}, now = d.now;
    const blocked = w.rfkill_hard ? "Yes (hardware switch)"
                  : w.rfkill_soft ? "Yes (software)"
                  : w.rfkill_soft === false ? "No" : NA;
    let reTry = "Never";
    if (has(wd.last_reconnect_at)) {
      reTry = (wd.last_reconnect_ssid || "") + ", " + ago(wd.last_reconnect_at, now)
            + (wd.last_reconnect_ok === true ? " (worked)" : wd.last_reconnect_ok === false ? " (failed)" : "");
    }
    return [
      ["Connection", [
        ["Network name", val(w.ssid)],
        ["Saved profile", val(w.profile)],
        ["Access point (BSSID)", val(w.bssid)],
        ["Band / channel", has(w.band) ? w.band + (has(w.channel) ? ", channel " + w.channel : "") : NA],
        ["Security", val(w.security)],
        ["Connected for", dur(w.connected_secs)],
        ["Interface", val(w.iface) + (has(w.operstate) ? " (" + w.operstate + ")" : "")],
        ["Interface MAC", val(w.mac)],
      ]],
      ["Signal", [
        ["Strength", has(w.signal_dbm) ? w.signal_dbm + " dBm, " + sigInfo(w.signal_dbm).label.toLowerCase() : NA],
        ["Strength (%)", val(w.signal_pct, "%")],
        ["Link quality", val(w.link_quality)],
        ["Noise", val(w.noise_dbm, " dBm")],
        ["Receive speed", mbit(w.rx_bitrate)],
        ["Send speed", mbit(w.tx_bitrate)],
        ["Send retries", val(w.tx_retries)],
        ["Failed sends", val(w.tx_failed)],
        ["Beacon loss", val(w.beacon_loss)],
      ]],
      ["Network", [
        ["IP address", has(w.ip4) ? w.ip4 + (has(w.ip4_prefix) ? "/" + w.ip4_prefix : "") : NA],
        ["Gateway", val(w.gateway)],
        ["DNS servers", (w.dns && w.dns.length) ? w.dns.join(", ") : NA],
        ["Internet check", internet(n).text + (has(n.ping_target) ? " (pings " + n.ping_target + ")" : "")],
        ["Ping time", val(n.ping_ms, " ms")],
        ["Login-page check", n.login_detect ? val(n.connectivity) : "Off (Watchdog settings)"],
        ["Received since boot", bytes(w.rx_bytes)],
        ["Sent since boot", bytes(w.tx_bytes)],
        ["Download rate", rate(w.rx_rate)],
        ["Upload rate", rate(w.tx_rate)],
      ]],
      ["Pi health", [
        ["WiFi radio", yesno(w.radio, "On", "Off")],
        ["Radio blocked (rfkill)", blocked],
        ["Country code", !has(w.country) ? NA : w.country === "00" ? "Not set (00), WiFi may be limited" : w.country + (COUNTRY[w.country] ? " (" + COUNTRY[w.country] + ")" : "")],
        ["Power save", w.power_save === true ? "On (can cause dropouts)" : yesno(w.power_save, "On", "Off")],
      ]],
      ["WiFi health (today)", healthRows(d)],
      ["WiFi chips", chipRows(d)],
      ["Watchdog", [
        ["Last good network", val(wd.last_good_ssid)],
        ["Last connection drop", ago(wd.last_drop_at, now)],
        ["Last restored", ago(wd.last_restore_at, now)],
        ["Reconnect attempts", val(wd.reconnect_attempts) + " since service start"],
        ["Last reconnect try", reTry],
        ["Networks for auto-reconnect", val(wd.networks_configured)],
      ]],
    ];
  }

  // ── WiFi health (v5.19) ─────────────────────────────────────────────
  function roamText(rm) {
    const w = (x) => x === true ? "Off" : x === false ? "On" : "Unknown";
    const now = w(rm.roam_off_now), next = rm.roam_off_next_boot ? "Off" : "On";
    return "Now: " + now + (rm.roam_off_now !== null && next !== now ? ", after reboot: " + next : "");
  }
  function healthRows(d) {
    const h = d.health || {}, rm = h.roam || {};
    return [
      ["Brief blips", val(h.blips) + " (missed checks that came back by themselves)"],
      ["Connection drops", val(h.drops)],
      ["WiFi chip stalls", h.chip_stalls === null || h.chip_stalls === undefined ? "n/a (needs the kernel log)" : String(h.chip_stalls)],
      ["Last chip stall", has(h.last_stall_at) ? ago(h.last_stall_at, d.now) : "None today"],
      ["Last chip message", val(h.last_stall_line)],
      ["Chip roaming", rm.driver === "brcmfmac" ? roamText(rm) : "n/a (" + (rm.driver || "unknown driver") + ")"],
    ];
  }
  // ── WiFi chips (v5.20) ──────────────────────────────────────────────
  const NOT_SAID = "Not announced by the router";
  function chipRows(d) {
    const w = d.wifi || {}, c = w.chips || {}, pi = c.pi || {}, ap = c.ap;
    let piChip = NA;
    if (pi.chip || pi.maker) piChip = [pi.chip, pi.maker ? "(" + pi.maker + ")" : ""].filter(Boolean).join(" ");
    if (pi.usb_id) piChip += " [USB " + pi.usb_id + "]";
    const rows = [
      ["This Pi's WiFi chip", piChip + (pi.source ? " — from " + pi.source : "")],
      ["Driver", val(pi.driver) + (pi.bus ? " (" + pi.bus + ")" : "")],
      ["Chip firmware", val(pi.firmware)],
    ];
    if (!has(w.ssid)) { rows.push(["Router", "Not connected"]); return rows; }
    if (!ap) { rows.push(["Router", "No details cached yet (they appear after the Pi's next WiFi scan)"]); return rows; }
    const wp = ap.wps || {};
    const model = [wp.maker, wp.model, wp.model_number].filter(Boolean);
    rows.push(["Router maker / model", model.length ? model.join(" ") : NOT_SAID]);
    if (wp.device_name) rows.push(["Router device name", wp.device_name]);
    rows.push(["Router's WiFi chip (best guess)", (ap.chip_guess && ap.chip_guess.length)
      ? ap.chip_guess.join(", ") + " (from the tags it broadcasts)" : NOT_SAID]);
    rows.push(["Maker of its hardware address", ap.local_mac ? "None (the router set this address itself)"
      : ap.mac_vendor ? ap.mac_vendor : "Unknown (no maker list installed on this Pi)"]);
    return rows;
  }
  function todayLine(h) {
    if (!h || h.blips === undefined) return "";
    const n = (x, one, many) => x + " " + (x === 1 ? one : many);
    const parts = [n(h.blips || 0, "brief blip", "brief blips"), n(h.drops || 0, "drop", "drops")];
    if (h.chip_stalls !== null && h.chip_stalls !== undefined) parts.push(n(h.chip_stalls, "WiFi chip stall", "WiFi chip stalls"));
    return "Today: " + parts.join(" · ");
  }
  $("roam-toggle").addEventListener("click", async () => {
    const rm = ((lastData || {}).health || {}).roam || {};
    const off = !rm.roam_off_next_boot;
    if (!confirm(off ? "Stop the WiFi chip's own roaming after the next reboot?\n\nGood with one router. With several access points for the same network, the node will stay on the first one it joins."
                     : "Let the WiFi chip roam again after the next reboot?")) return;
    await post("/api/roaming", { off: off, confirm: true });
  });

  function renderDetails(d) {
    const box = $("details");
    box.textContent = "";
    for (const [title, rows] of detailGroups(d)) {
      const sec = document.createElement("section");
      sec.className = "group";
      const h = document.createElement("h3");
      h.textContent = title;
      const dl = document.createElement("dl");
      dl.className = "kv";
      fillKv(dl, rows);
      sec.append(h, dl);
      box.appendChild(sec);
    }
  }

  // ── WiFi country code (v5.15) ───────────────────────────────────────
  let COUNTRY = {};
  async function loadCountries() {
    if (Object.keys(COUNTRY).length) return;
    try { const r = await api("/api/countries"); if (r.status === 200) COUNTRY = r.data.countries || {}; } catch (e) {}
  }
  async function openCountry() {
    await loadCountries();
    const sel = $("cc-sel");
    if (!sel.options.length) {
      for (const [code, name] of Object.entries(COUNTRY).sort((a, b) => a[1].localeCompare(b[1]))) {
        const o = document.createElement("option");
        o.value = code; o.textContent = name + " (" + code + ")";
        sel.appendChild(o);
      }
    }
    const cur = ((lastData || {}).wifi || {}).country;
    const region = ((navigator.language || "").split("-")[1] || "").toUpperCase();
    sel.value = COUNTRY[cur] ? cur : (COUNTRY[region] ? region : "US");
    $("cc-form").hidden = false;
    sel.focus();
  }
  $("cc-change").addEventListener("click", openCountry);
  $("btn-cc-fix").addEventListener("click", () => {
    setDetails(true);
    openCountry();
    if ($("cc-box").scrollIntoView) $("cc-box").scrollIntoView({ block: "nearest" });
  });
  $("cc-cancel").addEventListener("click", () => { $("cc-form").hidden = true; });
  $("cc-form").addEventListener("submit", (ev) => ev.preventDefault());
  $("cc-set").addEventListener("click", async () => {
    const code = $("cc-sel").value;
    if (!confirm("Set the WiFi country code to " + COUNTRY[code] + " (" + code + ")?\n\nIf the channel in use isn't allowed there, "
        + "the WiFi drops briefly. If this page can't reach the node within 1 minute, the old code comes back.")) return;
    const r = await post("/api/country", { code: code, confirm: true });
    if (r && r.status < 300) $("cc-form").hidden = true;
  });
  loadCountries();

  function setDetails(open) {
    detailsOpen = open;
    $("details").hidden = !open;
    $("btn-details").setAttribute("aria-expanded", String(open));
    $("btn-details").textContent = open ? "Fewer details" : "More details";
    try { localStorage.setItem("wifimon.details", open ? "open" : "closed"); } catch (e) {}
    if (open && lastData) renderDetails(lastData);
    $("cc-box").hidden = !open;
    const rm = ((lastData || {}).health || {}).roam || {};
    $("roam-box").hidden = !open || rm.driver !== "brcmfmac";
  }
  $("btn-details").addEventListener("click", () => setDetails(!detailsOpen));

  function renderStatus(d) {
    const w = d.wifi || {}, n = d.net || {};
    const ssidEl = $("s-ssid");
    ssidEl.textContent = has(w.ssid) ? w.ssid : "Not connected";
    ssidEl.classList.toggle("dim", !has(w.ssid));
    const sub = [];
    if (has(w.band)) sub.push(w.band + (has(w.channel) ? ", channel " + w.channel : ""));
    if (has(w.security)) sub.push(w.security);
    $("s-sub").textContent = sub.join(", ");

    const s = sigInfo(w.signal_dbm);
    const pct = has(w.signal_dbm) ? Math.max(0, Math.min(100, (w.signal_dbm + 90) / 60 * 100)) : 0;
    $("m-fill").style.width = pct + "%";
    $("m-fill").className = "meter-fill " + s.cls;
    $("s-meter").setAttribute("aria-label", "Signal strength: " + (has(w.signal_dbm) ? w.signal_dbm + " dBm, " + s.label : "unknown"));
    $("s-sig").textContent = has(w.signal_dbm) ? w.signal_dbm + " dBm, " + s.label.toLowerCase() : NA;
    $("s-sig").className = "v " + s.cls;

    $("s-ip").textContent = val(w.ip4);
    const net = internet(n);
    $("s-net").textContent = net.text + (net.cls === "good" && has(n.ping_ms) ? ", " + n.ping_ms + " ms" : "");
    $("s-net").className = "v " + net.cls;

    // v5.19: today's WiFi health line + chip roaming box
    const tl = todayLine(d.health);
    $("s-today").textContent = tl;
    $("s-today").hidden = !tl;
    const rmx = (d.health || {}).roam || {};
    $("roam-box").hidden = !detailsOpen || rmx.driver !== "brcmfmac";
    if (rmx.driver === "brcmfmac") {
      $("roam-now").textContent = roamText(rmx);
      $("roam-toggle").textContent = rmx.roam_off_next_boot ? "Allow chip roaming" : "Stop chip roaming";
    }
    $("roam-toggle").disabled = locked(d);
    // v5.15: country code block + Fix warning
    $("cc-box").hidden = !detailsOpen;
    $("cc-now").textContent = !has(w.country) ? NA : w.country === "00" ? "Not set" : w.country + (COUNTRY[w.country] ? " (" + COUNTRY[w.country] + ")" : "");
    $("s-cc").hidden = w.country !== "00";
    $("cc-change").disabled = locked(d);
    $("btn-cc-fix").disabled = locked(d);
    // v5.7: power-save offer + Reconnect now
    const sv = d.saved || {}, lockNow = locked(d);
    const savedNames = new Set((sv.networks || []).map((x) => x.ssid));
    $("s-ps").hidden = !(w.power_save === true && sv.available);
    $("btn-ps-cur").disabled = lockNow || !has(w.ssid) || !savedNames.has(w.ssid);
    $("btn-ps-all").disabled = lockNow;
    $("btn-reconnect").disabled = lockNow || !has(w.ssid) || !savedNames.has(w.ssid);
    if (detailsOpen) renderDetails(d);
  }

  function drawTimer(prefix, remaining, total, idleText, idleCls) {
    const el = $(prefix);
    if (has(remaining)) {
      el.className = "timer active";
      $(prefix + "-val").textContent = "Shutdown in " + clock(remaining);
      $(prefix + "-fill").style.width = Math.min(100, (total - remaining) / total * 100) + "%";
    } else {
      el.className = "timer " + (idleCls || "");
      $(prefix + "-val").textContent = idleText;
      $(prefix + "-fill").style.width = "0%";
    }
  }
  function drawTimers() {
    if (!timers) return;
    const gone = (performance.now() - timers.at) / 1000;
    const left = (r) => has(r) ? Math.max(0, r - gone) : null;
    const grace = left(timers.grace);
    const g = $("w-grace");
    if (has(grace) && grace > 0) {
      g.textContent = "Shutdown timer paused for " + clock(grace) + " after a change from this page.";
      g.hidden = false;
    } else {
      g.hidden = true;
    }
    if (has(grace) && grace > 0 && !has(timers.conn) && timers.connected !== true) {
      drawTimer("t-conn", null, timers.connTotal, "Paused, " + clock(grace), "paused");
    } else {
      drawTimer("t-conn", left(timers.conn), timers.connTotal, timers.connIdle, timers.connIdleCls);
    }
    drawTimer("t-lowv", left(timers.lowv), timers.lowvTotal, timers.lowvIdle, timers.lowvIdleCls);
  }
  setInterval(() => { drawTimers(); drawPending(); }, 1000);

  function renderWatchdog(d) {
    const wd = d.watchdog || {}, p = d.power || {};
    timers = {
      at: performance.now(),
      conn: wd.no_conn_remaining, connTotal: wd.no_conn_total,
      connIdle: wd.connected === true ? "Connected" : "Checking…",
      connIdleCls: wd.connected === true ? "" : "idle",
      lowv: wd.lowv_remaining, lowvTotal: wd.lowv_total,
      lowvIdle: "Normal", lowvIdleCls: "",
      grace: (d.control || {}).grace_remaining, connected: wd.connected,
    };
    drawTimers();
    $("w-rules").textContent = "Shuts the node down after " + dur(wd.no_conn_total)
      + " with no connection, or " + dur(wd.lowv_total) + " of low voltage (below "
      + wd.low_v_threshold + " V core).";
    fillKv($("w-kv"), [
      ["Core voltage", val(p.volts, " V")],
      ["Under-voltage now", yesno(p.undervoltage_now)],
      ["Under-voltage since boot", yesno(p.undervoltage_seen)],
      ["CPU throttled now", yesno(p.throttled_now)],
      ["Trying to reconnect", yesno(wd.reconnecting)],
      ["Shutdown report", wd.recording
        ? "Recording details (" + wd.recording.count + " snapshots since " + stamp(wd.recording.started_at) + ")"
        : "Not needed right now"],
    ]);
  }

  function renderService(d) {
    const sv = d.service || {}, w = d.wifi || {};
    $("h-host").textContent = sv.host || "";
    // v5.5: the red badge only when HTTPS was switched on but isn't running.
    const tls = $("h-tls");
    tls.hidden = !sv.tls && !sv.tls_wanted;
    tls.textContent = sv.tls ? "HTTPS" : "Not encrypted";
    tls.className = "badge " + (sv.tls ? "good" : "bad");
    fillKv($("v-kv"), [
      ["Version", val(sv.version)],
      ["Running for", dur(sv.uptime_secs)],
      ["Connection", sv.tls ? "Encrypted (HTTPS)" : sv.tls_wanted ? "Not encrypted (HTTPS failed to start)" : "Plain HTTP"],
      ["WiFi tool", val(w.backend)],
      ["Running as root", yesno(sv.is_root)],
      ["Started by systemd", yesno(sv.systemd)],
    ]);
    $("btn-restart").disabled = !sv.systemd;
    $("btn-restart").title = sv.systemd ? "" : "Only works when wifimon runs as a service";
  }

  function renderPortal(d) {
    const n = d.net || {}, box = $("portal");
    if (n.login_detect && n.connectivity === "portal") {
      box.textContent = ((d.wifi || {}).ssid || "This network") + " wants a login page (like hotel or guest WiFi) before it lets the node online. "
        + "The node can't fill that page in by itself. Use another network, or ask for one without a login page.";
      box.hidden = false;
    } else {
      box.hidden = true;
    }
  }

  function renderBanner(d) {
    renderPortal(d);
    const s = d.shutdown, b = $("banner");
    if (s && s.active) {
      b.textContent = "This node is shutting down: " + (s.reason || "watchdog triggered");
      b.hidden = false;
    } else {
      b.hidden = true;
    }
  }

  // ── Radio & device card (v5.1) ──────────────────────────────────────
  const DEV_MODE_ASK = {
    auto: (n) => "Set " + n + " to Auto? NetworkManager decides when it connects.",
    on: (n) => "Set " + n + " to Keep on? wifimon will keep it joined to a saved network.",
    off: (n) => "Set " + n + " to Keep off? wifimon will disconnect it and keep it off, even after a reboot."
  };
  function stateText(dv) {
    const st = has(dv.state) ? dv.state : "unknown";
    return has(dv.connection) ? st + " to " + dv.connection : st;
  }
  function renderRadio(d) {
    const ctl = d.control || {}, w = d.wifi || {};
    const locked = busy || !ctl.available || !!ctl.pending || !!(d.job && d.job.state === "running");
    const note = $("r-note");
    if (!ctl.available) {
      note.textContent = "These controls need NetworkManager (nmcli), which isn't installed on this node.";
      note.hidden = false;
    } else if (ctl.pending) {
      note.textContent = "Waiting for the last change to be kept or undone.";
      note.hidden = false;
    } else {
      note.hidden = true;
    }
    const radio = $("r-radio"), rb = $("btn-radio");
    radio.textContent = yesno(w.radio, "On", "Off");
    radio.className = "v " + (w.radio === true ? "good" : w.radio === false ? "bad" : "");
    rb.textContent = w.radio === false ? "Turn on" : "Turn off";
    rb.className = w.radio === false ? "" : "danger";
    rb.disabled = locked || !has(w.radio);

    const box = $("r-devs");
    box.textContent = "";
    const devs = d.devices || [];
    if (!devs.length) {
      const p = document.createElement("p");
      p.className = "muted";
      p.textContent = "No WiFi devices found.";
      box.appendChild(p);
    }
    for (const dv of devs) {
      const row = document.createElement("div");
      row.className = "dev";
      const head = document.createElement("div");
      head.className = "dev-head";
      const name = document.createElement("span");
      name.className = "dev-name";
      name.textContent = dv.device;
      head.appendChild(name);
      if (dv.watched) {
        const b = document.createElement("span");
        b.className = "badge good";
        b.textContent = "In use";
        head.appendChild(b);
      }
      if (dv.mode === "on" || dv.mode === "off") {
        const b = document.createElement("span");
        b.className = "badge " + (dv.mode === "on" ? "cyan" : "muted");
        b.textContent = dv.mode === "on" ? "Kept on" : "Kept off";
        head.appendChild(b);
      }
      const st = document.createElement("div");
      st.className = "dev-state";
      st.textContent = stateText(dv);
      const acts = document.createElement("div");
      acts.className = "actions";
      if (String(dv.state || "").startsWith("connected") && dv.mode !== "on") {
        const btn = document.createElement("button");
        btn.type = "button"; btn.className = "danger"; btn.textContent = "Disconnect";
        btn.disabled = locked;
        btn.addEventListener("click", () => doChange("/api/device/disconnect", { device: dv.device },
          "Disconnect " + dv.device + (has(dv.connection) ? " from " + dv.connection : "") + "?", dv.device));
        acts.appendChild(btn);
      }
      if (!dv.watched && dv.mode !== "off") {
        const btn = document.createElement("button");
        btn.type = "button"; btn.textContent = "Use this device";
        btn.disabled = locked;
        btn.addEventListener("click", () => doChange("/api/device/switch", { device: dv.device },
          "Switch WiFi to " + dv.device + "? The watchdog will follow the new device.", null));
        acts.appendChild(btn);
      }
      row.append(head, st);
      if (dv.mode_note) {
        const n = document.createElement("div");
        n.className = "dev-note";
        n.textContent = dv.mode_note;
        row.appendChild(n);
      }
      if (dv.hw) {
        const seg = document.createElement("div");
        seg.className = "seg";
        seg.setAttribute("role", "group");
        seg.setAttribute("aria-label", dv.device + " setting");
        for (const [m, label] of [["auto", "Auto"], ["on", "Keep on"], ["off", "Keep off"]]) {
          const b = document.createElement("button");
          b.type = "button"; b.textContent = label;
          const cur = (dv.mode || "auto") === m;
          b.setAttribute("aria-pressed", String(cur));
          b.disabled = locked || cur || (m === "off" && dv.watched);
          if (m === "off" && dv.watched) b.title = "The watchdog is using this adapter. Use another one first.";
          b.addEventListener("click", () => doChange("/api/device/mode", { device: dv.device, mode: m },
            DEV_MODE_ASK[m](dv.device), m === "off" ? dv.device : "-"));
          seg.appendChild(b);
        }
        row.appendChild(seg);
      }
      if (acts.childNodes.length) row.appendChild(acts);
      box.appendChild(row);
    }
    for (const ab of (d.adapters_absent || [])) {
      const row = document.createElement("div");
      row.className = "dev";
      const head = document.createElement("div");
      head.className = "dev-head";
      const name = document.createElement("span");
      name.className = "dev-name";
      name.textContent = ab.name + " (" + ab.key.replace(/^if:/, "") + ")";
      const b = document.createElement("span");
      b.className = "badge muted";
      b.textContent = "Not plugged in";
      head.append(name, b);
      const st = document.createElement("div");
      st.className = "dev-state";
      st.textContent = "Set to " + (ab.mode === "on" ? "Keep on" : "Keep off") + ". The setting comes back if this adapter is plugged in again.";
      const acts = document.createElement("div");
      acts.className = "actions";
      const fb = document.createElement("button");
      fb.type = "button"; fb.textContent = "Forget";
      fb.disabled = busy;
      fb.addEventListener("click", () => {
        if (confirm("Forget the setting for " + ab.name + " (" + ab.key + ")?")) post("/api/device/forget", { key: ab.key });
      });
      acts.appendChild(fb);
      row.append(head, st, acts);
      box.appendChild(row);
    }
    $("r-rules").textContent = "Auto: NetworkManager decides. Keep on: wifimon rejoins the adapter if it drops "
      + "(the adapter in use is reconnected by the watchdog). Keep off: wifimon keeps the adapter disconnected, "
      + "even after a reboot. Settings follow the adapter itself, even if its wlan name changes. "
      + "Turning the radio off, disconnecting, switching devices, or changing an adapter setting undoes itself after "
      + dur(ctl.undo_secs) + " unless this page can still reach the node. The watchdog's shutdown timer pauses for "
      + dur(ctl.grace_total) + " after any change here.";
  }

  function drawPending() {
    const box = $("pending");
    if (!pendingView) { box.hidden = true; return; }
    const p = pendingView.p;
    let text = p.desc + ". ";
    if (!p.armed) text += "Working on it…";
    else {
      const left = Math.max(0, p.remaining - (performance.now() - pendingView.at) / 1000);
      text += "Undoes itself in " + clock(left) + " unless this page can still reach the node.";
      if (p.open_url) text += " New address: " + p.open_url;
    }
    $("p-text").textContent = text;
    box.hidden = false;
  }

  // The first successful poll at least a few seconds after a change proves
  // the browser can still reach the node, so the change is kept.
  function handleControl(d) {
    const ctl = d.control || {}, p = ctl.pending;
    pendingView = p ? { p: p, at: performance.now() } : null;
    drawPending();
    if (p && p.armed && p.keep_after <= 0 && keepSent !== p.id) {
      keepSent = p.id;
      api("/api/change/keep", { id: p.id })
        .then((r) => { if (r.status === 200) { showPopup(r.data.message); tick(); } else keepSent = null; })
        .catch(() => { keepSent = null; });
    }
    const last = ctl.last_result;
    if (last && last.outcome === "undone" && has(last.at) && d.now - last.at < 600) {
      let seen = null;
      try { seen = localStorage.getItem("wifimon.seenResult"); } catch (e) {}
      if (seen !== last.id) {
        try { localStorage.setItem("wifimon.seenResult", last.id); } catch (e) {}
        showPopup("Change undone: " + last.desc + " (" + last.message + ")", !last.ok, 8000);
      }
    }
  }

  async function doChange(path, body, question, dropsIface) {
    const c = (lastData && lastData.client) || {};
    const undoSecs = ((lastData && lastData.control) || {}).undo_secs || 60;
    let q = question;
    if (c.via_wifi && (!dropsIface || dropsIface === c.via_iface)) {
      q += "\n\nYou're reaching this page through " + c.via_iface + ", so this may cut you off. "
         + "If the page can't reach the node again within " + undoSecs + " seconds, the change undoes itself.";
    } else {
      q += "\n\nIf this page can't reach the node within " + undoSecs + " seconds afterwards, the change undoes itself.";
    }
    if (!confirm(q)) return;
    await sendChange(path, body);
  }
  async function sendChange(path, body) {
    busy = true;
    if (lastData) renderRadio(lastData);
    try {
      const r = await api(path, Object.assign({ confirm: true }, body));
      showPopup(r.data.message || r.data.error || ("Status " + r.status), r.status !== 200);
    } catch (e) {
      showPopup("Lost contact with the node. If the change cut you off, it undoes itself in about a minute.", true, 6000);
    }
    busy = false;
    tick();
  }

  // ── Saved networks + nearby networks (v5.2) ────────────────────────
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const btn = (text, cls, onClick, disabled) => {
    const b = el("button", cls, text);
    b.type = "button"; b.disabled = !!disabled;
    b.addEventListener("click", onClick);
    return b;
  };
  function locked(d) {
    const ctl = d.control || {};
    return busy || !!ctl.pending || !!(d.job && d.job.state === "running") || !(d.saved || {}).available;
  }
  function sigBar(pct) {
    const bar = el("span", "sig");
    const fill = el("span");
    fill.style.width = Math.max(0, Math.min(100, pct || 0)) + "%";
    fill.style.background = pct >= 60 ? "var(--good)" : pct >= 35 ? "var(--warn)" : "var(--bad)";
    bar.appendChild(fill);
    return bar;
  }
  const TAGS = { known_good: ["Known good", "good"], unverified: ["Not verified", "muted"], failed: ["Failed", "bad"] };

  function renderSaved(d) {
    const sv = d.saved || {}, lock = locked(d), list = $("n-list");
    const note = $("n-note");
    note.hidden = sv.available !== false;
    note.textContent = "Saving and connecting need NetworkManager (nmcli), which isn't installed on this node.";
    $("btn-add").disabled = lock;
    // Keep a half-typed Show-password prompt across the 5 s refresh.
    const oldAsk = list.querySelector(".pw-ask input");
    const typed = oldAsk ? oldAsk.value : "";
    const hadFocus = !!oldAsk && document.activeElement === oldAsk;
    list.textContent = "";
    const nets = sv.networks || [];
    if (!nets.length) list.appendChild(el("p", "muted", "No saved networks yet. Use Add network, or pick one under Nearby networks."));
    const listed = nets.filter((n) => n.in_conf).map((n) => n.ssid);
    const nmOnly = nets.filter((n) => !n.in_conf).length;
    $("btn-track-all").hidden = nmOnly < 2;
    $("btn-track-all").disabled = busy || sv.available === false;
    for (const n of nets) {
      const row = el("div", "net");
      const head = el("div", "net-head");
      if (n.in_conf) {
        const i = listed.indexOf(n.ssid);
        const up = btn("▲", "arrow", () => move(n.ssid, "up"), busy || i === 0);
        const down = btn("▼", "arrow", () => move(n.ssid, "down"), busy || i === listed.length - 1);
        up.setAttribute("aria-label", "Move " + n.ssid + " up");
        down.setAttribute("aria-label", "Move " + n.ssid + " down");
        head.append(up, down);
      }
      head.appendChild(el("span", "prio", has(n.priority) ? String(n.priority) : "–"));
      head.appendChild(el("span", "net-name", n.ssid));
      if (n.in_use) head.appendChild(el("span", "badge good", "In use"));
      if (n.status && TAGS[n.status]) head.appendChild(el("span", "badge " + TAGS[n.status][1], TAGS[n.status][0]));
      if (n.hidden) head.appendChild(el("span", "badge cyan", "Hidden"));
      if (n.autojoin === false) head.appendChild(el("span", "badge muted", "Auto-join off"));
      row.appendChild(head);
      const meta = [];
      meta.push(has(n.security) ? n.security : "Security unknown");
      meta.push(has(n.signal) ? "in range, " + n.signal + "%" : "not seen in the last scan");
      if (!n.in_conf) meta.push("not in the watchdog's reconnect list");
      row.appendChild(el("div", "net-meta", meta.join(", ")));

      const acts = el("div", "actions");
      if (n.security !== "Open") {
        if (showing && showing.ssid === n.ssid) {
          acts.appendChild(el("span", "pw", showing.password));
          acts.appendChild(btn("Hide", "", () => { showing = null; renderSaved(lastData); }));
        } else {
          acts.appendChild(el("span", "pw", "••••••••"));
          acts.appendChild(btn("Show", "", () => { askingFor = n.ssid; showing = null; renderSaved(lastData); }));
        }
      }
      if (!n.in_use) acts.appendChild(btn("Connect", "", () => connectSaved(n.ssid), lock));
      if (!n.in_use && (!n.security || EDITABLE[n.security])) acts.appendChild(btn("Edit", "", () => openEdit(n), lock));
      if (n.options) acts.appendChild(btn("Options", "", () => openOptions(n), lock));
      if (n.autojoin !== null && n.autojoin !== undefined) {
        const aj = btn(n.autojoin ? "Auto-join: on" : "Auto-join: off", "", () => setAutojoin(n.ssid, !n.autojoin), busy || sv.available === false);
        aj.setAttribute("aria-pressed", String(!!n.autojoin));
        acts.appendChild(aj);
      }
      if (!n.in_conf) acts.appendChild(btn("Add to reconnect list", "", () => post("/api/network/track", { ssid: n.ssid }), busy));
      else if (n.in_nm) acts.appendChild(btn("Take off list", "", () => untrack(n.ssid), busy));
      if (!n.in_use) acts.appendChild(btn("Delete", "danger", () => deleteSaved(n.ssid), lock));
      row.appendChild(acts);

      if (askingFor === n.ssid) {
        const ask = el("form", "pw-ask");
        const inp = el("input");
        inp.type = "password"; inp.placeholder = "Root password"; inp.autocomplete = "current-password";
        inp.setAttribute("aria-label", "Root password to show the WiFi password");
        const go = el("button", "", "Show password"); go.type = "submit";
        ask.append(inp, go, btn("Cancel", "", () => { askingFor = null; renderSaved(lastData); }));
        ask.addEventListener("submit", (ev) => { ev.preventDefault(); revealPassword(n.ssid, inp.value); });
        row.appendChild(ask);
        if (oldAsk) {
          inp.value = typed;
          if (hadFocus) inp.focus();
        } else {
          setTimeout(() => inp.focus(), 0);
        }
      }
      list.appendChild(row);
    }
    $("n-rules").textContent = "The number is the order the watchdog tries networks in when the connection drops; use the arrows to change it. "
      + "Connecting gives a network " + dur(sv.test_secs) + " to join. If it doesn't, the node goes back to the network it was on, "
      + "then tries other known-good networks (" + dur(sv.fallback_secs) + " each).";
  }

  function renderScan(d) {
    const sc = d.scan || {}, lock = locked(d), list = $("sc-list");
    const saved = new Set(((d.saved || {}).networks || []).map((n) => n.ssid));
    $("btn-scan").disabled = lock;
    $("sc-age").textContent = has(sc.at) ? "List from " + ago(sc.at, d.now) + "." : "";
    list.textContent = "";
    const nets = sc.networks || [];
    if (!nets.length) list.appendChild(el("p", "muted", (d.saved || {}).available === false ? "Scanning needs NetworkManager (nmcli)." : "No networks found. Try Rescan."));
    for (const n of nets) {
      const row = el("div", "net");
      const head = el("div", "net-head");
      head.append(sigBar(n.signal), el("span", "net-name", n.ssid));
      if (n.in_use) head.appendChild(el("span", "badge good", "In use"));
      else if (saved.has(n.ssid)) head.appendChild(el("span", "badge cyan", "Saved"));
      row.appendChild(head);
      row.appendChild(el("div", "net-meta", [n.signal + "%", n.band, n.security].filter(has).join(", ")));
      if (!n.in_use) {
        const acts = el("div", "actions");
        if (saved.has(n.ssid)) acts.appendChild(btn("Connect", "", () => connectSaved(n.ssid), lock));
        else if (n.security === "Open") acts.appendChild(btn("Connect", "", () => addNetwork({ ssid: n.ssid, security: "open", password: "", hidden: false }, true), lock));
        else acts.appendChild(btn("Add…", "", () => openForm(n.ssid, /WPA3/.test(n.security) && !/WPA2/.test(n.security) ? "wpa3" : "wpa2"), lock));
        row.appendChild(acts);
      }
      list.appendChild(row);
    }
  }

  function switchWarning(target) {
    const d = lastData || {}, c = d.client || {}, sv = d.service || {}, cur = (d.wifi || {}).ssid;
    let q = "Connect to " + target + "?";
    if (c.via_wifi) {
      q += "\n\nThis page will lose contact while the node switches. Its address may change, so come back at " + location.protocol + "//"
         + (sv.host || "your-node") + ".local:" + (sv.port || 8991) + " instead of the IP number.";
    }
    q += "\n\nIf " + target + " doesn't connect, the node goes back to " + (cur || "the network it was on")
       + ", then tries other known-good networks.";
    return q;
  }
  async function post(path, body) {
    busy = true;
    if (lastData) render(lastData);
    try {
      const r = await api(path, body);
      showPopup(r.data.message || r.data.error || ("Status " + r.status), r.status >= 300);
      return r;
    } catch (e) {
      showPopup("Lost contact with the node. If it's switching networks, reload this page in a minute.", true, 6000);
      return null;
    } finally {
      busy = false;
      tick();
    }
  }
  function connectSaved(ssid) {
    if (!confirm(switchWarning(ssid))) return;
    post("/api/network/connect", { ssid: ssid, confirm: true });
  }
  function deleteSaved(ssid) {
    if (!confirm("Delete " + ssid + "? Its saved password is removed from this node.")) return;
    post("/api/network/delete", { ssid: ssid, confirm: true });
  }
  async function revealPassword(ssid, loginPw) {
    if (!loginPw) return;
    try {
      const r = await api("/api/network/password", { ssid: ssid, password: loginPw });
      if (r.status === 200) {
        askingFor = null;
        showing = { ssid: ssid, password: r.data.password, until: Date.now() + SHOW_SECS * 1000 };
      } else {
        showPopup(r.data.error || ("Status " + r.status), true);
      }
    } catch (e) {
      showPopup("Can't reach wifimon.", true);
    }
    if (lastData) renderSaved(lastData);
  }
  setInterval(() => {
    if (showing && Date.now() >= showing.until) { showing = null; if (lastData) renderSaved(lastData); }
  }, 1000);

  const EDITABLE = { Open: "open", WPA2: "wpa2", WPA3: "wpa3" };
  let editing = null;        // ssid being edited, or null when adding
  function setFormMode(edit) {
    editing = edit;
    $("f-title").textContent = edit ? "Edit " + edit : "Add network";
    $("f-ssid").readOnly = !!edit;
    $("f-pw").placeholder = edit ? "Leave blank to keep the current password" : "";
    $("f-connect").hidden = !!edit;
    $("f-save").hidden = !!edit;
    $("f-update").hidden = !edit;
    $("f-ps-row").hidden = true;
    $("f-mac-row").hidden = !!edit;
  }
  function openEdit(n) {
    openForm(n.ssid, EDITABLE[n.security] || "wpa2");
    setFormMode(n.ssid);
    $("f-hidden").checked = !!n.hidden;
    $("f-ps-row").hidden = !(n.in_nm || !n.in_conf);
    $("f-ps").value = n.powersave === "off" ? "off" : "default";
    $("f-pw").focus();
  }
  function setAutojoin(ssid, on) { post("/api/network/autojoin", { ssid: ssid, on: on }); }
  function reconnectNow() {
    const d = lastData || {}, c = d.client || {}, cur = (d.wifi || {}).ssid;
    let q = "Reconnect to " + cur + "? The WiFi drops for a few seconds.";
    if (c.via_wifi) q += "\n\nThis page may lose contact for a moment.";
    q += "\n\nIf " + cur + " doesn't come back, the node tries other known-good networks.";
    if (!confirm(q)) return;
    post("/api/network/reconnect", { confirm: true });
  }
  function powerSaveOff(scope) {
    const cur = ((lastData || {}).wifi || {}).ssid;
    const what = scope === "all" ? "all saved networks" : cur;
    if (!confirm("Turn off power save for " + what + "? It stays off after reboots.")) return;
    post("/api/powersave", { scope: scope, value: "off", confirm: true });
  }
  $("btn-reconnect").addEventListener("click", reconnectNow);
  $("btn-ps-cur").addEventListener("click", () => powerSaveOff("current"));
  $("btn-ps-all").addEventListener("click", () => powerSaveOff("all"));
  function move(ssid, dir) { post("/api/network/move", { ssid: ssid, dir: dir }); }
  function untrack(ssid) {
    if (!confirm("Take " + ssid + " off the watchdog's reconnect list? NetworkManager keeps it saved.")) return;
    post("/api/network/untrack", { ssid: ssid, confirm: true });
  }
  async function saveEdit() {
    const v = formValues();
    if (v.security !== "open" && v.password && (v.password.length < 8 || v.password.length > 64)) {
      $("f-err").textContent = "WiFi passwords are 8 to 63 characters.";
      return;
    }
    if (!confirm("Save changes to " + editing + "? Its tag goes back to Not verified until it connects again.")) return;
    const extra = $("f-ps-row").hidden ? {} : { powersave: $("f-ps").value };
    const r = await post("/api/network/edit", Object.assign({ confirm: true }, v, extra, { ssid: editing }));
    if (r && r.status < 300) closeForm();
    else if (r) $("f-err").textContent = r.data.error || "";
  }
  $("f-update").addEventListener("click", saveEdit);

  // ── Per-network options (v5.12) ─────────────────────────────────────
  let optFor = null;
  function syncOptForm() {
    const m = $("o-mode").value;
    $("o-addr-row").hidden = m !== "fixed";
    $("o-gw-row").hidden = m !== "fixed";
    $("o-dns-row").hidden = m === "auto";
  }
  function openOptions(n) {
    const o = n.options || {};
    optFor = n;
    $("o-title").textContent = "Options for " + n.ssid;
    $("o-mode").value = o.ip_mode || "auto";
    $("o-addr").value = o.address || "";
    $("o-gw").value = o.gateway || "";
    $("o-dns").value = (o.dns || []).join(" ");
    $("o-mac").checked = !!o.real_mac;
    const five = ((lastData || {}).wifi || {}).has_5ghz === true;
    $("o-band-row").hidden = !five && o.band === "any";
    $("o-band").value = o.band || "any";
    $("o-err").textContent = "";
    syncOptForm();
    $("opt-form").hidden = false;
    $("o-mode").focus();
  }
  $("o-mode").addEventListener("change", syncOptForm);
  $("o-cancel").addEventListener("click", () => { $("opt-form").hidden = true; optFor = null; });
  $("opt-form").addEventListener("submit", (ev) => ev.preventDefault());
  $("o-save").addEventListener("click", async () => {
    if (!optFor) return;
    const body = { ssid: optFor.ssid, ip_mode: $("o-mode").value, address: $("o-addr").value.trim(),
                   gateway: $("o-gw").value.trim(), dns: $("o-dns").value.trim(), real_mac: $("o-mac").checked,
                   band: $("o-band-row").hidden ? "any" : $("o-band").value, confirm: true };
    let q = "Save these options for " + optFor.ssid + "?";
    if (optFor.in_use) {
      q += "\n\nThis is the network in use: the WiFi drops for a few seconds while it reconnects.";
      if (body.ip_mode === "fixed") q += " The node's address becomes " + body.address.split("/")[0] + ", so this page may need to be reopened there (and you'll log in again).";
      q += " If no page checks in within 2 minutes, the old options come back.";
    }
    if (!confirm(q)) return;
    const r = await post("/api/network/options", body);
    if (r && r.status < 300) { $("opt-form").hidden = true; optFor = null; }
    else if (r) $("o-err").textContent = r.data.error || "";
  });
  $("btn-track-all").addEventListener("click", () => post("/api/network/track", { all: true }));

  // ── Watchdog settings (v5.3) ─────────────────────────────────────────
  const setInputs = () => [...$("set-form").querySelectorAll("input[data-key]")];
  function fillSettings(values) {
    const st = ((lastData && lastData.watchdog) || {}).settings || {};
    for (const inp of setInputs()) {
      const k = inp.dataset.key, lim = (st.limits || {})[k];
      const hint = inp.closest(".row").querySelector(".hint");
      if (inp.type === "checkbox") {
        inp.checked = !!values[k];
        hint.textContent = inp.dataset.hint || "Default off.";
        continue;
      }
      inp.value = values[k];
      if (lim) { inp.min = lim[0]; inp.max = lim[1]; }
      hint.textContent = "Default " + (st.defaults || {})[k]
        + (lim ? ", allowed " + lim[0] + " to " + lim[1] : "") + ".";
    }
  }
  $("btn-settings").addEventListener("click", () => {
    const st = ((lastData && lastData.watchdog) || {}).settings;
    if (!st) return;
    fillSettings(st.values);
    $("s-err").textContent = "";
    $("set-form").hidden = false;
    $("s-noconn").focus();
  });
  $("s-cancel").addEventListener("click", () => { $("set-form").hidden = true; });
  $("set-form").addEventListener("submit", (ev) => ev.preventDefault());
  $("s-save").addEventListener("click", async () => {
    const values = {};
    for (const inp of setInputs()) {
      const k = inp.dataset.key;
      if (inp.type === "checkbox") values[k] = inp.checked;
      else if (k === "ping_target") values[k] = inp.value.trim();
      else {
        if (inp.value === "" || isNaN(Number(inp.value))) { $("s-err").textContent = "Fill in every number."; return; }
        values[k] = Number(inp.value);
      }
    }
    if (!confirm("Apply these watchdog settings? If a time limit changed, a countdown that's running now starts over.")) return;
    const r = await post("/api/settings", { confirm: true, values: values });
    if (r && r.status === 200) $("set-form").hidden = true;
    else if (r) $("s-err").textContent = r.data.error || "";
  });
  $("s-reset").addEventListener("click", async () => {
    if (!confirm("Reset every watchdog setting to its default?")) return;
    const r = await post("/api/settings/reset", { confirm: true });
    if (r && r.status === 200) $("set-form").hidden = true;
  });

  function openForm(ssid, sec) {
    setFormMode(null);
    $("add-form").hidden = false;
    $("f-ssid").value = ssid || "";
    $("f-sec").value = sec || "wpa2";
    $("f-pw").value = "";
    $("f-hidden").checked = false;
    $("f-mac").checked = false;
    $("f-err").textContent = "";
    syncForm();
    (ssid ? $("f-pw") : $("f-ssid")).focus();
  }
  function closeForm() { $("add-form").hidden = true; $("f-pw").value = ""; setFormMode(null); }
  function syncForm() { $("f-pw-row").hidden = $("f-sec").value === "open"; }
  function formValues() {
    return { ssid: $("f-ssid").value, security: $("f-sec").value,
             password: $("f-sec").value === "open" ? "" : $("f-pw").value, hidden: $("f-hidden").checked };
  }
  function formError(v) {
    if (!v.ssid.trim()) return "Enter the network name.";
    if (v.security !== "open" && (v.password.length < 8 || v.password.length > 64)) return "WiFi passwords are 8 to 63 characters.";
    return "";
  }
  async function addNetwork(v, connect) {
    const err = formError(v);
    if (err) { $("f-err").textContent = err; return; }
    if (connect && !confirm(switchWarning(v.ssid))) return;
    const r = await post("/api/network/add", Object.assign({ connect: connect, confirm: true, real_mac: $("f-mac").checked }, v));
    if (r && r.status < 300) closeForm();
    else if (r) $("f-err").textContent = r.data.error || "";
  }
  $("btn-add").addEventListener("click", () => openForm("", "wpa2"));
  $("f-sec").addEventListener("change", syncForm);
  $("f-eye").addEventListener("click", () => {
    const shown = $("f-pw").type === "text";
    $("f-pw").type = shown ? "password" : "text";
    $("f-eye").textContent = shown ? "Show" : "Hide";
    $("f-eye").setAttribute("aria-pressed", String(!shown));
  });
  $("f-connect").addEventListener("click", () => addNetwork(formValues(), true));
  $("f-save").addEventListener("click", () => addNetwork(formValues(), false));
  $("f-cancel").addEventListener("click", closeForm);
  $("add-form").addEventListener("submit", (ev) => ev.preventDefault());
  $("btn-scan").addEventListener("click", async () => {
    await post("/api/scan", {});
    setTimeout(tick, 4000);
  });

  // Connect job progress + its result, shown once per job.
  const ROLE = { target: "", "return": " (going back)", fallback: " (known good)" };
  const RESULT = { trying: "trying…", ok: "connected", failed: "didn't connect", skipped: "skipped, not in range" };
  function renderJob(d) {
    const j = d.job, box = $("job");
    if (j && j.state === "running") {
      $("j-text").textContent = (j.kind === "reconnect" ? "Reconnecting to " : "Connecting to ") + j.target + ". " + (j.phase || "") + "…";
      const ol = $("j-steps");
      ol.textContent = "";
      for (const st of j.steps || []) {
        ol.appendChild(el("li", "", st.ssid + ROLE[st.role] + ": " + RESULT[st.result]
          + (st.result === "failed" && st.note ? " (" + st.note + ")" : "")));
      }
      box.hidden = false;
      return;
    }
    box.hidden = true;
    if (j && j.ended_at && d.now - j.ended_at < 600) {
      let seen = null;
      try { seen = localStorage.getItem("wifimon.seenJob"); } catch (e) {}
      if (seen !== j.id) {
        try { localStorage.setItem("wifimon.seenJob", j.id); } catch (e) {}
        showPopup(j.message, j.state === "failed", 8000);
      }
    }
  }

  // ── Activity log (v5.4) ────────────────────────────────────────────
  let logEntries = [], logSeq = 0, logBusy = false;
  function pad(n) { return String(n).padStart(2, "0"); }
  function stamp(t) {
    const dt = new Date(t * 1000);
    return pad(dt.getHours()) + ":" + pad(dt.getMinutes()) + ":" + pad(dt.getSeconds());
  }
  function visibleLog() {
    const warnOnly = $("lg-warn").checked;
    return logEntries.filter((e) => !warnOnly || e.level !== "info").slice().reverse();
  }
  function drawLog() {
    const ul = $("lg-list");
    ul.textContent = "";
    const rows = visibleLog();
    if (!rows.length) {
      const li = el("li", "", "");
      li.appendChild(el("span", "m muted", "Nothing to show yet."));
      ul.appendChild(li);
    }
    for (const e of rows) {
      const li = el("li", e.level);
      const t = el("time", "", stamp(e.at));
      t.dateTime = new Date(e.at * 1000).toISOString();
      li.append(t, el("span", "m", (e.level === "info" ? "" : e.level.toUpperCase() + ": ") + e.msg));
      ul.appendChild(li);
    }
  }
  async function syncLog(seq) {
    if (logBusy || !has(seq) || seq === logSeq) return;
    if (seq < logSeq) { logEntries = []; logSeq = 0; }     // wifimon restarted
    logBusy = true;
    try {
      const r = await api("/api/log?after=" + logSeq);
      if (r.status === 200) {
        logEntries = logEntries.concat(r.data.entries || []).slice(-100);
        logSeq = r.data.seq;
        drawLog();
      }
    } catch (e) {
    } finally {
      logBusy = false;
    }
  }
  $("lg-warn").addEventListener("change", drawLog);
  async function copyText(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; }
    } catch (e) {}
    const ta = document.createElement("textarea");
    ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) {}
    ta.remove();
    return ok;
  }
  $("btn-copy-log").addEventListener("click", async () => {
    const rows = visibleLog();
    if (!rows.length) { showPopup("Nothing to copy.", true); return; }
    const text = rows.map((e) => new Date(e.at * 1000).toISOString() + "  " + e.level.toUpperCase() + "  " + e.msg).join("\n");
    showPopup(await copyText(text) ? "Copied " + rows.length + " log lines." : "Couldn't copy. Select the lines and copy them by hand.", false);
  });

  // ── Shutdown reports (v5.10) ────────────────────────────────────────
  let reportsStamp = null;
  const KIND = { shutdown: "Shutdown", test: "Test report", unclean: "Unclean stop" };
  const fmtWhen = (t) => has(t) ? new Date(t * 1000).toLocaleString() : NA;
  const reportUrl = (name, extra) => "/api/report?name=" + encodeURIComponent(name) + "&format=text" + (extra || "");
  async function loadReports() {
    try {
      const r = await api("/api/reports");
      if (r.status === 200) drawReports(r.data.reports || []);
    } catch (e) {}
  }
  function drawReports(list) {
    const box = $("rep-list");
    box.textContent = "";
    if (!list.length) { box.appendChild(el("p", "muted", "No reports saved yet.")); return; }
    for (const rp of list) {
      const row = el("div", "net");
      const head = el("div", "net-head");
      head.append(el("span", "net-name", fmtWhen(rp.created_at)),
                  el("span", "badge " + (rp.kind === "test" ? "muted" : "bad"), KIND[rp.kind] || rp.kind));
      row.append(head, el("div", "net-meta", (rp.reason || "") + " (" + rp.snapshots + " snapshots)"));
      const acts = el("div", "actions");
      acts.appendChild(btn("View", "", () => viewReport(rp)));
      const a = el("a", "btnlink", "Download");
      a.href = reportUrl(rp.name, "&download=1");
      acts.appendChild(a);
      acts.appendChild(btn("Delete", "danger", () => deleteReport(rp)));
      row.appendChild(acts);
      box.appendChild(row);
    }
  }
  async function viewReport(rp) {
    try {
      const r = await fetch(reportUrl(rp.name), { credentials: "same-origin", cache: "no-store" });
      if (r.status !== 200) { showPopup("Couldn't open that report.", true); return; }
      $("rep-text").textContent = await r.text();
    } catch (e) { showPopup("Can't reach wifimon.", true); return; }
    $("rep-title").textContent = (KIND[rp.kind] || rp.kind) + ", " + fmtWhen(rp.created_at);
    $("rep-dl").href = reportUrl(rp.name, "&download=1");
    $("rep-view").hidden = false;
    if ($("rep-view").scrollIntoView) $("rep-view").scrollIntoView({ block: "nearest" });
  }
  async function deleteReport(rp) {
    if (!confirm("Delete the report from " + fmtWhen(rp.created_at) + "?")) return;
    await post("/api/reports/delete", { name: rp.name, confirm: true });
    $("rep-view").hidden = true;
    loadReports();
  }
  $("rep-close").addEventListener("click", () => { $("rep-view").hidden = true; });
  $("btn-test-report").addEventListener("click", async () => {
    if (!confirm("Save a test report now? Nothing shuts down; it takes about 10 seconds.")) return;
    $("btn-test-report").disabled = true;
    await post("/api/reports/test", { confirm: true });
    $("btn-test-report").disabled = false;
    loadReports();
  });
  let bannerReport = null;
  function renderReportBanner(d) {
    const lr = d.last_report, box = $("rep-banner");
    let seen = null;
    try { seen = localStorage.getItem("wifimon.seenReport"); } catch (e) {}
    if (lr && seen !== lr.name) {
      bannerReport = lr;
      $("rep-banner-text").textContent = (lr.kind === "unclean" ? "The last run didn't stop cleanly (" : "The node shut down at ")
        + fmtWhen(lr.created_at) + (lr.kind === "unclean" ? "): " : ": ") + (lr.reason || "") + ".";
      box.hidden = false;
    } else {
      box.hidden = true;
    }
  }
  $("rep-banner-view").addEventListener("click", () => { if (bannerReport) viewReport(bannerReport); });
  $("rep-banner-close").addEventListener("click", () => {
    if (bannerReport) { try { localStorage.setItem("wifimon.seenReport", bannerReport.name); } catch (e) {} }
    $("rep-banner").hidden = true;
  });

  // ── Emergency hotspot (v5.13) ───────────────────────────────────────
  let hsView = null;
  function randomPassword() {
    const abc = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";
    const a = new Uint32Array(12);
    (window.crypto || window.msCrypto).getRandomValues(a);
    return Array.from(a, (x) => abc[x % abc.length]).join("");
  }
  function drawHotspotTimer() {
    if (!hsView) { $("hs-banner").hidden = true; return; }
    const h = hsView.h, left = Math.max(0, h.remaining - (performance.now() - hsView.at) / 1000);
    const url = "http://" + (h.address || "10.42.0.1") + ":" + ((lastData || {}).service || {}).port;
    $("hs-banner").textContent = "Hotspot " + h.ssid + " is on. Join it and open " + url + ". Turns off in " + clock(left) + ".";
    $("hs-banner").hidden = false;
    $("h-on-text").textContent = "On: " + h.ssid + ". Phones that join it can open " + url + ". Turns off by itself in " + clock(left) + ".";
  }
  setInterval(drawHotspotTimer, 1000);
  function renderHotspot(d) {
    const h = d.hotspot || {};
    $("h-note").hidden = h.available !== false || h.active;
    $("h-note").textContent = h.why || "";
    $("btn-hs-open").disabled = !h.available || busy || !!(d.control || {}).pending || !!(d.job && d.job.state === "running");
    $("h-off").hidden = !!h.active;
    $("h-on").hidden = !h.active;
    hsView = h.active ? { h: h, at: performance.now() } : null;
    if (h.active) {
      const sel = $("hs-back"), keep = sel.value;
      const names = ((d.saved || {}).networks || []).map((n) => n.ssid);
      if (sel.options.length !== names.length + 1) {
        sel.textContent = "";
        const first = el("option", "", h.previous ? h.previous + " (where it was)" : "Let the watchdog choose");
        first.value = h.previous || "";
        sel.appendChild(first);
        for (const n of names) if (n !== h.previous) { const o = el("option", "", n); o.value = n; sel.appendChild(o); }
        if (keep) sel.value = keep;
      }
    }
    drawHotspotTimer();
  }
  $("btn-hs-open").addEventListener("click", () => {
    $("hs-name").value = ((lastData || {}).hotspot || {}).default_name || "wifimon-setup";
    $("hs-pw").value = randomPassword();
    $("hs-err").textContent = "";
    $("hs-form").hidden = false;
  });
  $("hs-new").addEventListener("click", () => { $("hs-pw").value = randomPassword(); });
  $("hs-cancel").addEventListener("click", () => { $("hs-form").hidden = true; });
  $("hs-form").addEventListener("submit", (ev) => ev.preventDefault());
  $("hs-start").addEventListener("click", async () => {
    const name = $("hs-name").value, pw = $("hs-pw").value, mins = Number($("hs-min").value);
    if (!name.trim()) { $("hs-err").textContent = "Give the hotspot a name."; return; }
    if (pw.length < 8 || pw.length > 63) { $("hs-err").textContent = "The password must be 8 to 63 characters."; return; }
    const cur = ((lastData || {}).wifi || {}).ssid;
    if (!confirm("Start hotspot " + name + "?\n\nWrite down the password: " + pw + "\n\nThe node leaves "
        + (cur || "its current WiFi") + " while the hotspot is on, so this page will stop updating. Join " + name
        + " from your phone and open http://10.42.0.1:" + (((lastData || {}).service || {}).port || 8991)
        + " (the address can differ; the result appears here if you stay connected).\n\nIt turns off by itself after "
        + mins + " minutes and the node goes back to " + (cur || "a known network") + ".")) return;
    const r = await post("/api/hotspot/start", { name: name, password: pw, minutes: mins, confirm: true });
    if (r && r.status < 300) $("hs-form").hidden = true;
    else if (r) $("hs-err").textContent = r.data.error || "";
  });
  $("hs-stop").addEventListener("click", () => {
    const to = $("hs-back").value;
    if (!confirm("Stop the hotspot" + (to ? " and connect to " + to : "") + "? Phones joined to it will lose this page.")) return;
    post("/api/hotspot/stop", { confirm: true, connect_to: to || null });
  });

  function render(d) {
    lastData = d;
    syncLog(d.log_seq);
    renderReportBanner(d);
    if (d.reports_stamp !== reportsStamp) { reportsStamp = d.reports_stamp; loadReports(); }
    renderBanner(d);
    renderJob(d);
    renderStatus(d);
    renderSaved(d);
    renderScan(d);
    renderRadio(d);
    renderHotspot(d);
    renderWatchdog(d);
    renderService(d);
    handleControl(d);
  }

  // ── Actions ─────────────────────────────────────────────────────────
  $("btn-restart").addEventListener("click", async () => {
    if (!confirm("Restart the wifimon service?\n\nThe watchdog pauses for a few seconds, and you'll need to log in again afterwards.")) return;
    try {
      const r = await api("/api/service/restart", { confirm: true });
      showPopup(r.data.message || r.data.error || ("Status " + r.status), r.status !== 200);
    } catch (e) {
      showPopup("Can't reach wifimon.", true);
    }
  });
  $("btn-radio").addEventListener("click", () => {
    const w = (lastData && lastData.wifi) || {};
    if (w.radio === false) sendChange("/api/radio", { on: true });
    else doChange("/api/radio", { on: false }, "Turn the WiFi radio off? Every WiFi device goes offline.", null);
  });
  $("btn-undo").addEventListener("click", async () => {
    if (!pendingView) return;
    $("btn-undo").disabled = true;
    try {
      const r = await api("/api/change/undo", { id: pendingView.p.id });
      showPopup(r.data.message || r.data.error || ("Status " + r.status), r.status !== 200);
      try { localStorage.setItem("wifimon.seenResult", pendingView.p.id); } catch (e) {}
    } catch (e) {
      showPopup("Can't reach wifimon.", true);
    }
    $("btn-undo").disabled = false;
    tick();
  });
  $("btn-logout").addEventListener("click", async () => {
    try { await api("/api/logout", {}); } catch (e) {}
    showLogin("");
  });

  // ── Start ───────────────────────────────────────────────────────────
  setDetails(detailsOpen);
  api("/api/whoami")
    .then((r) => { if (r.data.auth) showApp(); else showLogin(""); })
    .catch(() => showLogin("Can't reach wifimon."));
})();
</script>
</body>
</html>
"""

_page_cache: Optional[bytes] = None


def _page_bytes() -> bytes:
    global _page_cache
    if _page_cache is None:
        _page_cache = _PAGE_HTML.replace("__APP_VERSION__", APP_VERSION).encode("utf-8")
    return _page_cache


def run() -> None:
    log.info("wifimon %s starting — watchdog active on %s", APP_VERSION, INTERFACE)
    if os.geteuid() != 0:
        log.warning("Not running as root -- shutdown/poweroff and WiFi "
                     "reconnect commands will likely fail with permission errors.")

    _clear_shutdown_state()
    _marker_check_and_set()
    _load_saved_interface()
    _load_dev_modes()
    _load_saved_settings()
    _apply_login_page_detection(DETECT_LOGIN_PAGES)
    _apply_keep_powersave_off(KEEP_POWERSAVE_OFF)
    _health_load()
    _recover_pending_change()
    _hotspot_recover()

    _service_info["root_pw"] = _root_password_status()
    if _service_info["root_pw"] == "none":
        log.warning("root has no usable password, so dashboard login will fail. "
                    "Set one with: sudo passwd root")

    watchdog = threading.Thread(target=_watchdog_loop, name="watchdog", daemon=True)
    watchdog.start()
    threading.Thread(target=_collector_loop, name="status", daemon=True).start()
    threading.Thread(target=_nm_sync_loop, name="nm-sync", daemon=True).start()
    threading.Thread(target=_kmsg_loop, name="kmsg", daemon=True).start()
    threading.Thread(target=_nm_monitor_loop, name="nm-monitor", daemon=True).start()
    threading.Thread(target=_devmode_loop, name="dev-mode", daemon=True).start()
    _nm_sync_wanted.set()

    httpd = _start_web()
    if httpd is None:
        while not _shutdown_event.wait(1.0):
            pass
    else:
        def _stopper() -> None:
            _shutdown_event.wait()
            httpd.shutdown()

        threading.Thread(target=_stopper, name="web-stop", daemon=True).start()
        scheme = "https" if _service_info["tls"] else "http"
        log.info("Dashboard listening on %s://%s:%d", scheme, HTTP_BIND, HTTP_PORT)
        try:
            httpd.serve_forever(poll_interval=0.5)
        finally:
            httpd.server_close()

    watchdog.join(timeout=10)
    _marker_clear()
    proc = _nm_monitor_proc
    if proc is not None and proc.poll() is None:
        proc.terminate()
    log.info("wifimon exiting")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WiFi and Voltage Watchdog + Dashboard for Raspberry Pi")
    parser.add_argument("--install", action="store_true", help="Install wifimon as a systemd service")
    parser.add_argument("--uninstall", action="store_true", help="Remove wifimon systemd service")
    parser.add_argument("--setup-wifi", action="store_true", help="Add/import WiFi networks")
    args = parser.parse_args()

    if args.install:
        install_service()
    elif args.uninstall:
        uninstall_service()
    elif args.setup_wifi:
        run_wifi_setup()
        result = subprocess.run(["systemctl", "is-active", "--quiet", "wifimon.service"])
        if result.returncode == 0:
            subprocess.run(["systemctl", "restart", "wifimon.service"], check=False)
            print("  [+] Restarted wifimon.service to pick up the new network(s)")
    else:
        run()
