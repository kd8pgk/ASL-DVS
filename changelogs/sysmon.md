# SysMon, full build changelog

Current file: `sysmon_v6_13_94_20261028.py`. Newest entries first.

## 6.13.94 (2026-10-28)

- **Find in every editor.** The file editor (Asterisk, Allmon3, DVSwitch and app config files, and unit files) has a Find bar in its header, next to Save. The All Visible Config Files view (ASL and DVS AllConf) has one next to Copy All. The Edit tab's Pinned Services box, the DVSwitch.ini (STFU) editor, the M17 editor and the Zello editor have one under the text. Type to search; Enter and Shift+Enter (or ▲ Prev and ▼ Next) step through matches; the count shows "2 of 5" or "No matches"; Escape clears it. The bar clears each time a file opens.
- **Find scrolls to the match.** The first match, and each Next or Prev match, scrolls into view. The position is measured from the text, so wrapped lines and the padding above the file text do not put the match off screen.
- **File editor on top.** The editor does not scroll as a whole, so the header with the file name, Find, Save and Copy stays pinned above the path bar and the file text, and opens above the offline bar and the other panels. Toast messages still show above it.

## 6.13.93 (2026-10-27)

- **The port opens on install and closes on uninstall.** Install checks that SysMon's port (9999, or the port in its config) is open in the firewall (ufw or firewalld) and opens it if it is not. With no active firewall nothing changes. Uninstall removes the service first and closes the port last. The check is shared through `firewall_backend`, `open_firewall_port` and `close_firewall_port` in `shared/confio.py`, kept identical in each tool and checked by the repo check.

## 6.13.92 (2026-10-27)

- **Config files are written the same safe way in every tool.** Every write goes through one shared function (`atomic_write`, kept identical in each tool and checked by the repo check): a private temp file with a random name in the same folder, fsync, then a rename. An edited file keeps its owner and mode. A symlink at the path is replaced, not followed.

## 6.13.91 (2026-10-27)

- **KD8PGK on every splash.** The login screen reads "Welcome to the KD8PGK System Monitor" on every node. The callsign is no longer read from the node's config. Cosmetic in effect; the release is for the change in code.

## 6.13.90 (2026-10-27)

- **Log Out in the header.** A Log Out button sits beside the uptime, as in Node Controller. It signs out the same way as the Logout button on the command bar.
- **Node Controller.** The nav button that opens Node Controller reads "Node Controller" (was "Node Control").

## 6.13.89 (2026-10-27)

- **Login splash.** The login screen opens with "Welcome to the KD8PGK System Monitor" above the login card, and the CC BY-NC 4.0 license at the bottom. The callsign comes from `/etc/asl_dvs/asl_dvs.conf` when the page is served, so the page reads it on every load.

## 6.13.88.2 (2026-10-27)

- **Header and page names.** The header, the login card and the page title read "System Monitor". Cosmetic only; no change in behaviour.
- The header sub-line drops "Node Control". The ASL-DVS tab keeps its name.

## 6.13.88.1 (2026-10-27)

- **Smaller type and the shared look.** The text is set in Readex Pro (built into the page), with one size scale for the whole page, so the tabs, buttons and cards fit more on screen. The header matches Node Control: the sub-line now starts with "Node Control". The Global Actions bar wraps on a phone instead of running off the right edge. The ASL-DVS tab keeps its name. Cosmetic only; no change in behaviour. Readex Pro is Copyright 2019 The Readex Pro Project Authors, under the SIL Open Font License 1.1.

## 6.13.88 (2026-10-19)

- **Code cleanup, no change in behaviour.** Reboot and Shut down share one
  handler instead of two copies of the same code, and the troubleshooting checks run their
  commands through the same helper as the rest of SysMon instead of its own
  identical copy.

## 6.13.87 (2026-10-19)

