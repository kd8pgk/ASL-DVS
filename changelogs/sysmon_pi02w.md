# SysMon, Pi Zero 2 W build changelog

Current file: `sysmon_pi02w_v6_13_67_4_20261006.py`. Newest entries first.

## 6.13.67.4-pi02w (2026-10-06)

- Phone tab, Dialing rules card: it now starts from each phone node's own
  `context =` as well as the `*61` autopatch context. Since Dashboard Pi02w 9.3.71.9,
  `*61` lands in a short `dvs-radio-<network>` context that hands the number to the
  dashboard, so the card stopped there and didn't show the dialing rules. The HOIP
  voicemail check that reads the same list works again.
- The card has a "Why there's a short dvs-radio context (show/hide)" note when that
  context is present.
- Autopatch modules card: lists `app_system.so` (hands numbers dialed from the radio
  to the dashboard) when the dialplan uses `System()`.

## 6.13.67.3-pi02w (2026-10-06)

- Launcher version 2 (`/usr/local/bin/asl_dvs_launch.py`, the same file every ASL-DVS `--install` writes) adds three memory savers, each with an off switch. Create the file and restart the service to turn one off; delete it and restart to turn it back on.
  - `python3 -OO`: drops docstrings from the loaded code. Off: `/etc/asl_dvs/launch_no_optimize`
  - `MALLOC_ARENA_MAX=2`: at most 2 malloc pools instead of up to 8 per CPU core. Off: `/etc/asl_dvs/launch_no_arena_cap`
  - `malloc_trim`: 1 minute after start, then every 5 minutes, freed memory is handed back to Linux. Off: `/etc/asl_dvs/launch_no_trim`
  
  The service files are unchanged: the launcher starts Python once more with `-OO` and `MALLOC_ARENA_MAX` (same PID, so systemd notify and watchdog are not affected). The launcher itself is comment-stripped too.

- Repo copy is comment-stripped. The change history that was in the file's comments now lives in this changelog.


## Earlier history

Carried over unchanged from the comments of the files below.

### sysmon_pi02w_v6_13_67_4_20261006.py (module docstring)

