# Dashboard, full build changelog

Current file: `dashboard_v9_3_75.py`. Newest entries first. Before 9.3.75 the
file was `asl_dvs_dashboard_v*_<date>.py` and this changelog was
`asl_dvs_dashboard.md`.

## 9.3.75 (2026-10-11)

- New name: `dashboard_v9_3_75.py` (was `asl_dvs_dashboard_v9_3_74_20261011.py`).
  No `asl_dvs_` prefix and no date in the name; the date is in `BUILD_DATE`.
  Versions have three parts (this build already did). Needs instmon 2.40.0 or
  installer 6.7.0 to be seen as the same tool as the old name.
- `--uninstall` also removes the installed copy in `/usr/local/lib/asl_dvs/`
  when its name starts with `dashboard_` (it only knew `asl_dvs_dashboard_`).
  Same fix as Dashboard 9.4.0-pi02w. The installed paths and service
  (`/usr/local/bin/asl_dvs_dashboard.py`, `asl_dvs_dashboard.service`) are
  unchanged.
- Tested: `--uninstall` with mocks for an installed copy under each name (new
  and old Pi02w, new and old full): the link, unit and copy are removed; an
  unrelated name is left alone.


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