The full-build port of 6.13.74-pi02w: a **Node Listen** card at the bottom of the
ASL-DVS tab. The code is the same as the fork's. SysMon does all the checks itself;
Node Listen is not changed and any version of it works.

- **Service:** whether `nodelisten.service` is running, and the version from its
  `/api/health` page (no login needed).
- **Listen ports** (from `ss`), with the ports read from
  `/etc/asl_dvs/nodelisten.conf` (Node Listen's defaults when it is missing): the web
  port (8993/tcp), node audio in (6200/udp on 127.0.0.1), push-to-talk audio back
  from node 1921 (34018/udp), and, when push-to-talk is on, Asterisk's 32018/udp. A
  port held by another program shows as a port conflict.
- **Connection checks:** the web page answers on 127.0.0.1 (and on HTTPS when HTTPS
  is set); the main node's `outstreamcmd` hook points at Node Listen's UDP port; the
  feeder process is running; node 1921's `rxchannel` and whether it is linked to the
  main node (`rpt lstats`); internet access (`allow_wan`), with a warning when it is
  on without HTTPS.
- **Connected browsers:** each address connected to the web port, marked LAN,
  internet or this Pi, with a **Disconnect** button (`ss -K`; their page tries again
  in 3 s if they are still listening).
- **Buttons:** Restart nodelisten, Unlink 1921 (Node Listen links it again within
  20 s while it runs), Open Node Listen, Refresh and Copy. A node without Node
  Listen shows "not installed".
- The Self-check covers `/api/nodelisten` too.

## 6.13.86 (2026-10-14)

The full-build port of Pi Zero 2 W SysMons 6.13.69-pi02w and 6.13.70-pi02w
(reliability plan, Stages 3 and 6). The code is the same as the fork's.

- **Connection limits that refuse instead of queue.** Past 24 open
  connections, or 12 from one address, a new connection is refused at once,
  with no thread. Before, each extra connection got a thread that waited on a
  semaphore. Refusals are logged at most once a minute.
- **Node Health card** at the top of the Hardware tab (`/api/health`, login
  needed, cached 30 s), included in "Copy hardware report":
  - **Clock sync.** The Troubleshoot tab's Clock check stays; this one keeps
    both builds alike.
  - **Out-of-memory kills** since boot, with the last victims.
  - **Memory:** available and swap.
  - **Disk and logs:** root free space, journal size, `/var/log` size.
  - **Memory per service:** state, memory and restart count for the suite,
    Asterisk and the bridges.
  - Thresholds as in 6.13.70-pi02w. They fit the larger Pis too: the memory
    limits are absolute (64 MB / 32 MB), so they warn only when memory is
    really short.
- **A systemd watchdog that checks the web server.** "ready" is sent once the
  web server listens. "alive" is sent only while the background poll ran in
  the last 180 s and SysMon's own new `/healthz` (no login) answered in the
  last 25 s. Before, the poll sent both, so a hung web server went unnoticed,
  and one poll pass slower than 30 s got SysMon killed.
- Ported with the fork's own diff. Nine of ten parts applied as they were;
  the route table had different neighbours (the Reg routes), so those two
  lines were placed by hand.
- Tested: the fork's tests run against this file:
  - connection limits (4)
  - health checks and heartbeat (9), with a real server and a real notify
    socket
  - the Hardware tab in headless Chromium: the card first, no script errors,
    no horizontal scroll at 390 px
  - `ci/check_repo.py`

## 6.13.85 (2026-10-14)

Text only. Two hints in the Console's **Half tunnel** checks said "Use Undo now on
44helper's Firewall tab". 44helper 0.0.196 moved the half tunnel card to its Full
Tunnel tab, so the hints now say that. Nothing else changes.

## 6.13.84 (2026-10-13)

Console -> Troubleshooting: a new **Half tunnel** group, between Network and
Dashboard. It has the outside-view checks from 44helper's half-tunnel card (checks
1, 4, 5, 6 and 11–14), so a node with the half tunnel on can be checked from
SysMon. They are read-only and need no 44helper. Run all and Copy report include
them.

