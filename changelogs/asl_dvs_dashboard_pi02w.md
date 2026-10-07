# Dashboard, Pi Zero 2 W build changelog

Current file: `asl_dvs_dashboard_pi02w_v9_3_71_12_20261007.py`. Newest entries first.

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