```text
ASL-DVS SYSMON  --  sysmon.py
Version : 6.13.67.3-pi02w  (20261006)
Build   : Pi Zero 2 W fork of v6.13.67
Authors : Claude AI (Anthropic) / KD8PGK
License : CC BY-NC 4.0
Nodes   : KD8PGK 652701 / 652702 / 652703

Changelog: the last 10 versions are below.  Older entries (v6.13.55 and
earlier) are in sysmon_changelog_v6_13_65_20261004.txt.

v6.13.67.3-pi02w -- Launcher version 2 (the same file every ASL-DVS --install writes): three memory savers, each with an off switch -- python3 -OO (drops docstrings from the loaded code; off: /etc/asl_dvs/launch_no_optimize), MALLOC_ARENA_MAX=2 (at most 2 malloc pools instead of up to 8 per CPU core; off: /etc/asl_dvs/launch_no_arena_cap) and malloc_trim every 5 minutes (freed memory handed back to Linux; off: /etc/asl_dvs/launch_no_trim).  Create the file and restart the service to turn one off.  The service files are unchanged; the launcher starts Python once more with -OO and MALLOC_ARENA_MAX (same PID).

v6.13.67.2-pi02w -- --uninstall no longer stops part-way if a compiled copy or the launcher is already gone (removed by another uninstall at the same moment).

v6.13.67.1-pi02w -- Zello tab removed (Pi Zero 2 W build).  The tab
for asl-zello-bridge (install/status/config/compatibility cards, sample
and override editor, start/stop/restart), its routes /api/zello GET and
POST, the "zello_installed" check in /api/status and the tab's entries in
the tab lists are gone.  A saved enabled_tabs list that still names zello
is fine -- unknown tabs are dropped when the config is read.  The bridge
service itself is untouched; Services and Journal still show it.
  Launcher: the service now starts through /usr/local/bin/asl_dvs_launch.py
(written by --install, shared with the Pi02w dashboard), which imports
this file instead of running it, so Python keeps its compiled copy in
__pycache__ and reuses it: about 26 MB settled instead of 54 MB, and twice
as fast to start.  --install also clears compiled copies of older
versions; --uninstall removes this version's and, when no other unit uses
it, the launcher.  The Security check "dashboard requires login" now takes
the last .py in the dashboard's ExecStart (the program, not the launcher).

v6.13.67-pi02w -- Pi Zero 2 W build, branched from v6.13.67.  A lighter
sysmon for the Pi Zero 2 W (512 MB RAM, 4 slow cores): tabs are removed
in stages; everything else matches v6.13.67.
  Console tab removed: the in-browser Asterisk console (websocket,
  asterisk -rvvv, embedded xterm.js), every Troubleshooting check and the
  Page self-check.  Routes gone: /api/console/*, /static/xterm.js,
  /static/xterm.css, /static/addon-fit.js.  The D-Star card keeps its
  "Remote control listening" row (helpers moved into the card).
  Net tab removed: hostname / .local tools, mtr install, ping and trace
  to Google, allstarlink.org, DV hosts and reflectors.  Routes gone:
  /api/net, /api/net/run, /api/net/cancel.  The background job runner
  and /api/net/job stay -- Phone -> Modules "Reinstall" uses them.
  Reg tab removed: the HTTP and IAX2 registration check cards.  Routes
  gone: /api/reg/http, /api/reg/iax.  The shared check-list renderer
  stays (Phone uses it).
  Firewall tab removed: ufw / nftables / firewalld rule views and
  editing, raw ruleset, enable / disable.  Route gone: /api/firewall (GET
  and POST).  Ports -> port details loses its Firewall zone (state and
  Allow / Deny), so /api/ports no longer reads the firewall on every
  15 s refresh.  Phone's read-only "Pi firewall" checks stay; their fix
  hints now give the Cockpit / firewall-cmd / nftables / ufw step.
  Cleanup: section labels updated for the tabs that remain, tab colour
  map trimmed.  A saved enabled_tabs list that still names a removed tab
  is fine -- unknown tabs are dropped when the config is read.
  Result: 33,068 -> ~23,400 lines, page 440 -> 358 KB, 53 -> 42 GET and
  30 -> 22 POST routes.  Checks run each stage: pyflakes (clean),
  node --check, dead-code and reachability scans, --selftest, every GET
  route called directly, and every tab opened in Chromium (no errors).

v6.13.67 -- D-Star card: gatewayAddress row fixed.  gatewayAddress is the
Pi's own address that ircDDBGateway binds every socket to (DExtra, D-Plus,
DCS, G2 and remote control), not the router's.  Blank (or 0.0.0.0) now
passes -- it is the normal setting -- with a "don't forward the port" note
when remote control is on.  127.0.0.1 fails (blocks reflector and gateway
links) and an address this Pi doesn't have (e.g. the router's) fails
(ircDDBGateway can't bind it).  The row shows whatever the remote-control
setting, since the address covers every link.  v6.13.66 passed 127.0.0.1
and warned on blank.

v6.13.66 -- D-Star -- ircDDBGateway card (ASL-DVS tab).
For dashboard v9.3.71, whose D-STAR tab links to gateway callsigns as well
as reflectors.  A new card under "DVSwitch -- Config Files" reads
/etc/ircddbgateway and checks: ircddbgatewayd running, gatewayCallsign,
repeaterBand1 (shown as the 8-character callsign the dashboard uses),
ircddbEnabled (gateway lookup), dextraEnabled (gateway links), and remote
control -- remoteEnabled (WARN when off: the dashboard falls back to
dvswitch.sh tune), remotePassword set (never shown), remotePort valid and
listening (catches settings not yet applied by a restart), gatewayAddress
(WARN when blank: listens on every interface).  Buttons: Edit (the file
is now in the DVSwitch config-file list), Restart ircddbgatewayd (root),
Refresh, Copy.  Read-only -- nothing changes the file but the editor.
New route /api/dstar-gw (GET checks, POST restart), added to the Page
self-check.  Console -> Saved favorites now passes D-STAR gateway rows
("W1ABC BL") and treats the unpadded "W1ABCBL" as old form (the dashboard
fixes it on load).

v6.13.65 -- Console Dashboard checks, stage 4 of 4 (release).
Summary of v6.13.62-v6.13.64: a new "Dashboard" group in Console ->
Troubleshooting (before Sysmon) with three read-only checks for the
dashboard's v9.3.61-v9.3.69 refactor -- "Dashboard file check" (version,
compiles, functions defined twice, every page button's function present),
"Node search lists" (the astdb.txt and EchoLink lists the ASL and Echo
search cards use) and "Saved favorites" (each saved ASL, Echo, D-STAR and
XLX row in asl_dvs.conf).  None connects to port 8989.  Run all goes from
33 to 36 checks (the Console keeps 40 results).  The Page self-check is
unchanged: it reads tab data routes, and these checks already run through
/api/console/tcatalog, which it covers.  Changelog entries v6.13.52-
v6.13.55 moved to sysmon_changelog_v6_13_65_20261004.txt.  Checks run:
py_compile, pyflakes (no new warnings), duplicate-function scan, node
--check, --selftest, and tests of each new check against dashboard
v9.3.60 and v9.3.69, broken copies (a missing page function, a file that
won't compile), sample astdb.txt / echolink dbdump output, and a sample
asl_dvs.conf with good, old-form, duplicate, bridge and bad rows.

v6.13.64 -- Console Dashboard checks, stage 3 of 4: Saved favorites.
"Saved favorites" reads asl_dvs.conf and checks every saved ASL, Echo,
D-STAR and XLX row: node numbers are 1-7 digits, no bridge or phone node
is saved as a favorite, nothing is saved twice, ASL/Echo rows past slot 10
(not loaded) are flagged, D-STAR rows are the 6-character base + module +
L (REF/XRF/DCS + 3 digits), XLX rows are XLX + 3 + module + L, and old
4-field XLX rows (skipped when the dashboard loads) are flagged.  Run it
after tapping Save on the dashboard to see the row landed right.

v6.13.63 -- Console Dashboard checks, stage 2 of 4: Node search lists.
"Node search lists" shows what the dashboard's ASL and Echo search cards
(dashboard v9.3.61/62) have to search: astdb.txt found, its date and how
many nodes it holds (read the way the dashboard reads it), the EchoLink
stations logged in now (asterisk -rx "echolink dbdump"), and the bridge
and phone nodes the dashboard leaves out of both searches.

v6.13.62 -- Console Dashboard checks, stage 1 of 4: Dashboard file check.
New "Dashboard" group in Troubleshooting (before Sysmon).  "Dashboard
file check" reads the installed asl_dvs_dashboard.py (never connects to
port 8989): shows its version (WARN if older than 9.3.69), compiles it in
memory (nothing written to the SD card), flags a function defined twice,
and checks that every on...= handler on the dashboard page names a
function the page script defines -- a renamed or removed function there
breaks a button.  _ts_dash_version() now finds the file through the new
shared _ts_dash_paths().  BUILD_DATE was a release behind; now 20261004.

v6.13.61 -- rpt.conf templates, stage 3 of 3: Console reader.
_ts_rpt_sections() (used by the Console's Bridge port check, Bridge
traffic and Stuck autopatch) now keeps the last value when a setting appears twice
in one section, as Asterisk does -- it used to keep the first.  It also
skips ;-- ... --; block comments instead of reading the lines inside.

v6.13.60 -- rpt.conf templates, stage 2 of 3: Console check.  New
"Template values" button in Troubleshooting -> Links: for each node it
lists the settings that come only from a template such as [node-main],
marks the ones the sysmon tabs read (callsign, idrecording, idtalkover,
rxchannel, statpost_url and the four DTMF settings) and fails any node
whose template isn't defined above it in rpt.conf.

v6.13.59 -- rpt.conf templates, stage 1 of 3: shared scanner.
_rpt_scan() now reads rpt.conf the way Asterisk does (checked against
Asterisk's main/config.c): a node's template values go in first, then
its own lines, and the last value wins -- so the node's own line beats
the template, and with two templates the second beats the first.
Templates of templates work, as does [name](!,base); a template must be
defined above the node that uses it.  ;-- ... --; block comments are now
skipped (a line inside one used to be read as a setting).  This changes
what the ASL-DVS rpt.conf card, the Reg tab, the DVSM tab, the M17 and
Zello rpt.conf checks, the header callsign and the Security identity
show when a value is set only in the template.  Checked: output
identical to v6.13.58 on sample files with no templates or block
comments; new cases (value only in template, node overrides, two
templates, template of template, missing template, block comments)
give Asterisk's answer.  #include lines are still not followed by this
scanner (the Phone tab and Node Settings reader does follow them).

v6.13.58 -- Refactor by tab and card, stage 6 of 6 (release).
Summary of v6.13.51-v6.13.57: a dead-code scan found nothing unused that
is safe to delete (the 58 decorator-registered Phone/Console checks and
the two web-server overrides only look unused; /api/dashboard-status,
/api/appconf/files and /api/abinfo are kept on purpose).  The code is now
grouped by tab, then by card, with no change to what any tab shows or
does.  Changelog entries before v6.13.49 moved to the separate file
sysmon_changelog_v6_13_58_20261004.txt (shipped with this file); the last
10 versions stay here.  _RADIO_TUNE_DRIVERS was checked and kept as is --
it is the allowlist the Tune save checks, and one item is correct today.
Checks run on every stage: py_compile, pyflakes (no new warnings), a
before/after comparison of every top-level statement and every module
value (route tables, Phone sections, Console checks, security checks),
the page outside the script byte-identical, every script statement
present once with non-function statements in the same order, node
--check, and --selftest.

v6.13.57 -- Refactor stage 5 of 6: Console.  The Troubleshooting checks
are grouped by their button group (Links, Bridges, Phone, Asterisk, Pi
health, Network, Sysmon), each helper beside the group that uses it;
helpers used by several groups come first.  Buttons, their order in
each group, and Run all are unchanged (checked against the old
catalog).  The unused "order" list in /api/console/tcatalog now follows
group order -- the page doesn't read it.  _ts_netcheck split into
_ts_nc_state, _ts_nc_network and _ts_nc_bridges.

v6.13.56 -- Refactor stage 4 of 6: Phone.  _phone_sec_health split into
_phone_health_nodes, _phone_health_files, _phone_health_live and
_phone_health_routes; _ph_hoip_checks split into _ph_hoip_server_ports,
_ph_hoip_transport_auth, _ph_hoip_signin and _ph_hoip_network_vm.  The
splits are mechanical (same statements, values passed in and out).
Health, HOIP and Netcheck output compared old vs new over 80 mocked
system states each (sample rpt/extensions/pjsip/iax files, canned
command output): identical.
```