- Each result shows the half-tunnel state (not set up, test running, or on)
  and the 44 address from wg0.conf.
- **Tunnel is up:** the last WireGuard handshake. Under 3 minutes passes, never
  is a warning, older fails. No wg0.conf at all is info.
- **Internet uses the normal link:** where `ip route get 1.1.1.1` goes. Into wg0
  fails with the half tunnel on, and is info without it (a full tunnel).
- **DNS works:** looks up allstarlink.org and register.allstarlink.org.
- **LAN tools respond:** the Dashboard, SysMon, instmon and 44helper ports that are
  listening must answer, and their replies to the LAN gateway must leave by the
  LAN link, not wg0.
- **DVSwitch connected:** MMDVM_Bridge / Analog_Bridge running, and the DMR login
  lines in the newest MMDVM_Bridge log.
- **usrp2m17 connected:** the service is running.
- **ASL registration shows your 44 address:** `rpt show registrations` (or `iax2
  show registry`). A missing 44 address is a warning, since it can take a few
  minutes. Without a half tunnel it is info.
- **EchoLink logged in:** the directory list from `echolink dbdump`. Empty is a
  warning. EchoLink off is info.
- 44helper's own wait state shows as a warning here, and its skip as info.
- Tested: mocked unit tests for every result of each check (pass, warn, fail,
  info), the three half-tunnel states and the catalog order. `py_compile` and
  `pyflakes` are clean.

## 6.13.83 (2026-10-13)

Easier to read: the grey-blue text is white, successes are green and failures are
red, from the Pi Zero 2 W build (6.13.67.17-pi02w), plus the tabs only the full
build has. Only text colours change. The ASL-DVS tab is unchanged.

- **Grey-blue to white `#ffffff`:**
  - `--text` (was `#d0dff0`)
  - the typed-in `#9fb4cc`, `#c8d8e8`, `#5a7898`, `#3a5278`, `#cfe3ff`,
    `#2a4060` and `#c98a92`
  - on the full-only tabs: the network console text (was `#d8e0f0`) and its
    pills (was `#8aa0c0`)
- **Failures to bright red `--red`:**
  - the radio dialog errors, panel load errors, the alert bar and the shutdown
    message (they were `#f88`, `#ff6b6b` or `#ffb0b8`)
  - the network console's error line (was `#ff6b6b`)
- **Hardware checks and Security rows:** the dark detail text is bright green,
  amber and red (was `#007a50`, `#7a5800` and `#7a2030`).
- **Network console results** use the standard colours: pass is green (was
  `#3ddc84`), warn is amber (was `#ffb020`) and fail is red (was `#ff5c5c`).
- Results that were already green or red are unchanged.
- **Tested:**
  - The page in headless Chromium, before and after: body text
    `rgb(255,255,255)`; success details and console pass `rgb(0,255,176)`; failure
    details and console errors `rgb(255,61,90)`; no script errors.
  - The ASL-DVS mentions are unchanged in number.
  - `node --check` on the page JavaScript.

## 6.13.82 (2026-10-13)

SysMon checks the USRP pairs on its own, as the Pi Zero 2 W build does since
6.13.67.16-pi02w. 44helper's Port check can now be verified on a full-build node.

- **DVSwitch tab**, Analog_Bridge card: a new **USRP pair with rpt.conf** row.
  - Pass when an rpt.conf node has `rxchannel = USRP/127.0.0.1:rxPort:txPort`.
  - Fail when the node's ports don't mirror `[USRP]`, or no node uses them.
- **New command-line flag** `--usrp-pairs`: prints the pairing of rpt.conf,
  Analog_Bridge.ini and USRP2M17.ini as one `USRP-PAIRS-JSON:` line, then exits.
  44helper's **Verify with SysMon** button runs it.
