# SysMon, full build changelog

Current file: `sysmon_v6_13_70_20261007.py`. Newest entries first.

## 6.13.70 (2026-10-07)

Hardware tab: the **Video & GPU Memory** card from SysMon Pi02w 6.13.67.5.

- Two checkboxes that edit `/boot/firmware/config.txt` (Bookworm and Trixie), applied
  after a reboot. Unchecking puts the file back the way it was.
  - **Disable HDMI and video driver (headless):** comments out `dtoverlay=vc4-kms-v3d`
    as `#ASL-DVS-VIDEO-OFF# dtoverlay=vc4-kms-v3d`. Refused when there is no such line.
  - **Lower GPU memory to 16 MB:** adds a marked block at the end
    (`#ASL-DVS-GPUMEM-BEGIN`, `[all]`, `gpu_mem=16`, `#ASL-DVS-GPUMEM-END`). Camera and
    video decoding stop working. Greyed out on a Raspberry Pi 5, where `gpu_mem` has no
    effect.
- Shows the running state (vc4 loaded, HDMI outputs, GPU memory, CMA reserved), a
  "Reboot required" badge with a Reboot now button, the HDMI sound cards that go away,
  and settings that name a sound card by number.
- Each change writes `config.txt.asl_dvs.bak` first and replaces config.txt in one step.
  `--uninstall` and the uninstaller (1.3) put both settings back.

## 6.13.69 (2026-10-06)

Phone tab brought level with SysMon Pi02w 6.13.67.4, for Dashboard 9.3.73.

- Dialing rules card: starts from each phone node's own `context =` as well as the
  `*61` autopatch context, so it shows the dialing rules past the new short
  `dvs-radio-<network>` step. The HOIP voicemail check reading the same list keeps
  working.
- "Why there's a short dvs-radio context (show/hide)" note on the card.
- Autopatch modules card lists `app_system.so` when the dialplan uses `System()`.

## 6.13.68 (2026-10-06)

- No code change from 6.13.67. Repo copy is comment-stripped. The change history that was in the file's comments now lives in this changelog.


## Earlier history

Carried over unchanged from the comments of the files below.

### sysmon_v6_13_69_20261006.py (module docstring, as of 6.13.67)

```text
ASL-DVS SYSMON  --  sysmon.py
Version : 6.13.68  (20261006)
Authors : Claude AI (Anthropic) / KD8PGK
License : CC BY-NC 4.0
Nodes   : KD8PGK 652701 / 652702 / 652703

Changelog: the last 10 versions are below.  Older entries (v6.13.55 and
earlier) are in sysmon_changelog_v6_13_65_20261004.txt.

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

### sysmon_v6_5_18_20260823.py (older copy kept in the repo, stripped in place)

```text
ASL-DVS SYSMON  --  sysmon.py
Version : 6.5.18  (20260823)
Authors : Claude AI (Anthropic) / KD8PGK
License : CC BY-NC 4.0
Nodes   : KD8PGK 652701 / 652702 / 652703
```
