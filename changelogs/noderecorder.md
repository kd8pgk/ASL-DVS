# Node Recorder changelog

Current file: `noderecorder_v0_17_4_20261113.py`. Newest entries first.

## 0.17.4 (2026-11-13)

Fixes a login that succeeded and then was refused on an https page. This is a release: the server's cookie reading changed.

- **The cause.** Since the session rules moved onto the common model, the cookie on an https page is named with `__Host-` in front. A browser that still held the old cookie of the same name without the prefix (written by an earlier version, good for 12 hours) sent both, and the server read the old one first, so the new login was thrown away: the password was accepted, then every request got 401 and the login screen came back.
- **The fix.** The server now reads the `__Host-` cookie first and uses the old name only when there is no prefixed one. Nothing needs clearing in the browser.
- **Nothing else changes.**

## 0.17.3 (2026-11-13)

HTTPS code moves to the common code (`shared/confio.py`, the `tls_*` functions the other tools will use) and the page answers plain HTTP from this Pi itself. This is a release: the server's connection handling changed.

- **Plain HTTP from the Pi itself is served.** Before, a plain request from the node (Node Controller, Node Talker and instmon read `http://127.0.0.1:8995/api/recorder/status`) was answered with a redirect to https, which those tools cannot follow because the certificate is self-signed, so they could not tell that a recording was running. Now that request is answered. Plain HTTP from any other address still gets a redirect to https.
- **The cookie's Secure flag follows the connection.** A request over https gets the Secure, `__Host-` cookie; a plain request from the Pi itself does not.
- **Nothing else changes.** Same certificate, same port, same `https` setting and fall back to plain HTTP with the note on the login page.

## 0.17.2 (2026-11-13)

Login sessions and lockout follow the common model (`shared/confio.py`, the same code as the other tools will use). This is a release: the server's session rules changed.

- **Tier: standard.** A session ends after 12 hours without use; there is no hard cap. Using the page keeps it alive, and the cookie is renewed about once an hour while in use (before, its life was fixed at the login and the browser dropped it 12 hours after the login even while the page was in use).
- **Any Log Out ends every session.** There is no separate "log out everywhere"; the one Log Out button signs out all browsers.
- **A root password change ends every session.** The page asks for the new password.
- **Safer cookie.** Only a hash of each session's key is kept in memory (at most 50 sessions); on an https page the cookie is named with `__Host-` in front (Secure, no domain).
- **Failed logins wait longer each time.** After 5 mistakes from one address the wait is 5 s, doubling to 300 s; a login that works clears it. Many failures from the internet in 10 minutes also pause internet logins.
- **Nothing else changes.** Same password, same login request.

## 0.17.1 (2026-11-13)

The login screen has an eye button in the password field and now looks the same in every tool. This is a release: the page script changed.

- **One login screen everywhere.** A dark card with the tool's name, one password field, a Log in button and a line for errors, and the licence line at the foot of the page. The "Welcome to the KD8PGK ..." line, the sub-title and the field label are gone, and the field says "Password". Colours, sizes and fonts are the same in every tool (the style comes from one shared block of code); the ids the page scripts use are unchanged.
- **Eye button on the password field.** Press it to see the password in the clear and press it again to hide it. It hides the password again when the form is sent, when the page is hidden or left, and it keeps the cursor in the field. It is drawn with the page's own colours and is a real button with a label ("Show password" / "Hide password") for keyboards and screen readers.
- **Nothing else changes.** The login request, the cookie and the lockout are as before; the password is typed into the same field and is never stored by the page.


## 0.17.0 (2026-11-13)

Slow link for the Node Recorder page, the same idea and the same code as Node Talker 0.10.43, Node Controller 9.3.113-pi02w and instmon 2.95.0: less traffic on the node's Wi-Fi. This is a release: server and page behaviour changed. Not yet measured on a node. Recording, the schedule, the converter and the audio path are not changed.

- **The page is sent gzip-compressed** when the browser accepts it. The compressed page is made once and kept, so it costs the node nothing per load. JSON replies of 600 bytes or more are compressed too (level 5).
- **Unchanged replies cost almost nothing.** Every JSON reply to a GET carries an ETag (the same with and without gzip) and answers 304 when it is unchanged. The page asks that way for the status and the host links and reuses its last reply on a 304. `Cache-Control: no-store` is unchanged; error replies carry no ETag.
- **Slow link switch (Auto, On, Off)** next to the theme switch, in the cookie `asl_slow` shared with Node Talker, Node Controller and instmon. Auto times the status poll; over about 0.4 s the page polls less often (up to 8 times slower) and recovers when the line does. On is at least 6 times slower, Off is normal. A page nobody touched for two minutes polls half as often again while the line is slow.
- **What slows down.** The status poll (1.5 s), the log (3 s), the schedule (4 s) and storage (15 s) polls, the host links (30 s) and the converter's 2 s refresh. A hidden tab does not poll the host links or the status.
- **What does not change.** The 5 s check that the page is still reaching Node Recorder, Disconnect All's own progress poll, and everything on the server side: the schedule, the recordings, the converter and the audio.
- **A light page on a slow link.** With the cookie `on` or a browser that sends `Save-Data: on`, the page is sent without the embedded fonts (text uses the system font).
- **Compatible.** Another tool's `/api/recorder/status` request is a plain GET without `Accept-Encoding` and gets the same plain reply as before (plus an ETag header). An older Node Controller or instmon does not write the cookie; this page's own switch works alone.
- Tests: new `ci/test_noderecorder_slowlink.py` (19 tests: gzip with and without the header and `q=0`, small and error replies, ETag and 304 in every form, the page packed and light, look-alike cookies, the session cookie still read, the poll rules in the page, the 5 s check left alone, and the shared helper run in Node: cookie, factor, cap, recovery, busy, hidden tab, idle).

