# SysMon, full build changelog

Current file: `sysmon_v6_13_74_20261007.py`. Newest entries first.

## 6.13.74 (2026-10-07)

- Hardware tab video options now survive an update, same as SysMon Pi02w
  6.13.67.9. `--uninstall` saves which of "Disable HDMI and video driver" and
  "Lower GPU memory" were on, in `/etc/sysmon/boot_restore.json` (mode 600, with the
  time), and still restores the stock `config.txt`. `--install` puts them back if
  that file is under 30 minutes old, then deletes it. The first update from an
  older SysMon falls back to SysMon's own `config.txt.asl_dvs.bak` when it is under
  30 minutes old and the service file is gone (an install after an uninstall, never
  an install over a running SysMon). Covers instmon's Full Update and Update, a
  manual reinstall, and the 44helper reinstall job.
- Tested: 17 checks of the save and put-back logic and 6 end-to-end checks that
  run the real `install_service` and `uninstall_service` against a sandbox.

## 6.13.73 (2026-10-07)

- Screen-size fixes, same as SysMon Pi02w 6.13.67.8, found sweeping every tab at the Galaxy Tab S6 Lite's widths
  (about 800 px portrait, 1280 px landscape, 980 px in Vivaldi's "Desktop site")
  and at phone width.
  - **Ports tab:** the column headers (PID, Known Service, Conflict) sat 28 to 56
    px left of their values at every width from 600 px up, because the header and
    each row sized their `auto` and `1fr` columns separately. Both now use the
    same fixed columns, with a little less letter spacing so PROTO and PROCESS no
    longer touch. On a phone the header now hides the same columns the rows hide
    (it used to spill onto extra lines). The Copy buttons wrap to a second line on
    a phone instead of running off the card.
  - **STFU tab:** at phone width the "Hotspot Password → Self Care" pill, the
    "✕ Close" button and the "Save then Restart to apply changes" text ran off
    the card. The BrandMeister bar and the editor button bar now wrap. (The M17
    editor bar uses the same class and gets the same fix.)
  - Checked in headless Chromium at 390, 600, 800, 980 and 1280 px, with the
    old build as a control (it fails the same checks), and with live-looking
    data on Ports, Services, Overview, Hardware and Security: no clipped
    content and no misaligned rows.

## 6.13.72 (2026-10-07)

- Copy buttons that copy the full desktop layout, whatever the screen size,
  same as SysMon Pi02w 6.13.67.7. Text is built from the page's data, not from
  what is on screen, so a phone and a desktop copy the same text.
- **Ports tab:** `Copy table` (current All/TCP/UDP filter), `Copy all` (every
  open port) and `Copy port details`. Columns: port, proto, process, PID, listen
  address, service, conflict (OK/DUP) and the full command line (new, from
  `/proc/<pid>/cmdline`, up to 300 chars). The page reads the full port list
  once and filters All/TCP/UDP in the page.
- **Services, Overview, Hardware and Security tabs:** a Copy button on each.
  Hardware copies the whole tab; Security copies every check with its result and,
  for warnings and failures, what it means and how to fix it.
- The Journal tab already copies from its popup; unchanged.

## 6.13.71 (2026-10-07)

- Copy buttons on the DVSwitch / M17 / STFU cards work again (Copy Stanza on
  the sample USRP2M17.ini and DVSwitch.ini cards, and the copy buttons for
  values and secrets). They used only `navigator.clipboard`, which browsers
  provide on https or localhost but not on `http://<node-ip>`, so nothing was
  copied. They now copy through a hidden text box first (works on plain http,
  iOS too) and use `navigator.clipboard` only where it exists. A failed copy
  says so ("Copy failed" and a message) instead of showing a tick.
- Copy Stanza no longer leaves its button stuck on "✓". Same fix as SysMon
  Pi02w 6.13.67.6.

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
- Headless-only warning on the card and in the confirm dialog: on a laptop or a computer
  with a monitor you use, don't turn off video, since the screen goes blank after the
  reboot. A red warning appears when a monitor is connected or the system boots to a
  desktop (`graphical.target`). On a laptop or PC with no `config.txt`, the card says it
  does nothing there.
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