- The code is the same as the Pi Zero 2 W build's.
- Tested:
  - The same mock cases as the Pi Zero 2 W build: SysMon and 44helper agreed in
    every case.
  - The new DVSwitch row.
  - The flag with no config files.

## 6.13.81 (2026-10-13)

SysMon's ASL-DVS tab is named **ASL-DVS** again (it was "Node Controller" in
6.13.80): the tab button, its Edit-page checkbox and the "Hide from ASL-DVS tab"
labels. The tab is an exception to the "Node Controller" naming. Nothing else
changes. The same change is in the Pi Zero 2 W build (6.13.67.15-pi02w).

## 6.13.80 (2026-10-13)

The Phone tab and D-Star card fixes from an audit against Dashboard 9.3.77 and
ircDDBGateway's source, and the "Node Controller" naming. The same change is in the Pi Zero 2 W build (6.13.67.14-pi02w).

- Page title, logo and login heading say SysMon / SYSMON (no "ASL-DVS"). The
  ASL-DVS tab is now the **Node Controller** tab (same tab, same id, so saved tab
  choices still apply); the Edit page's "ASL-DVS Config Files" is "Config Files".
  System names and saved settings (paths, markers, the Services group names in
  `sysmon.conf`) are unchanged.
- D-Star card:
  - A setting left out of `/etc/ircddbgateway` now counts as ircDDBGateway's
    default: `ircddbEnabled`, `ircddbEnabled2` and `dextraEnabled` are on unless
    the file turns them off. Before, a missing key showed FAIL or WARN.
  - ircDDB counts as on when any of `ircddbEnabled`, `ircddbEnabled2`-`4` is on.
    Off is now WARN (reflectors still work; gateway callsigns can't be found).
  - `dextraEnabled` off is now FAIL: ircDDBGateway refuses gateway links and XRF
    reflectors without it.
  - The remote-control hint no longer says it keeps the module (the tune path
    keeps it too). It says what remote control adds: the dashboard hears whether a
    link was accepted, and links work with a fixed reconnect.
- Phone tab:
  - Dialing rules shows an extension network's real dial line
    (`PJSIP/${EXTEN}@...`), not its Test call number.
  - Phone networks shows Hams Over IP and AmateurWire by name.
  - Health checks: one row per helper script, with the codes it serves and what
    breaks without it: the hang-up script (`*62`, `*65`; it ends every phone call,
    not only incoming ones), and new rows for the radio dial script (`*61`) and the
    radio tone script (`*980`-`*982`). The radio tone codes row lists the codes in
    `rpt.conf` (the old text named `*983`-`*987`, removed in Dashboard 9.3.71.3).
  - The checks for the removed Hams Over IP AllStar Link feature are gone.
  - Router advice: forwarding is no longer the default instruction. Signing in
    usually keeps the SIP port open; forward only if incoming calls don't arrive
    (and the audio range if audio is one-way), since forwarding opens Asterisk to
    the internet.
  - Autopatch modules: `func_callerid.so` (caller ID and trusted numbers) is
    listed, and `chan_iax2.so` is always listed and locked, because the phone nodes
    link to the radio node over IAX2. A `noload` of `chan_iax2.so` is flagged.
  - Router test: the incoming result names the real SIP port; Call audio says it
    covers SIP calls only; the incoming hint fits any provider. The no-PIN warning
    names the network instead of its id.
- Tested against the files Dashboard 9.3.77 writes for a Hams Over IP and a
  VoIP.ms network (helper scripts missing, present and world-writable), four
  `/etc/ircddbgateway` cases (keys left out, DExtra off, ircDDB off, only
  ircDDB 2 on), and the page in headless Chromium (no script errors).

## 6.13.79 (2026-10-12)

Knows the Dashboard by its new name, `nodecontrol`, as well as the old
`asl_dvs_dashboard`. The same change is in the Pi Zero 2 W build (6.13.67.13-pi02w).

- Services tab: the pinned Dashboard row follows whichever unit is installed.
  A saved list that still says `asl_dvs_dashboard.service` keeps working; it
  shows `nodecontrol.service` once the Dashboard has been renamed (on SysMon's
  next start; Full Update restarts SysMon after the Dashboard). The default list
  for a new node names `nodecontrol.service`.
- Security tab: the Dashboard login check finds the Dashboard through
  `nodecontrol.service` or `/usr/local/bin/nodecontrol.py` first, and the
  root/non-root unit lists include both names.
- Troubleshoot tab: the Dashboard's file and version are found at
  `/usr/local/bin/nodecontrol.py` and through whichever unit is installed.
- Tested with mocks: the pinned row with neither unit, the old one, the new
  one and both; the default list.

## 6.13.78 (2026-10-12)

Standard install layout (same as instmon 2.40.0, wifimon 5.29 and 44helper
0.0.180). The same change is in the Pi Zero 2 W build (6.13.67.12-pi02w).

- `--install` copies the file to `/usr/local/lib/asl_dvs/sysmon/` (was
  `/usr/local/lib/asl_dvs_sysmon/`) and points `/usr/local/bin/sysmon.py` at it.
  The link is swapped in with one rename, so the path is never missing. Any
  other version in the new folder is removed, and so are the SysMon files (and
  their compiled copies) in the old folder, which is then removed if empty.
  Anything else in the old folder is left alone. Running `--install` through the
  link changes nothing. The unit is unchanged.
- `--uninstall` also removes the empty lib folder, `/usr/local/lib/asl_dvs/` if
  that is then empty, and the old folder if it is empty.
- Tested with mocks against a temporary root: a fresh install, an install over
  the old folder and over the new layout, reinstall through the link, uninstall,
  and an old folder that holds a file that isn't SysMon's.

## 6.13.77 (2026-10-11)

- M17 tab, sample `USRP2M17.ini` stanza: when `[M17 Network]` has no `LocalPort`,
  the sample now fills in `17010`, the port the full Dashboard writes from 9.3.74.
  It used to fill in `32010`, which is the P25 bridge's port. Same fix as SysMon
  Pi02w 6.13.67.10.
- Tested: the sample stanza with an empty config and with a set `LocalPort`.

## 6.13.76 (2026-10-11)

- Config editor **Thresholds**: "CPU warn %" and "RSS warn MiB" now do
  something. In a service's detail panel the CPU and memory badges turn amber
  with a ⚠ when the service is at or over them. Before, both were saved but
  never read, and the badges were always plain.
- All four thresholds (with NRestart warn and crit) now load from the saved
  config when the page opens. Before, NRestart warn and crit were only picked up
  after a Save in the editor, so after a reload the badges used the built-in
  3 and 10 whatever was saved. A blank or non-numeric value keeps the default.
- Same fix as SysMon Pi02w 6.13.67.11.
- Tested in headless Chromium with the API mocked: badges below, at and over each
  threshold, loaded from config on page start, and changed by a Save.

## 6.13.75 (2026-10-11)

- Firewall tab, **Enable ufw** now asks first, like Disable ufw. The prompt says
  that incoming traffic without an allow rule will be blocked, this page and the
  Dashboard included.
- Before it turns ufw on, SysMon checks the rules ufw has (`ufw show added`) for
  an allow or limit rule on the SSH port (from `sshd_config`, 22 if unset; `ssh`
  and `OpenSSH` count for 22). If there is none it adds `ufw allow <port>/tcp`
  first, and says so in the result. If adding that rule fails, ufw is not
  enabled. Before, Enable ran `ufw --force enable` straight away, which could
  shut out SSH on a node with no rules.
- Tested: 14 checks of the rule matching (port, profile names, `from ... port`,
  udp-only and deny rules, a non-default SSH port) and the enable flow with
  `ufw` mocked.

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