## 0.16.0 (2026-11-13)

Node Recorder is checked against Node Talker and Node Controller, and the faults Node Talker fixed in 0.10.35 and 0.10.39 are fixed here too. This is a release: tune, connect and disconnect behaviour changed. Most of it matters when Node Controller is not running and Node Recorder tunes DVSwitch itself, which is how a scheduled digital recording is set up then. Not tried on a node.

- **A failed DVSwitch mode switch stops the tune.** When `dvswitch.sh mode` failed it was logged and the tune went on in the old mode, so a scheduled DMR, P25 or NXDN recording could record the wrong thing. The tune now stops with a message.
- **Disconnect reports a failure.** A failed `dvswitch.sh` disconnect, an M17 ini that cannot be written, or a USRP2M17 service that does not restart now fails the disconnect ("... is still tuned: ...") and what was tuned stays shown. A new tune still goes ahead when the old one's teardown fails.
- **Link drops are checked.** After a disconnect Node Recorder reads the link list again (up to 3 s). A node Asterisk still lists is reported as still linked, for a single node, a favorite and Disconnect Links. If the list cannot be read, the disconnect is reported as before.
- **The connect check follows Node Controller and Node Talker.** It waits up to 10 s (was 15), asking Asterisk every half second. It fails at once when the node appears and then drops out of the link list, and after 5 s when the node never appears. A node still connecting after 10 s is reported as still trying.
- **Disconnect All forgets the remembered mode and DMR network,** so the first tune after the services restart sets both again.
- **Waits 220 s for a tune through Node Controller,** up from 100 s, so a tune that takes Node Controller longer is not reported as "not answering".
- **Same sound conversion code.** `_ulaw_byte` is now the same text as in Node Talker and Node Controller; a test checks every sample gives the same byte as before.
- **Checked by the shared-code rule.** Node Recorder is now listed in `shared/confio.py` for `atomic_write`, `ami_credentials`, `firewall_backend`, `open_firewall_port`, `close_firewall_port` and `allmon3_sync`. It already carried them unchanged; `check_repo` now fails if one drifts. `rpt_scan` and `rpt_remove_private` were already listed.
- The Local monitor link choice (`ilink 8`) is kept in every changed path.
- Left as they are on purpose: the login session code (it matches Node Talker, and Node Controller keeps its own), the "tuned" verdict on the tune line, and the Suite Log, which belong to Node Talker's own features.
- Tests: new `ci/test_noderecorder_links.py` (18 tests: the Node Talker cases for the mode switch, the disconnect failures, the drop check and the connect check, the link choice kept, the waits, and the sound conversion over every sample).

## 0.15.0 (2026-11-10)

- **A converted file is kept even if the WAV cannot be deleted.** After the MP3, Opus or FLAC is in place, a failure to delete the WAV no longer counts as a failed conversion. It is logged as a warning, and the next sweep no longer converts it again into a second copy (`name-2.mp3`): a WAV that already has a converted file beside it is deleted instead.
- **The converter thread logs unexpected errors.** An unexpected error while converting is logged, counted as failed (the WAV is kept), and the thread carries on with the next file.
- **A failed recording writer stops taking audio.** After a write error (for example a full drive) frames are no longer queued and counted as dropped every 20 ms; the error is shown as before.
- This is a release, not a cosmetic build.

## 0.14.0 (2026-11-09)

- **Private recording nodes are gone.** This version goes back to the code of 0.5.14 and removes everything 0.6.0 to 0.12.0 added around private nodes numbered 1050 and up: the Private recording nodes card and its Add, Remove and Test tune buttons, the node choice on schedule entries and the runner per node, simultaneous recordings, the digital bridge tuning for entries, the "Tune anyway" question on the Tune button, the load warning, and the extra status fields. A private node (1000-1999) does not connect to the AllStarLink network, so it could never link to a public node; the plan now is a dedicated recorder node, a separate registered node that runs Node Recorder alone.
- **Node 1921 works as in 0.5.14.** It is linked to the node all the time again, so the feed light, the level meter and the Audio row are live at idle and RX gain, gate and CTCSS notch can be set by ear. The rule that linked it only while the main node was recorded (0.11.0) is removed.
- **New: Link choice on schedule entries.** Each entry can link its target **Transceive** (as before) or **Local monitor only** (`ilink 8`), which hears the target but never sends audio to it. A dedicated recorder node should use local monitor only so it can never transmit into the network. It applies to every link Node Recorder makes for the entry: an ASL or EchoLink node, and the digital bridge for DMR, D-STAR, YSF, P25, NXDN, STFU or M17 when Node Recorder tunes it itself. When Node Controller is running and owns the node, it makes the link and the choice does not apply. The schedule list shows "local monitor only" on such entries. Entries saved before have no choice and stay transceive.
- **Kept: a second part after a restart (from 0.10.0).** When a recording ends because the link dropped and the window is still open, Node Recorder links again and records a second part into a new file named like `...-part-2.wav`. It tries every 30 seconds, up to 20 tries in a window, and only while more than 2 minutes of the window are left. "Asterisk is still starting" is tried again the same way. It only happens after something was recorded in that window. The part count is kept across a restart of Node Recorder.
- **One-time cleanup of the old nodes.** If rpt.conf still has private recording nodes added by an older version (marked "noderecorder: private recording node"), the Recorder node card on the Setup tab lists them with a **Remove old private nodes** button, then restart Asterisk once. Only nodes carrying that mark are removed; node 1921 and nodes written by hand are not touched. Leftover per-node schedule state files are deleted when Node Recorder starts. Entries that were saved on a private node now record on the main node (one warning in the log).
- Node Controller and Node Talker keep their questions before tunes and restarts: without the removed status fields they ask only before Reboot, Shutdown and an Asterisk restart, using the busy state, as they did for a main-node recording.
- This is a release, not a cosmetic build.

