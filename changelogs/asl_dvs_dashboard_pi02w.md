# Dashboard, Pi Zero 2 W build changelog

Current file: `asl_dvs_dashboard_pi02w_v9_3_71_6_20261006.py`. Newest entries first.

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