## 0.12.0 (2026-11-08)

- **Test tune.** The Private recording nodes card on the Setup tab has a new "Test a target" row: pick a schedule entry and a node (Auto uses the entry's own private node if it has one, otherwise the first one that is ready and free) and press **Test tune**. For an ASL or EchoLink entry it links the node to the target in local monitor mode, holds for 3 seconds, checks the link is still up and lets go. For a DMR, D-STAR, YSF, P25, NXDN, STFU or M17 entry it first checks that dvswitch.sh (or USRP2M17), the network, the callsign and the bridge node are there, tunes the bridge to the entry's target, links the node to the bridge, holds, then unlinks and puts the bridge back. Each step is listed with its time, and the number of audio packets that reached the node during the hold is shown (none is normal when nobody is talking).
- **It leaves live use alone.** The test does nothing to a bridge that a live tune or a recording holds, skips a node that is recording and runs one test at a time. Whatever happens, the node is unlinked and the bridge let go at the end.
- **Wording.** A scheduled recording skipped because the bridge is in use says so at the end of its reason ("...; this recording is skipped"); the reason itself is now the same text the test shows.
- A new route, `POST /api/privnodes/test`, takes an entry id and a node.
- This is a release, not a cosmetic build.

## 0.11.0 (2026-11-08)

- **Node 1921 is linked only while the main node is being recorded.** Before, Node Recorder kept 1921 linked to the main node all the time. Now it links it when a main-node recording starts, which is Record now or a schedule entry set to the Main node (or an entry saved before private nodes existed), and unlinks it when that recording ends. Scheduled recordings on private nodes never use it. A left-over link, for example after Node Recorder was stopped mid-recording, is dropped within 20 seconds. If the link drops during a main-node recording it is linked again within 20 seconds, as before.
- **Node Talker is not affected.** When Node Talker is running or owns node 1921 it keeps the link itself, and Node Recorder does not touch it.
- **The feed and level meter are quiet at idle.** The feed light, the RX light and the level meter on the Record card, and the Audio row of the Recorder node card, only show audio while 1921 is linked. At idle the feed light is grey and says "feed idle" instead of red, so tune the RX gain, gate and CTCSS notch during a Record now.
- **Wording.** The Recorder node card says when node 1921 is linked, and its states read "Recording the main node", "Set up and idle" and "Recording, linked".
- The link keeper's check is now a function of its own (`link_keeper_step`) so it can be tested; it behaves as before apart from the rule above.
- This is a release, not a cosmetic build.

## 0.10.0 (2026-11-08)

- **A second part after a restart.** When a recording ends because the link dropped (an Asterisk restart, a reboot, a node going away) and the window is still open, Node Recorder now links again and records a second part into a new file instead of treating the window as finished. It tries every 30 seconds, up to 20 tries in a window, and only while more than 2 minutes of the window are left. While Asterisk is still coming back, "Asterisk does not know node N yet" is tried again the same way. The file of part 2 is named like `20261108-213320_Net-part-2.wav`, part 3 `-part-3`, and so on.
- **Only after something was recorded.** A window whose first connect fails is still marked failed, as before, so a wrong number or an offline node is not tried over and over. Stop recording by hand, a special taking over, a write error and a stopped Node Recorder are not retried either.
- **Specials** are kept until their last part ends, then removed as before.
- **Across a restart of Node Recorder itself** the part count is kept in the lane's state file, so the part after a reboot continues the numbering. Each lane (the main node and every private node) does this on its own.
- This is a release, not a cosmetic build.

## 0.9.0 (2026-11-08)

- **Advance notice in the status.** `/api/recorder/status` has a new `next_bridge`: the soonest enabled digital or M17 entry whose window starts within 30 minutes (`name`, `kind`, `start`, `node`), or an empty object. Node Controller and Node Talker use it to warn before a tune would make that recording skip. Older versions of those tools ignore it.
- Nothing else changes in Node Recorder.
- This is a release, not a cosmetic build.

## 0.8.0 (2026-11-08)

- **DMR, D-STAR, YSF, P25, NXDN, STFU and M17 entries can record on a private node.** The entry's node links to the digital bridge (`ilink 8`, local monitor only) and records, while the main node and node 1921 stay free. Auto picks a private node for these entries too.
- **The bridge is tuned for the window.** When the window opens Node Recorder tunes the bridge to the entry's talkgroup, room or reflector (the recording itself starts 60 seconds in, as for every entry, so the tune has time to settle): DVSwitch mode, DMR network login and tune for the digital modes, the USRP2M17 settings and restart for M17. When the window ends it unlinks and puts the bridge back to idle, unless another recording still holds it or someone else tuned it in the meantime.
- **One tune per bridge.** The digital bridge is shared by every digital mode and M17 has its own, so two entries that overlap on the same bridge must have the same target. Different targets are refused when saving, whatever node they are on, with a message that says a new node would not help. Two entries with the same target can share the bridge.
- **A live tune wins at window start.** If the main node is linked to the bridge with another tune (Tune on this page, Node Controller or Node Talker), the entry is skipped and logged. If the live tune is the same target, the recording shares it and leaves it alone afterwards.
- **A live tune during a recording ends it, and the file is kept.** If the main node is linked to the bridge with a different tune while a recording runs, the recording stops with the result "bridge taken by a live tune" and the bridge is left on the new tune.
- **Tune asks first.** Tuning a digital target on this page while a scheduled recording holds that bridge asks "Tune anyway?", naming the recording and when it ends; Yes stops that recording and keeps what it recorded.
- **Pre-flight checks.** Saving a digital entry on a private node checks that dvswitch.sh (or USRP2M17 and the callsign and reflector for M17), the DMR network and the bridge node are there, and says what is missing. The same checks run again at the window.
- **Load warning.** When the 1-minute load is above 4, the schedule note, a save and a digital window start say so. It never blocks a recording.
- **Status.** `/api/recorder/status` lists the bridges held by recordings (`bridges`) and has `load_warning`, ready for Node Controller and Node Talker to warn before a tune.
- The Tune and Record now buttons are unchanged apart from the question above; their DVSwitch and M17 steps now live in functions the scheduled recordings use too.
- Not verified on a node: that tuning the bridge directly leaves Node Controller's own page state alone, and that `ilink 8` carries the bridge's audio into a private node.
- This is a release, not a cosmetic build.

## 0.7.0 (2026-11-08)

- **Scheduled recordings can run on private nodes, several at once.** Each schedule entry now has a node: **Auto**, **Main node**, or one of the private nodes added on the Setup tab. Auto puts an ASL or EchoLink entry on the first private node that is free at that time; with no private nodes it stays on the main node, as before. Entries on different nodes can overlap and record at the same time, each with its own audio feed, level handling and file. Only entries on the same node conflict, and touching windows are still fine.
- **Link in local monitor mode.** An entry on a private node links that node to the target with `ilink 8` (local monitor only), records, then drops it with `ilink 1`. The main node and node 1921 are not used, so radio comms carry on during the recording. If the link drops, it is linked again; a drop that lasts two checks ends the recording as before.
- **A busy node suggests a new one.** When every private node is busy at that time, saving says to add another private node on the Setup tab (restart Asterisk once, then save again). At five nodes it says to pick another time.
- **Digital entries stay on the main node.** DMR, D-STAR, YSF and M17 entries still record on the main node in this version; a digital entry cannot be given a private node yet.
- **Node waiting for a restart.** An entry on a node Asterisk has not loaded yet fails that window with "restart Asterisk once" and records from the next window once it is loaded.
- **Removing a node** is refused while it is recording or a schedule entry uses it.
- **Status.** `/api/recorder/status` has a new `recordings` list (entry, node, times, file) and `busy` still means the main node is in use. The schedule view lists the private nodes and what is recording on them.
- **Open recordings are protected.** Header repair, conversion and old-file removal skip every recording that is still being written.
- This is a release, not a cosmetic build.

## 0.6.0 (2026-11-08)

- **Private recording nodes.** The Setup tab has a new "Private recording nodes" card. **Add** writes one private node into rpt.conf at a time, as needed: the next free number from 1050 up, with its own USRP port pair, the main node's template and a `[nodes]` line. At most five. Asterisk needs one restart for a new node to load; the node then stays. **Remove** takes out one node, **Remove all** takes out every node Node Recorder added. Only stanzas marked as Node Recorder's are ever removed, and node 1921 is not touched by this card.
- **Numbers and ports in use are skipped.** A number is skipped when rpt.conf already has a `[node]`, a `[functionsNODE]` or a `[nodes]` line for it, or when it is the main node, node 1921 or a digital bridge node (1999, 1917 or the ones set on the Digital card). A port is skipped when any `rxchannel = USRP/...` already uses it.
- **Shared code.** The rpt.conf scan, number and port picking, and add and remove of a marked stanza live in `shared/confio.py` (`rpt_scan`, `rpt_next_free`, `rpt_pick_ports`, `rpt_template`, `rpt_add_private`, `rpt_remove_private`) and are copied unchanged into this file.
- This version only sets the nodes up. Scheduled recordings use them from 0.7.0.
- This is a release, not a cosmetic build.

## 0.5.14 (2026-11-07)

- **Schedule windows can touch.** The rule that windows be at least 2 minutes apart is gone: back-to-back windows are allowed. Each scheduled recording starts 60 seconds after its window opens and stops 60 seconds before it closes, so two windows that meet leave a one-minute gap for the node to change over. Overlapping windows are still refused. The dry run uses the same timing. Record now is not affected.
- **Scheduled slots are at least 3 minutes long.** A scheduled entry shorter than 3 minutes is refused with a message.
- **Offline banner.** When Node Recorder stops answering, a red banner says so. The page checks `/api/health` every 5 seconds and hides the banner when the server answers again.
- This is a release, not a cosmetic build.

## 0.5.13 (2026-11-07)

- **One Schedule list.** The Setup tab no longer has its own copy of the schedule list. The Schedule tab's card is the only list, and it folds like the other cards. Its note about 2-minute windows is removed.
- This is a release, not a cosmetic build.

## 0.5.12 (2026-11-05)

- **Node Recorder plays no audio.** The live audio stream the page never used (`/api/listen`, a copy of Node Talker's listen feature) is removed, with the listener slots behind it and the `max_listeners` and `public_listen` settings. Node Recorder now only receives the node's audio and writes it to recordings; nothing is sent out to a listener. A node whose saved settings still hold the two removed keys keeps working: they are ignored.
- **Status is for logged-in users only.** `public_listen` used to let anyone read `/api/status` without a login; with it gone, that route always needs a login. The status fields `listeners`, `listener_list` and `max_listeners` are gone too. Programs on the Pi still get the recording status from the local route as before.
- The unused Listen and volume styling from the Node Talker copy is removed from the page.
- Recording, Record now, schedules and the level meter are unchanged.
- This is a release, not a cosmetic build.

## 0.5.11 (2026-11-05)

- **Record now is named after the current tune, whoever made it.** It looks at what the main node is linked to when you press Record now (an ASL node linked from anywhere, or a DMR, D-STAR, YSF or M17 tune through Node Controller or Node Recorder) and uses that as the recording's name, for example `ASL Node 1234` or `DMR TGIF 3100`. The name is on the Record card and in the file name. With nothing tuned it is "Record now". It is taken once, when recording starts, so a later link change does not rename or stop it. The Schedule form's name is no longer used by Record now.
- This is a release, not a cosmetic build.

## 0.5.10 (2026-11-05)

- **Record now works again.** Since 0.5.8 it ignored the link but still checked the Schedule form's target, so with the form empty it stopped with "Type or pick a node, talkgroup, room or reflector first" and never started. Record now no longer looks at the form's target at all: it only uses the form's name (or "Record now") and format. It records the current link, with or without one.
- This is a release, not a cosmetic build.

## 0.5.9.1 (2026-11-05)

- **Wording only.** The Connect tab is now called Schedule: its tab button and the two notes that pointed to it (the Schedule card note on the Setup tab and the Digital card note). The Tune card's Connect and Disconnect buttons are unchanged.
- This is a cosmetic build, not a release. The file name is unchanged.

## 0.5.9 (2026-11-05)

- **Schedule list in order.** Entries are sorted by when they next run: a recording running now is first, then the rest by day and time (Mon 09:00 before Tue 08:00). Regular entries whose window has already run today are at the bottom until their next day. A disabled entry keeps its place by its next time, so it returns to the schedule at that time and stays off. Specials with no window left sit at the very bottom.
- **Dividers.** A line separates each entry, and done entries are dimmed; disabled entries are shown in italics. The order is set on the server (`schedule_view`), so the Connect and Setup lists match.
- The "Next" label now shows the next time for a disabled entry too.
- This is a release, not a cosmetic build.

## 0.5.8 (2026-11-05)

- **Record now records the current link.** It no longer tunes to the target set in the Schedule form and does not drop the link when it stops: it records the audio that is up now, as it is. It keeps going through link changes; the 4 hour limit and the save on Stop are unchanged. It is not started while a scheduled recording is due or running.
- **Stop recording stops everything**, scheduled or Record now. A scheduled window in progress is marked done when you press Stop, so it does not start again after the stop. What was recorded is saved as before.
- Includes the layout moves from 0.5.7.1 (Tune card to the top of Record, Schedule list to the bottom of Connect, Storage to Setup).
- This is a release, not a cosmetic build.

## 0.5.7.1 (2026-11-05)

- **Layout only.** The Tune card moves from the Connect tab to the top of the Record tab, with its styles scoped to that tab. The Schedule card (the list of recordings, with Dry run, Edit and Remove) moves from the Record tab to the bottom of the Connect tab, after Disconnect All. The Storage card moves from the Record tab to the Setup tab, below Links. Element ids are unchanged, so the code that fills each card is the same.
- The Connect tab now loads the schedule list when it opens, since the list moved there; the Record tab still loads it for its Record now and Stop buttons.
- This is a cosmetic build, not a release. Not on the stable or testing channels until it is released.

## 0.5.7 (2026-11-05)

- **The suite-log hook from 0.5.6 is removed.** instmon already collects Node Recorder's log lines from the journal (as `journal:noderecorder`), with its rate limit and repeat folding. The 0.5.6 hook wrote a second copy of each success, warning and error, and put the level and message inside `data`, where instmon's viewer and level filter do not look, so those rows showed blank. Node Recorder no longer carries the shared suite-log functions, and `shared/confio.py` no longer lists it for them.
- **Correction to 0.5.6:** the raw check covers the clean-up stage only. With high-pass, automatic level, gate and notch off and gain 0, the clean-up passes each frame through unchanged. The audio hub can still drop frames under load and fills gaps with silence, so a recording is not a bit-exact copy of the node's audio.
- Otherwise the code is the same as 0.5.5. Tests: `ci/test_noderecorder_raw.py` (3 checks, the raw clean-up path).
- This is a release, not a cosmetic build.

## 0.5.6 (2026-11-05)

- **Suite log holds its lock for the whole write.** The shared `suitelog_append` (in `shared/confio.py`) wrote a row without the lock and checked the segment size after, so concurrent writers could push a segment past its limit before it was rotated. The lock is now held across the write and the rotation. This fixes an intermittent failure of the suite-log test in `ci/test_ci.py`.
- **Suite log.** Node Recorder writes its warnings, errors and successes to the shared suite log, as Node Talker does, when instmon's suite log is on (the flag file). Off by default; with the flag off nothing is written. Rows are `kind: "log"` with `src: "noderecorder"`. The suite-log functions are the shared copy in `shared/confio.py`, now listed for Node Recorder too.
- **Raw baseline check.** With its clean-up settings off (high-pass, automatic level, gate, notch, gain 0), Node Recorder's PCM path passes audio through bit for bit. A test checks this, so the baseline Node Talker is compared against stays raw.
- Tests: `ci/test_noderecorder_raw.py` (6 checks).
- This is a release, not a cosmetic build.

## 0.5.5 (2026-11-05)

- **Time zone for the schedule.** The Schedule a recording card has a Time zone list: the Pi's clock (the default, as before), UTC, or any zone such as America/New_York. Every schedule, special and Record now window follows it, and the schedule's "now" line says which it is. Stored as `schedule_tz`. Changing it moves when existing entries run, so the card says so when it is saved.
- **24-hour time in 15-minute steps.** From and To are now an hour list (00 to 23) and a minute list (00, 15, 30, 45) instead of the phone's time picker, so the times are always 24-hour. An entry saved earlier with another minute keeps it when edited.
- Recording file names and the log keep the Pi's own clock.

## 0.5.4 (2026-11-05)

- **CTCSS notch on what is recorded.** A new setting, "CTCSS notch (Hz)" on the RX card, removes one sub-audible tone from the recording: enter the tone the radio sends (for example 100.0); 0 is off, and it is off by default. It cuts about 40 dB at the tone and leaves voice unchanged (checked at 150 Hz and 1 kHz). Stored as `rx_notch_hz`, 60 to 300 Hz. It is the same notch as in Node Talker 0.10.12.
- **PCM is the default recording format.** New schedules and Record now record PCM unless u-law is picked. With Convert on (the default), the PCM recording becomes an MP3 when it ends and the WAV is deleted; if the conversion fails the WAV is kept. Schedules saved with u-law keep it.
- **MP3 quality as close to PCM as it gets.** The default quality is now 96 kbps (was 32), and 96 and 128 kbps are new choices. Measured on 8 kHz voice against the PCM recording: 32 kbps 15 dB signal to error (audibly coded), 64 kbps 42 dB, 96 kbps 44 dB, 128 kbps and up no better than 96. 96 kbps is about 0.7 MB a minute (the PCM WAV is about 0.9 MB). A node that already saved a quality keeps it: pick 96 kbps in the Convert card to use the new setting.
- shine keeps the 8 kHz rate, where 64 kbps is the top MP3 rate, so it uses 64 kbps when 96 or 128 is picked.
- No audio tests are added to Node Recorder.

## 0.5.3 (2026-11-04)

- **Record now and Stop recording on the Record card.** Record now starts a recording by hand, using the target and format set in the Connect tab's schedule form, and it runs until Stop recording is pressed. It stops by itself after 4 hours. Stop recording ends the recording in progress: what was recorded is saved, the link is dropped, and the scheduled window does not start again. Only one recording can run at a time, and a manual start is refused while a scheduled window is due. New routes `POST /api/recording/start` and `POST /api/recording/stop`.
- **Removing a scheduled recording that is recording stops it.** Before, Remove was refused while the entry was recording. Now the recording is stopped by hand, saved, and the entry is deleted.
- **Days are check boxes.** The Day drop-down on the schedule form is seven check boxes (Sun to Sat), so any mix of days can be picked. At least one must be ticked.
- **Schedule tables fit the page.** Each recording takes two lines (name and target, then days, window, format and next time), and its buttons (Dry run, on/off, Edit, Remove) sit on a row of their own under it.
- **Specials.** A schedule entry is now a Regular (weekly, as before) or a Special (one time, on a date). Tick "Special (one time)" on the Schedule a recording card and pick the date. A special takes over from a recording that is running: the regular's first part is saved and its window resumes after the special ends, as a new file. While a special's window is on, a regular does not start over it. A special runs once and is then removed; if the Pi was off for its window it is removed and reported as missed. Two specials that overlap are refused when saved; a special may overlap a regular. Stopping a special by hand also removes it.
- This is a release, not a cosmetic build.

## 0.5.2 (2026-11-04)

- **A chatty encoder cannot stall a conversion.** An encoder that writes a lot to its error output used to block until the job timed out (up to two hours). Its error output now goes to a temporary file, so the conversion runs to the end. When an encoder fails, the message carries the encoder's own error text.
- **Retention leaves a recording that is being converted alone.** Before, the oldest-first cleanup could delete the WAV that the conversion was reading, and the conversion then reported "could not finish" although the MP3 had been written. Such a recording is skipped until it is converted.
- **shine: correct header for PCM recordings.** The RIFF size written in front of a PCM recording was twice the audio length plus 36. Now it is 36 plus the audio length, as for the data chunk.
- **The Setup tab stops starting encoders every 2 s.** The encoder version shown in the Convert card is worked out once per encoder binary and kept until the binary changes, instead of running `--version` on every refresh.
- This is a release, not a cosmetic build.

## 0.5.1 (2026-11-04)

- **A late start cannot leave a recording open.** A window whose start runs past its 15 s limit is now stopped properly: the sequence stops whatever the recorder opened late, so the next window can start. Before, the late recording stayed open with nothing to stop it, and every later window failed with "a recording is already open" until a restart.
- **A slow drive cannot leave a writer running.** Stopping no longer depends on a stop message that can be dropped when the queue is full. The writer finishes once it has written what is queued and closes the file. If the drive is so slow that the stop is not finished within 20 s, the recording is kept and the window reports it; the next window waits until the old file has closed, then converts it.
- This is a release, not a cosmetic build.

## 0.5.0 (2026-11-04)

- **Recordings are compressed after they are made.** When a recording ends, Node Recorder turns the WAV into a smaller file and then deletes the WAV. If the conversion fails, or the encoder is not installed, the WAV is kept. The work runs at the lowest priority (`nice -n 19`), one file at a time, so it does not disturb the node. u-law recordings are decoded to 16-bit audio on the way in.
- **Setup tab, new Convert card.** Tick or untick the conversion, pick the quality (24, 32, 48 or 64 kbps; 32 is about 14 MB an hour) and choose the encoder. Each option shows why you would pick it, its apt package, its file type and whether it is installed. ffmpeg is not offered: it is a very large install for this job.
  - **lame** (MP3, the default): about 1 MB, well tested on the Pi, plays everywhere; resampled to 16 kHz mono.
  - **sox** (MP3): needs the extra `libsox-fmt-mp3` package; choose it if sox is already on the node.
  - **shine** (MP3, `shineenc`): the lightest on the CPU of the Pi Zero 2 W, but it keeps 8 kHz so a few players may not play it, and it is not in every repository.
  - **opusenc** (Opus, `opus-tools`): much smaller files for the same voice quality; Pibrary plays `.opus` but not every phone does.
  - **flac** (FLAC): lossless, about half the size of the WAV; the quality setting does not apply.
- **Install button and terminal.** Each encoder that is not installed has an Install button that runs `apt-get update` and `apt-get install` for its package and shows the output live in a terminal box on the card. It needs a network connection and runs one install at a time. When an install finishes, recordings that were left as WAV files are converted. New routes `GET /api/convert` and `POST /api/convert/install`.
- **Leftovers are picked up.** At start-up and before each window, any WAV that is not the open recording (for example after a power cut, once its header is repaired) is converted too.
- **Retention and counts include the new files.** The MB limit, the oldest-first removal and the Storage card's file count cover `.mp3`, `.opus` and `.flac` as well as `.wav`. Pibrary lists and plays all of them.
- New settings: `record_convert` (default on), `record_encoder` (default `lame`), `record_kbps` (default 32).
- This is a release, not a cosmetic build.

## 0.4.0 (2026-11-02)

- **Phase 4: recordings are scheduled from the page.** The Connect tab has a new Schedule card. Pick a mode and the card shows only that mode's fields: Node (ASL), Number (EchoLink), Talkgroup and Network (DMR), Talkgroup (STFU, P25, NXDN), Reflector (YSF), Reflector and Module (D-STAR, M17). Choose the days from a drop-down (every day, Mon-Fri, Sat and Sun, or one day), the start and end times, the format (u-law or PCM) and whether it is on, then press **Set**. The result is added to the schedule, or the card says what is wrong, for example which two entries overlap.
- **Favorites are picked from Node Talker and Node Controller.** The Favorite drop-down lists the favorites of the chosen mode from Node Talker's favorites file and from Node Controller's list, in two groups. Picking one copies its values into the card; changing the favorite later in Node Talker or Node Controller does not change the entry. Node Recorder only reads those files and never writes to them. A DMR favorite needs its network in this tool's own DMR list (Setup, Digital card; **Copy from Node Controller** fills it); the card says so if it is missing.
- **The schedule is managed in Setup.** A new Schedule card lists every entry with an On box, Edit (loads it back into the Connect card), Dry run and Remove. The Record tab keeps its read-only list.
- **The favorites section is gone.** Setup no longer has a Favorites card or its file download and upload, the Connect tab no longer has its own favorite to connect, and the Tune card no longer has a Save button. Tune and Disconnect All stay. The routes behind them (`/api/favorites`, `/api/favorites-file`, `/api/connect`, `/api/disconnect`, `/api/tune/save`, `/api/dash-favorites`) are removed; the Tune card gets its modes and networks from the new `/api/tune-info`. New route `/api/schedule/sources`.
- A D-STAR reflector is shown and saved as the reflector plus its module (for example REF001 and C).
- This is a release, not a cosmetic build.

## 0.3.0 (2026-11-02)

- **Phase 3: it records.** Scheduled windows now connect, record, stop and disconnect for real. Turn `schedule_dry_run` on to walk the steps without connecting or recording. Each recording is one WAV file named `YYYYMMDD-HHMMSS_<entry name>.wav`, 8 kHz mono: u-law (about 29 MB an hour) or PCM (about 58 MB an hour), as the entry says. The audio is what Node Recorder's receive chain makes of the node's audio (300 Hz cut, auto level, gate and gain, as set on the RX card), with silence written between transmissions so a file is as long as its window.
- **Files are safe against interruptions.** A separate writer thread does the disk work, so a slow drive cannot hold up the audio. The file is flushed and synced every 10 s and its header refreshed every 10 s. After a power cut Node Recorder repairs the header of any recording that was not closed (at start-up and before each window), so Pibrary plays the whole file. A stopping Node Recorder closes the file cleanly first.
- **Write failures end the window cleanly.** If the disk fills or the USB drive is unplugged during a recording, the window stops, the file is kept, the link is dropped and the result shows as "could not write the file".
- **Where recordings go.** The Setup tab has a Storage card with a Recordings folder and a limit in MB. Empty means automatic, in this order: the Pibrary library if it is on a USB drive, any other mounted USB drive (`<drive>/pibrary/audio/recordings`), then the Pibrary library (or `/srv/pibrary/media`) on the SD card. The folder is `audio/recordings` inside the library, so Pibrary lists and plays the recordings in its Audio tab. Pibrary's settings file is only read. If both a Recordings folder and a Pibrary library are set and differ, the Record tab shows both paths and which is used.
- **Recordings never go to the SD card while a USB drive is mounted.** If the Recordings folder is on the SD card and a USB drive is mounted, the window does not start and the Record tab says why.
- **Space and the limit.** Before a window starts Node Recorder removes the oldest of its own recordings (only files with its own naming) until the new window fits under the MB limit, then checks the drive has room for the whole window plus 50 MB. If it does not, the window does not start.
- **Status for other tools.** `GET /api/recorder/status` (answered only to programs on this Pi, never through a proxy) gives the state (idle, connecting, recording, stopping, disconnecting), a `busy` flag that is true during a real window, the entry name, start and end, seconds elapsed and the file name. It is kept in memory only. New route `/api/storage`.
- This is a release, not a cosmetic build.

## 0.2.0 (2026-11-02)

- **Phase 2: the schedule and its state machine.** Node Recorder now keeps a schedule and walks each window through the same steps every time: connect, start recording, stop recording, disconnect. **Recording itself is not built yet**, so until the recording engine arrives every window runs as a dry run: the steps are walked and logged, but nothing is connected and no audio is written. The Record tab says so.
- **Schedule entries.** Each entry has a name, the days of the week (Sunday to Saturday, one or several, or every day), a start and an end time, a target (mode and the node, talkgroup, reflector or network, copied in when the entry is saved, with no live link to where it came from), a recording format (u-law or PCM) and an enabled flag. An end time earlier than the start runs past midnight. A window is under 24 hours.
- **Overlaps are refused.** Two enabled windows must be at least 2 minutes apart, so the first can disconnect before the next connects. This counts across midnight and across the end of the week, and a window that runs into its own next day is refused too. A refused save says which entries clash.
- **Stored safely.** The schedule is `schedule.json` in the settings folder, written atomically (up to 40 entries). If the file cannot be read, a copy is kept as `schedule.json.bad`, the schedule shows as empty with the reason, and saving is refused until it is fixed, so a damaged file is never overwritten.
- **Each step has a time limit and a way out.** Connect 120 s, start 15 s, stop 30 s, disconnect 60 s. If connecting fails, nothing is recorded, the failure is logged and the node is left disconnected. If starting fails, the link is dropped. If the link drops during the recording (two checks, 5 s apart, both find it gone), the recording is stopped cleanly and the rest is cleaned up. If Asterisk cannot say whether the link is up, the recording carries on. A stopping Node Recorder ends the window cleanly first.
- **Restart and power-loss recovery.** A small state file remembers which window is open and which have finished. After a restart inside an open window the window resumes; one that ended while Node Recorder was down is logged as interrupted or missed, once. A window is never run twice, and an entry saved after its window ended is not reported missed. No history is written to disk.
- **Dry run on request.** The Record tab lists the schedule (days, window, target, format, next run) with a Dry run button on each entry that shows every step. New settings: `schedule_dry_run`. New routes: `/api/schedule`, `/api/schedule/set`, `/api/schedule/remove`, `/api/schedule/dryrun`.
- The page for adding and editing entries comes in a later build; this one stores and runs them.
- This is a release, not a cosmetic build.

## 0.1.0 (2026-11-02)

- **New tool, phase 1 (strip and skeleton).** Node Recorder is forked from Node Talker 0.10.1. It is receive-only and will record on a schedule; this build has no recording yet. The web page and status are on port 8995, with Connect, Record and Setup tabs.
- **Audio comes from the private node 1921.** The tool listens for the USRP audio Asterisk sends to node 1921 (UDP 34018) and reads the key-up flag from each packet. When Node Talker is running it owns the port and node, so Node Recorder listens on `127.0.0.1:9995/udp` instead, where Node Talker 0.10.1 and later forward the same packets. Node Recorder lets go of 34018 within a few seconds of Node Talker starting. There is no `outstreamcmd` line and no `--feed` hook.
- **Node 1921 is shared.** Without Node Talker, Setup adds node 1921 to rpt.conf (the same stanza Node Talker writes, with its own note line) and keeps it linked to the main node. With Node Talker it leaves the node alone. Uninstalling hands the node to Node Talker when it is installed, and removes it otherwise.
- **Kept from Node Talker:** the receive chain (300 Hz cut, auto level, gate), the Connect tab and Tune card, Disconnect All, the System, Links, Digital and Favorites cards, login and the log.
- **Removed from Node Talker:** transmit and push-to-talk, the phone patch, the tone test, the balance run, kerchunk logging, receive health, the Audio check, the Listen tab and the `outstreamcmd` feed. The Listen tab is replaced by a Record tab that shows the feed, the level and the node.
- **Files:** settings in `/etc/asl_dvs/noderecorder/noderecorder.conf`; service `noderecorder.service`; program `/usr/local/bin/noderecorder.py`.
- This is a release, not a cosmetic build.
