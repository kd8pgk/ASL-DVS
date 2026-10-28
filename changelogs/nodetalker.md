# Node Talker changelog

Current file: `nodetalker_v0_9_47_20261028.py`. Before 0.6.0 the tool was Node Listen, the file was `nodelisten_v….py` and this log was `nodelisten.md`. Newest entries first.

## 0.9.47 (2026-10-28)

Key-up polling now works the way Node Controller's does:

- **The AMI login comes from `/etc/asterisk/manager.conf`.** Node Talker used the user and password in `/etc/allmon3/allmon3.ini`, so a node without Allmon3 had no key-up state. It now reads the first manager user that has a secret (not `[general]`), the same way Node Controller does, through `ami_credentials` in `shared/confio.py`. It connects only to `127.0.0.1:5038`; the host and port in `allmon3.ini` are no longer used, so the password can't be sent to another machine. `NODETALKER_ALLMON3` is replaced by `NODETALKER_AMI_CONF`.
- **Polling runs on demand.** It checks the manager once at start, then closes the connection. It polls (4 times a second) while audio is heard or a transmit is tried, and for 20 seconds after, and while someone is keyed. A key-up that was already under way when polling began is not logged, because its start time is unknown.
- **A refused login is not retried every 10 seconds.** Node Talker tries again only when the user or password in `manager.conf` changes.
- **Replies are capped.** A reply over 1 MB, or no answer to an action within 5 seconds, drops the connection.

## 0.9.46 (2026-10-28)

- **The page opens on the Connect tab.** Each time Node Talker starts or the page is loaded again, it opens on Connect instead of the tab that was last open. The last tab is no longer remembered.

## 0.9.45 (2026-10-27)

- **The port opens on install and closes on uninstall.** Install checks that Node Talker's port (8993, or the port in its config) is open in the firewall (ufw or firewalld) and opens it if it is not. With no active firewall nothing changes. Uninstall removes the service first and closes the port last. The check is shared through `firewall_backend`, `open_firewall_port` and `close_firewall_port` in `shared/confio.py`, kept identical in each tool and checked by the repo check.

## 0.9.44 (2026-10-27)

- **Config files are written the same safe way in every tool.** Every write goes through one shared function (`atomic_write`, kept identical in each tool and checked by the repo check): a private temp file with a random name in the same folder, fsync, then a rename. An edited file keeps its owner and mode. A symlink at the path is replaced, not followed.

## 0.9.43 (2026-10-27)

Fixes for the listen graphs:

- **The spectrum graph starts again when the page comes back.** When the
  browser was minimized or the tab was hidden, the spectrum stopped drawing
  while the sound kept playing, and it stayed frozen until you relinked. The
  page now restarts the graph whenever it becomes visible again.

## 0.9.42 (2026-10-27)

Fixes from an audit of the page's JavaScript:

- **A failed connect no longer wipes the Tune card.** When Connect on the
  Tune card failed, the page went back to the Connect tab and reset the card:
  the error disappeared at once and the node, talkgroup or reflector you had
  typed or picked was cleared (with the DMR "add the network" question, its
  explanation went too). The error and your choice now stay. A favorite that
  fails to connect also stays selected instead of jumping back to the first.
- **The microphone can't be left open after push-to-talk.** Letting go while
  the microphone was still opening (most likely the first time, or while the
  phone asks for the microphone), or pressing again straight away, could
  leave the microphone on in the background until the next transmission. It
  is now closed.

## 0.9.41 (2026-10-27)

Fixes from a code audit:

- **Favorites whose label starts with `[`, `#` or `;` are no longer lost.**
  The favorites file read a label like `[Club] repeater` as a section header,
  so it and the favorites after it disappeared, and one like `#1 hub` as a
  comment. A line with a `|` is now always a favorite, and a label can no
  longer start with `#` or `;` (they are dropped when you save). Files
  already saved with a `[` label read correctly again.
- **A favorite's number must be 0 or more.** `-1` picked the last favorite
  (Connect, Disconnect); it now asks you to pick a favorite.
- **A gain of `inf` in the settings** now gets the usual "-12 to +12 dB"
  error instead of an error page.
- **A hand-edited burst log** with a bad row no longer breaks the Kerchunks
  card; the row is skipped.

## 0.9.40 (2026-10-26)

- **Text sliders go down to 10 px** on the Tune, Listen and Setup size
  sections (they stopped at 12 px).
- **Text first.** The Tune card's sliders are now Text, then Height.
- **No Gap slider.** The Gap slider did nothing on the Connect tab (a fixed
  6 px rule overrode it), so it is gone. The Tune card's gap is now 2 px. A gap
  saved by an older version is ignored.

## 0.9.39.1 (2026-10-26)

- **Links card follows the Setup text size.** The table on the Setup tab's
  Links card (and its "No links" line) now grows and shrinks with the Setup
  tab's Text slider. At the default 15 px it looks as before.

## 0.9.39 (2026-10-26)

- **One set of size functions.** The Tune, Listen and Setup size sliders now run
  on the same load, apply, reset and wiring code, driven by one table. What the
  sliders do, their saved values and their ids are unchanged.

## 0.9.38 (2026-10-26)

- **Setup headings back to their spacing.** The Setup card's headings have
  their 0.9.35 margins again. 0.9.36 had dropped them for the default spacing.
- **Spelling on screen.** Three words are spelled the US way like the rest of
  the page: "labeled bursts" (Kerchunks), "recognizes" (Listen's keyup message)
  and "Analyzing" (tone test stage).

## 0.9.37 (2026-10-26)

- **Size sliders for the Listen and Setup tabs.** The Setup card has a
  "Listen tab on this phone" and a "Setup tab on this phone" section, like the
  Tune card's. Each has **Text** (the tab's text size) and **Height**: on Listen
  the height of the push-to-talk and Mark kerchunk buttons, on Setup the height
  of its buttons. **Default size** puts a tab back to 15 px text and the default
  heights. Each tab's size is saved in its own browser entry (`nlListenSize`,
  `nlSetupSize`), so the Tune card's sizes are not changed.

## 0.9.36 (2026-10-26)

- **Connect.** The Disconnect All button shows its title only; the list of
  services under it is gone (the confirmation still names them). The line under
  the Tune card (`Tuned: ...`) is centred.
- **Listen.** The red "display max" line across the top of the spectrum is
  removed. The clip line on the level meter stays.
- **Setup.** The System card's buttons (Reboot, Shutdown) are centred, and the
  card has no Copy all button. The headings in the Setup card use the default
  heading spacing instead of their own margins.
- **Favorites.** The RX dB and TX dB gain fields open the full keyboard, so a
  minus sign can be typed (gains run from -12 to +12 dB). Numeric keypads have
  no minus key.
- **Expanded test.** The show/hide arrow on the card heading sits at the right
  edge.

## 0.9.35 (2026-10-26)

- **Mark kerchunk on the Listen tab.** While a kerchunk test runs (and you are
  logged in), the push-to-talk button splits into **Hold to talk** and an amber
  **Mark kerchunk** button beside it, so you can mark a key-up without leaving
  Listen. It works like the button on the Kerchunks card: it marks the key-up
  that just ended (within 5 s), or the next one if one is still going. The
  result shows under the button for 4 s. When no test runs, push-to-talk uses
  the full width as before.
- The status the Listen tab polls says whether a test is running (`kc_test`).

## 0.9.34 (2026-10-26)

- **Busy is fail-safe with key-ups.** When Node Talker reads key-ups from
  Asterisk, busy (and the activity light) now come on if Asterisk reports a
  key-up *or* audio is heard (a burst over 0.4 s). In 0.9.33 busy followed
  key-ups only, so if Asterisk did not report a linked node keying, net traffic
  would not block Talk. Kerchunk logging still uses key-ups only.

## 0.9.33 (2026-10-26)

- **Kerchunks from Asterisk's key-up state.** Node Talker logs in to the
  Asterisk manager (AMI) with the node's login from `/etc/allmon3/allmon3.ini`
  (the `[node]` stanza: host, port, user, pass) and asks for the node's state
  (`RptStatus` / `XStat`) four times a second. A key-up is the local receiver
  (`RPT_RXKEYED`) or a linked node keying (`RPT_ALINKS`); Node Talker's own TX
  node is left out.
- **New kerchunk rule with key-ups:** a key-up shorter than 3 s with less audio
  than the cut-off. Carrier-only key-ups, which pass little or no audio, are now
  caught. Courtesy tones, IDs and telemetry fall outside key-ups and are not
  logged. Each row records the source, the keyed time, the audio time and who
  keyed (`local` or the node number), and the report counts kerchunks by node.
- **Busy follows key-ups.** With key-ups, "Don't transmit while the node is
  busy" and the activity light follow the keyed state (plus the 0.6 s hold), so
  busy starts at the key-up, with no 0.4 s wait.
- **Fallback.** Without `allmon3.ini`, a login, or a manager that answers,
  Node Talker uses audio as before. The Kerchunks card says which source it is
  using and why key-ups are not available. The log says when key-ups start and
  stop.
- **Card.** Bars are sized by keyed time when the source is key-ups; the dashed
  cut-off is drawn only for the audio source. List rows show who keyed and for
  how long.
- The burst log gains three columns (`source`, `keyed_secs`, `who`). Older
  five-column logs still read.

## 0.9.32 (2026-10-26)

- **Our own transmissions are not logged as bursts.** Audio heard while Node
  Talker is keyed, within 1 s after it unkeys, or while the tone test runs is
  left out of the burst log, the kerchunk count, the test and the Listen drop.
- **The burst log is written off the audio thread.** Appending a burst, the
  200 KB trim and labels from Mark kerchunk now go through a writer thread, so a
  slow SD card write can no longer hold up the audio pump (and Listen).
- **One clip level everywhere.** The red line on the Audio check strips, the red
  line on the spectrum's level meter and the report's "Samples at full scale"
  count all use -0.5 dBFS (the strips and meter drew -1 dBFS before). The lines
  stay inside the graph at the top edge.
- **Spectrum label.** The red line at the top of the spectrum is labelled
  "display max": it is the top of the analyser's range (-25 dB per bin), not
  clipping.

## 0.9.31.1 (2026-10-26)

- **Burst list in a sub-card.** The list of bursts on the Kerchunks card is in
  its own sub-card, hidden by default, with a Show / Hide button and a count of
  bursts. Layout only: nothing else changes. Cosmetic build, not for stable.

## 0.9.31 (2026-10-26)

- **The kerchunk test counts only what you mark.** 0.9.30 recorded every burst
  on the node during a test, so a test sample could be other stations' traffic.
  Now press **Mark kerchunk** after each key-up you make. Only marked bursts are
  counted in the test, and each one is labelled Kerchunk in the log, which
  feeds the learned cut-off. The button is enabled only while a test runs.
- A mark applies to the burst that just ended (within 5 s), or to the next burst
  if one is still going. Marks are refused when no test is running.
- The test summary and the copied JSON count marked bursts only.

## 0.9.30 (2026-10-26)

- **Busy and activity use the fixed 0.4 s again.** 0.9.27 to 0.9.29 used the
  learned cut-off here, so a learned 1.5 s stopped real short transmissions from
  setting busy, and Talk was not blocked. The learned cut-off now only sets the
  kerchunk flag, the card and the Listen drop.
- **Learning is capped at 0.8 s.** A split above that is not used, and the card
  says so (the default stays).
- **Copy JSON** (Kerchunks card) copies the whole report: cut-off, label counts,
  the longest kerchunk label and the shortest real label, whether they overlap,
  how many labels the cut-off gets wrong, every labelled length, and the last
  300 bursts. If the clipboard refuses, the JSON is selected in a box below.
- **Reset** (Kerchunks card, after a confirm) moves the log to a timestamped
  `.bak` file, clears the labels, puts the cut-off back to 0.4 s and stops a test.
- **Kerchunk test** (Start test / Stop test, with minutes, 15 by default, 1 to
  60). While it runs the card shows a countdown and the bursts and kerchunks so
  far. It stops by itself when the time is up. Its bursts appear in the report
  and the copied JSON.
- `/api/kerchunks/test/start`, `/api/kerchunks/test/stop` and
  `/api/kerchunks/reset` added. `/api/kerchunks` returns the report and the test.

## 0.9.29 (2026-10-26)

- **Spectrum has a dB axis and a level meter.** The left axis labels the
  spectrum from -100 to -40 dB (the analyser's own range). A meter on the right
  shows the peak level in dBFS from 0 to -60, with a peak hold that stays for
  1 s. The meter's red line is at -1 dBFS.
- **Clip line across the spectrum.** A solid red line at the top of the bars
  marks where clipping begins: the analyser saturates there, at -25 dB.
- **Clip line across the Audio check strips.** The RX strip (and the sent and
  your-level strips) has a solid red line at -1 dBFS, drawn over the bars, and
  dBFS labels on the right. The bars are coloured by level on the spectrum's
  colour ramp, no longer one teal colour. The old red band behind the bars is
  gone, since the line replaces it.
- Client-side only (the page script and CSS). The server is not changed.

## 0.9.28 (2026-10-26)

- **Drop kerchunks from Listen** (Setup tab, under "Don't transmit while the
  node is busy"). Off, or a delay of 0.1 s to 1.0 s. Listen waits that long
  before it plays audio. A burst that has ended before its audio would play is
  a kerchunk under the learned cut-off, and its audio is not played. Every
  delay adds the same lag to Listen. A kerchunk is known to be over only after
  its length plus 0.6 s, so a short delay drops only the shortest kerchunks.
  At 1.0 s, kerchunks up to 0.4 s are dropped in full. Default: off.
- The listen feed to every listener now goes through that delay queue (it is
  empty when the setting is off, so the feed is unchanged).
- Fix: the RX level calculation could raise a math-domain error when the filter
  output decayed to denormal values after a loud burst. The level is now floored
  at -300 dB, which fits the existing -120 dB floor, so the pump keeps running.
- `kerchunk_delay_ms` added to the config.

## 0.9.27 (2026-10-26)

- **Kerchunks are tracked.** Every burst of node audio of 0.1 s or more is
  logged to `nodetalker_bursts.csv` in the config folder (time, length, peak
  level, kerchunk or not, your label). The file is trimmed to the last 2000
  bursts, and it is rewritten at 200 KB. A kerchunk is written to the log, too.
- **Kerchunks card** (Kerchunks, between Phone and Log). A bar graph of the last
  100 bursts: each bar's height is its length, the dashed line is the cut-off,
  and labelled bursts are drawn in full colour. Below it is the list, with
  Kerchunk and Real buttons to label each burst (press again to clear it), and
  today's and total kerchunk counts.
- **Kerchunks are learned from the labels.** The cut-off starts at 0.4 s. Once
  there are six labels with both kinds present, Node Talker fits the cut-off
  between them (one length threshold, limited to 0.15 to 1.5 s). If the best cut
  still gets more than a third of the labels wrong, the 0.4 s default stays.
  Activity uses the learned cut-off from then on.
- `/api/kerchunks` and `/api/kerchunks/label` added.

## 0.9.26 (2026-10-26)

- **Kerchunks no longer make the node look busy.** A kerchunk is a brief key-up
  with no speech. Node Talker treated any short burst of audio above the activity
  level as activity, so a kerchunk on the node blocked Talk (Don't transmit while
  the node is busy) and showed the channel as active. A burst now counts as
  activity only after it has lasted 0.4 s (`KERCHUNK_MAX_SEC`). Shorter bursts are
  ignored for busy and activity; the audio still goes to Listen. Bursts with gaps
  under 0.6 s stay one burst.

## 0.9.25 (2026-10-26)

- **Disconnect All** (Connect tab, under the Tune card). An emergency general
  reset. After one confirm it:
  1. stops a transmission from Node Talker, a tone test, and an expanded test
     or audio check on this page;
  2. drops what is tuned, the same as Disconnect on the Tune card (through Node
     Controller when it runs). It waits at most 5 s for this, and if Asterisk
     doesn't answer it goes on;
  3. restarts md380-emu, Analog_Bridge, MMDVM_Bridge, USRP2M17 and Asterisk,
     one at a time in that order. A service that isn't installed is skipped,
     and one that fails doesn't stop the rest.
- The button shows each step as it runs ("MMDVM_Bridge... (5 of 7)"), then what
  was restarted, what failed and what isn't installed. Each step goes to the log.
  Under its label it lists the services this node has. It needs the login, like
  Restart Asterisk, and refuses while a reset is already running.
- It fills the width of the screen. Its height (44-64 px) and text size follow
  the screen size, from a small phone in landscape to a desktop.
- `/api/disconnect-all` and `/api/disconnect-all/status` added.

## 0.9.24 (2026-10-26)

- **The Expanded test card opens.** In 0.9.23 its header showed on the Setup
  tab, but tapping it did nothing, so the test, its options and Start could not
  be reached. The card was missing from the page's list of fold-out cards. It
  now opens and closes like the others.

## 0.9.23 (2026-10-26)

- **Expanded test** (Setup tab, new card above the Audio check). Tick the live audio check, the node tone test, or both; they run one after the other, tone first. Live length is 2, 5, 10 or 15 min.
- **Balance automatically** (optional). Between runs it changes one setting at a time, applied live. Live check: it takes the highest-ranked Audio check suggestion that has an Apply change (the same ones the Apply buttons offer) and applies it only after the channel has been quiet for 5 s (no audio and no transmission, as the Pi sees it); if the channel stays busy for 2 min, balancing stops without a change. Node tones: it changes RX gain toward a 1 kHz return level (about -19 dBFS RMS), starting from the gain in effect. Each run is scored; a change that makes the score worse is put back and balancing stops. Phone-side mic changes are never balanced automatically. At most three runs per path.
- **Adjust audio levels** is turned on when a balance change needs it (RX gain, TX gain, Listen buffer, TX buffer), and the level settings the change does not set are written with the values that were in effect while it was off, so only the change itself is heard.
- **Restore and Keep.** The settings are saved to `nodetalker_balance.json` in the config folder before the first change. Restore original settings puts them back (also after a restart); Keep changes drops the saved copy. The card shows Restore and Keep while a saved copy exists, checked again each time the card is opened.
- **Tone test limit raised to 2 min** (was 60 s). The tone set itself stays well under it: 12 tones of 2 s with both station IDs come to about 40 s.
- **Tone test refuses to key while the node is linked or something is tuned.** The link to the TX node (1921) is expected; any other link, a DVSwitch or M17 bridge included, or a tuned talkgroup or reflector, refuses the test. It checks before starting and every 5 s during the test, and stops if a link appears. The checks run beside the transmission, so a slow answer from Asterisk or Node Controller never holds up the tones.
- **Load guard** for both paths: CPU, memory, throttling and temperature are checked every second during a tone test and every 3 s during the expanded test. Limits: CPU above 90 % of all cores for 10 s; free memory below the larger of 40 MB or 10 % of RAM; Pi throttling or temperature at 80 C (Pi readings only where the Pi reports them). A breach stops the test, puts the original settings back, and says why. The tone test report shows the CPU and memory peaks.
- `/api/load`, `/api/balance`, `/api/balance/snapshot`, `/api/balance/restore` and `/api/balance/keep` added.

## 0.9.22 (2026-10-25)

- **0.9.21 brought into the repo** (it came in as a file, not through the repo). Comments and docstrings are stripped and the history below is moved here.
- `ptt_rx_gap` stays off by default (0.9.21 had turned it on).
- Pi health (`pi`) is part of the status only for a logged-in client, not the public status.
- Tone test: the Stop route is local network only like Start, and a test that would run past the TX time-out less 5 s is refused.

Entries 0.9.0 to 0.9.21 below were kept in the file header and carry no dates of their own; the 0.7 and 0.8 series have no written history.

## 0.9.21 (2026-10-25)

- Settings that can't be used right now are grayed out, with the reason in a note under the section: in app audio (Node Talker Mobile) the page playback options, the page's mic processing, Mic test, Test through the node, output / mic picking, the headset button and Start check; without the https:// page the microphone options; browser-unsupported echo cancel / noise suppression / auto gain; the Voice filter while Radio voice is on; the level fields while Adjust audio levels is off. Phone card: rows the app doesn't use are marked, and inside the app a Node Talker Mobile section shows the audio mode and version, plus the app's own settings when the app provides audioInfo().

## 0.9.20 (2026-10-25)

- Review fixes. Audio check: Download report works again (the page used an undefined VERSION). RX cleanup: the squelch-tail gate counts a frame as noise only when its samples one and two apart are both unrelated (flat hiss), so steady tones and loud "s" sounds are no longer muted; the check's squelch-tail count uses the same test. When the gate opens it keeps the 40 ms before the opening and fades in. TX: a gap repeats the last frame faded out instead of a hard cut, and the frame after a gap fades in. Phone mic: longer down-sampling filter (flat to 3 kHz, less hiss folding back) and a steeper Voice filter. Listen: a burst that runs far ahead is dropped until playback is back at the Listen buffer, instead of playing on top of queued audio; Disconnect drops audio already queued. Listen line reads the bridge settings at most every 5 s. Copy all hides password fields. Audio check: suggestions use the table's own limits. Tone test: the processed column is measured 80 ms later when the gate is on (its delay). Faster gain and WebSocket unmasking on the Pi.

## 0.9.19 (2026-10-25)

- Listen tab: the feed button label is two lines in a smaller font (Connect / feed, Disconnect / feed).

## 0.9.18 (2026-10-25)

- Listen tab: the feed button reads Connect feed / Disconnect feed.

## 0.9.17 (2026-10-25)

- Listen line: the DVSwitch and M17 status is read only when a bridge is linked to the main node.

## 0.9.16 (2026-10-25)

- Listen line: with no ASL node linked, a tuned DVSwitch or M17 bridge is the primary (its talkgroup or reflector, with the mode badge) instead of No ASL node linked.

## 0.9.15 (2026-10-25)

- Listen line shows the ASL node the main node is linked to (its number from rpt lstats, named from the favorites or astdb.txt). TX node 1921 and bridges 1999/1917 are infrastructure, so they never become the primary; a tuned bridge (DVSwitch or M17) follows as a tag. Favorites editor counter fixed.

## 0.9.14 (2026-10-25)

- Audio check suggestions: ordered by how much audio they affect (lost or distorted audio first, then levels, then noise and filters). At most two changes carry Apply at once; the rest are marked Later. Level suggestions use the report table's targets and need 5 s of speech before they are made.

## 0.9.13 (2026-10-25)

- Listen line under PTT shows the live link, not the Connect or Tune selection. It reads the main node's links; a DVSwitch or M17 bridge is labelled from its own status. Shows Not connected, Node unreachable, or Bridge linked, nothing tuned. The badge is sized to the line's font.

## 0.9.12 (2026-10-25)

- Settings tab: every card has a Copy all button at its foot. It copies the whole card as plain text, including folded sections and the values of its fields. Audio check's button is renamed to match.

## 0.9.11 (2026-10-25)

- Node cross-check: rpt stats parser now reads the 'since system initialization' keyup count and TX time (HH:MM:SS:mmm). It used to read the 'today' count, which resets at midnight.

## 0.9.10 (2026-10-25)

- Audio check: Copy whole card moved to the Start check row so it is visible before a check runs (it was inside the report area, which stays hidden until a check finishes).

## 0.9.9 (2026-10-25)

- Page layout: Favorites (with the favorites file) and Digital (with DMR networks) are now cards of their own, each with its own save button; Setup keeps node settings, Save and Restart. Audio check has a Copy whole card button that copies the card as plain text.

## 0.9.8 (2026-10-25)

- Tone test: the busy check looked at any packet from the node, which the node sends continuously, so the test always refused with 'channel busy'. It now uses audio above the activity level only.

## 0.9.7 (2026-10-25)

- Audio check (Phase 4, page only): Download report saves the current report to this phone as a JSON file. Compare with a saved report loads such a file and compares it with the current check; nothing is kept on the Pi. Compare with last check is unchanged.

## 0.9.6 (2026-10-25)

- Audio check (Phase 3): Pi temperature and throttling sampled every 10 s (in memory, shown in the report); PTT round trip from the page and key-to-first-audio on the Pi (from the unkeyed event); node cross-check comparing rpt stats keyups with the phone's transmissions (/api/node/counters). The rpt stats format is parsed defensively and shows raw lines when it is not recognised.

## 0.9.5 (2026-10-25)

- Audio check (Phase 2): per-minute data (speech level, noise floor, Pi load, dropouts) for up to 15 minutes, shown as a bar strip in the report. Run totals are unchanged. Saved runs in the older format are migrated on load instead of discarded.

## 0.9.4 (2026-10-25)

- Audio check (Phase 1, client only): full-scale sample rows for RX and TX; dropouts split into under 0.1 s, 0.1-0.5 s and over 0.5 s, with silent seconds; queue resets counted separately; screen kept awake during a check (Wake Lock, with a warning if it can't be held); optional "talk now" prompts every 2 minutes from 0:30 (on by default).

## 0.9.3 (2026-10-25)

- Tone test in the web page: Audio check card, Tone test section (length, tone list, run and stop). Shows the report as a per-tone table with raw, after-cleanup and cleanup-effect columns, the usable band and warnings. Reloads the last in-memory report when the Setup tab opens.

## 0.9.2 (2026-10-25)

- Tone test: reports are no longer saved to disk. The report stays in memory until the next test. Removed /api/tonetest/list and /api/tonetest/report (test results are not logged).

## 0.9.1 (2026-10-25)

- Tone test: station ID (Morse "DE <callsign>") sent at the start and end, using the callsign from Setup; the test refuses to key without one. Each finished run is saved as JSON in CONFIG_DIR/nodetalker_tonetests (newest 50 kept). New GET endpoints: /api/tonetest/list and /api/tonetest/report?name=. Start ID also sets the delay figure.

## 0.9.0 (2026-10-25)

- Tone test (Pi side): raw and processed RX taps in the audio pump (inactive unless a test runs); tone sequence keyed through the Talker; Goertzel analysis with frequency search; /api/tonetest/start, /stop and /status (start is LAN-only and needs login).

## 0.6.12 (2026-10-21)

- **Spectrum on the Listen tab is bars only.** The waterfall view is gone,
  and tapping the spectrum no longer switches views; a saved "waterfall"
  choice is ignored. The setting (Setup tab, Playback) still shows or hides
  the spectrum.

## 0.6.11 (2026-10-21)

- **Works with Node Talker for Android 0.3.0 (transmit in the app).** With app
  audio on, push-to-talk goes through the app: it opens the talk channel,
  keys, sends the phone's microphone and unkeys, so the page needs no HTTPS
  for the microphone and a tap-to-talk transmission carries on with the
  screen locked. The page shows the same messages as before (keyed, busy,
  time-out, guard timer) from the node's own answers, and the TX level from
  the app. The page's microphone gain is passed on; its other microphone
  settings (leveler, gate, filter) apply in a browser only.
- In app mode, switching apps or the screen going off keeps a tap-to-talk
  transmission going and unkeys a hold-to-talk one.
- In a browser, or with page audio, nothing changes.

## 0.6.10 (2026-10-21)

- **Works with Node Talker for Android 0.2.0 (app audio).** Inside the app,
  with app audio on, Listen hands receive to the app, which keeps playing
  with the screen locked; the page shows the app's state (connecting,
  listening, reconnecting, paused for a call) and level, a Stop from the
  app's notification turns the page's button back, push-to-talk mutes the
  app's receive and the volume slider sets the app's volume.
- In a browser, or in the app with page audio, nothing changes.

## 0.6.9 (2026-10-21)

- **ASL and EchoLink on the Tune card**, first in the Mode menu.
  - Search as you type (2 characters or more), as in Node Controller: ASL
    searches the AllStar node list (`/var/lib/asterisk/astdb.txt`) by node
    number, call or place; EchoLink searches Asterisk's station list
    (`echolink dbdump`, kept for 5 minutes) by number or call. A number
    alone matches nodes that start with it. Up to 200 matches are listed.
  - A node number can be typed when it isn't found, or the list is missing.
  - Connect links the node as an ASL or EchoLink favorite does, through Node
    Controller when it runs, and checks the link for up to 15 s.
  - LH opens the node's AllStar stats page (ASL). Save adds it to favorites.
  - Disconnect drops the link to the node picked or typed.
  - Bridge nodes and the transmit node are left out of the ASL search and
    refused.
- New API: `GET /api/tune-search?mode=&q=`; `/api/tune` and
  `/api/tune/disconnect` take ASL and EchoLink.

## 0.6.8 (2026-10-21)

- **Tune card** on the Connect tab, after Node Controller's search cards:
  Mode, Network (DMR) or Module (D-STAR, M17), Search, the list, Connect,
  LH and Save on one line (wrapping on a phone), with Disconnect below.
  - The lists come from the files on the Pi that Node Controller reads:
    `YSFHosts.txt`, `P25Hosts.txt`, `NXDNHosts.txt`, `TGList_BM.txt` (STFU),
    the DPlus, DExtra and DCS host lists (D-STAR) and `M17Hosts.json`. Search
    matches every word typed; one match is picked for you.
  - A talkgroup, room or reflector can also be typed when it is not in the
    list, or when the list is missing. DMR has no list: type the talkgroup.
  - Connect tunes through Node Controller when it runs, otherwise on its own,
    the same way a favorite does. A DMR network Node Controller doesn't have
    gets the same "add it / tune this once / cancel" question.
  - LH opens Last Heard for the pick: the network's link for DMR, the
    reflector's own link or its address for the others.
  - Save adds the pick to the favorites (up to 15).
  - Disconnect ends whatever DVSwitch or M17 has tuned, favorite or not; the
    card shows what is tuned.
  - The mode, network, module, search and pick are remembered on the phone.
- **Tune card on this phone** (Setup tab, Settings): sliders for the card's
  gap, height and text size, kept on the phone, with "Default spacing".
- **Links card** moved from the Connect tab to the Setup tab, under System.
- New API: `GET /api/tune-list?mode=`, `POST /api/tune`, `/api/tune/save`,
  `/api/tune/disconnect`. `/api/status` adds `tuned_now`; `/api/favorites`
  adds `net_links`. Node Controller needs no update.

## 0.6.7.1 (2026-10-21)

- **Favorites list on the Connect tab**: text 5% smaller (16px to 15.2px).

## 0.6.7 (2026-10-20)

- **Dashboard favorites list** (Setup, *Favorites*, "From the Dashboard...")
  shows only each favorite's name, as the Connect tab's list does since
  0.6.6.

## 0.6.6 (2026-10-20)

- **Favorites list on the Connect tab** shows only each favorite's name. The
  mode and number still show under it for the one selected.

## 0.6.5 (2026-10-20)

- **System card** at the top of the Setup tab.
  - **Reboot** and **Shutdown**, as in Node Controller: the page asks
    "Reboot the system?" or "Shut down the system?", the Pi answers
    *Rebooting…* or *Shutting down…*, then runs `reboot` or
    `shutdown -h now` 1 s later. Login is required, and each request is
    written to the log.
  - **Quick links** to Allmon3 (`/allmon3`), DVSwitch (`/dvswitch`) and
    Cockpit (port 9090), in Node Controller's style. Each shows only when its
    page answers: the Pi checks them (a page answers with a status below
    400; Cockpit's port accepts a connection) every 30 s. The row is hidden
    when none answers.
- **Header button:** when Node Controller isn't running, it opens InstMon
  (port 8990) if InstMon is running, and is hidden if neither is. The page
  re-checks every 30 s, so it switches without a reload.

## 0.6.4 (2026-10-20)

- **Wait 4 s after receive before talking** (Settings, *Push-to-talk on this
  phone*; off by default).
  - When it's on, push-to-talk is locked while the node receives and for 4 s
    after receive ends.
  - The waterfall or bars show the count, 3, 2, 1, 0, in the upper-right
    corner: a quarter of the width and half the height (1/8 of the space),
    in white at 25 % opacity (75 % see-through).
  - The button reads *Wait...*. Pressing it, tapping it or using the headset
    button says how long is left.
  - **What counts as receive:** the node's RX light (the node's audio
    before any cleanup, the same signal the Pi's own busy lockout uses), plus,
    while listening, the audio as it arrives (above −50 dBFS), which times the
    end exactly. Someone else transmitting from Node Talker counts too.
  - Your own transmission and the 2.5 s after it don't start the wait.
  - With the spectrum hidden, the count shows beside the Talk button.
  - Saved per phone, with the rest of the push-to-talk settings, and backed
    up on the Pi as `ptt_rx_gap`.
- Removed an unused byte counter in the audio input.

## 0.6.3 (2026-10-20)

- **Connect moves to the Listen tab.**
  - Pressing **Connect** on the Connect tab (or answering the add-network
    question) switches to the Listen tab. The line under the Talk button
    reads *Connecting to …* or *Tuning …*.
  - When the link comes up, the result shows there for 8 s.
  - If it fails (refused, no answer after 15 s, the node still trying, or a
    DMR network Node Controller doesn't have), the page goes back to the
    Connect tab with the error, and the add-network question when it
    applies. It does this only if you are still on the Listen tab.
- Disconnect stays on the Connect tab.

## 0.6.2 (2026-10-20)

- **Push-to-talk on this phone** (Settings card): **Hold to talk** (as
  before, the default) or **Tap to talk, tap to stop**.
  - In tap mode, one tap keys and the next tap unkeys. Lifting the finger
    does nothing. A tap within 0.5 s of keying is ignored, so a double tap
    can't key and drop at once.
  - Space or Enter toggle in tap mode, and are held in hold mode.
  - Losing focus or going to the background still unkeys, in both modes.
  - The button label and its screen-reader label follow the mode. While
    talking in tap mode it reads **TALKING · tap to stop** with the seconds left counting down.
- **Guard timer** for tap mode and the headset button's push-to-talk: 30, 60,
  90, 120 or 180 s, 60 s by default.
  - 10 s before the end: two quick short beeps (80 ms at 1 kHz, played only
    on this phone, never into the transmit audio), an amber border and a
    flashing countdown, and a vibration where the browser allows it.
  - At zero it unkeys and says *Guard timer: unkeyed after …*. The Audio
    check counts these with the time-outs.
  - It never runs past the node's TX time-out, and the setting says so when
    the time-out is shorter. The TX time-out and the 1 s dead-man on the Pi
    stay in both modes.
- **Saved on each phone, backed up on the Pi.**
  - **Save on this phone** also writes `ptt_mode` and `ptt_guard_sec` to
    `nodetalker.conf`.
  - A phone with nothing saved (new phone, cleared browser, private window)
    starts from that copy.
  - **Restore from the Pi** puts it back on a phone.
  - The card says where the values came from. The copy on the Pi is the last
    one any phone saved.
  - Older versions ignore the two keys.

## 0.6.1 (2026-10-20)

Solo, Node Talker now connects, disconnects and guards links the way Node
Controller does. With Node Controller running on Node Talker's node, Node
Controller does all of this and Node Talker's guard stays off.

- **One link at a time, everywhere.** Connecting an ASL or EchoLink favorite
  drops every other link first, as Node Controller does. Before, it was
  added next to the existing links.
- **Tuning a digital favorite** drops every link except that mode's bridge
  node. Before, only linked favorites and the other bridge were dropped.
- **Private nodes (1999 and below) have their own rules.**
  - The one-link rule doesn't drop them or count them.
  - The digital bridge nodes are handled by the reaper and watchdog below.
  - Node 1921 is kept by its own keeper.
  - Any other private node (a private hub, a phone node) is left alone.
  - This differs from Node Controller, which also drops a private node that
    isn't one of its bridges.
- **Permanent links** (the `nodes =` line in the node's `rpt.conf` stanza)
  are dropped with `ilink 11`, as in Node Controller. This applies to
  connect, tune and Disconnect.
- **If Asterisk doesn't list the links,** connect and tune change nothing and
  say so. Node Controller instead sends `ilink 6`, which would also drop the
  private nodes.
- **Guard,** every 5 s. It uses Node Controller's thresholds (2 polls, 8 s
  cooldown) and starts once Node Talker has connected or tuned something
  itself. It stops while Node Controller runs on the node, and starts again
  only after the next connect or tune in Node Talker.
  - **Reaper:** a bridge node that is linked but isn't the bridge of what
    Node Talker tuned is dropped.
  - **Watchdog:** the tuned favorite's bridge node is linked again if it
    drops.
  - **Multi-link cleanup:** when more than one public link is up and nothing
    digital is tuned, extra links that are favorites are dropped, keeping the
    one connected last. Other stations' links are left alone, as in Node
    Controller.
- An AllStar link added by DTMF or Allmon while a digital favorite is tuned
  is left up, as in Node Controller.
- Drops are 0.25 s apart, at most 16 per action, as in Node Controller.

## 0.6.0 (2026-10-20)

**Node Listen is now Node Talker**, and with Node Controller on the node,
every mode goes through Node Controller.

- **Through Node Controller.** When Node Controller runs (pi02w 9.3.94 or
  later), DMR, STFU, YSF, P25, NXDN and D-STAR favorites are tuned by Node
  Controller through its local API (`dvs-tune`), as ASL, EchoLink and M17
  already were. The Connect button shows Disconnect for a favorite Node
  Controller tuned (`dvs-status`); Disconnect sends `dvs-disconnect`.
  - **A DMR network Node Controller doesn't have.** The Connect tab asks
    either to **Add it to Node Controller and tune** (`dmr-server-add`, then
    the tune) or to **Tune this once** (Node Controller joins it for this tune
    only and saves nothing), or to Cancel.
  - An older Node Controller without these actions gets "update Node
    Controller". Node Talker never tunes DVSwitch behind a running Node
    Controller.
  - Without Node Controller, Node Talker tunes all three itself, as in 0.5.0.
- **Renamed.** The service, the files and the paths are renamed too:

  | | Was | Now |
  |---|---|---|
  | Service | `nodelisten.service` | `nodetalker.service` |
  | Program | `/usr/local/bin/nodelisten.py`, `/usr/local/lib/asl_dvs/nodelisten/` | `/usr/local/bin/nodetalker.py`, `/usr/local/lib/asl_dvs/nodetalker/` |
  | Settings | `nodelisten.conf` `[nodelisten]` | `nodetalker.conf` `[nodetalker]` |
  | Data | `nodelisten_favorites.conf` and `.json`, `_tuned.json`, `_restore.json`, `_tls/`, `_backups/` | `nodetalker_…` |

  The page title, header, login, lock-screen media info, the messages and the
  logs say Node Talker.
- **Kept working for older tools and versions:**
  - `nodetalker.service` has `Alias=nodelisten.service`.
  - `/usr/local/bin/nodelisten.py` stays as a symlink to `nodetalker.py`.
    The service starts through it, so tools that look for `nodelisten` in
    the process list (the full-build SysMon's port checks) still see it.
    Where that path is some other program's file, it is left alone and the
    service starts as `nodetalker.py`.
  - A plain copy of Node Listen or Node Talker at that path (instmon makes
    one before an install) is turned back into the symlink. If the new
    service doesn't start, the copy is put back.
  - Each old settings or data path is a symlink to the new one.
  - The settings file holds the same settings under both `[nodetalker]` and
    `[nodelisten]`.
  - The full-build SysMon and Node Controller, and Node Listen itself, still
    find the tool and read its port, node and favorites.
  - **`rpt.conf` is not changed.** The audio line still runs
    `/usr/local/bin/nodelisten.py,--feed,…`, and both comment markers
    (`; nodelisten: …`) stay exactly as they are. The full-build SysMon,
    Node Controller (both builds) and Node Listen 0.5.0 recognize them by
    that text. Node Talker recognizes either program name.
- **Install over Node Listen** moves the settings and data, including the
  HTTPS certificate, so browsers keep trusting it.
  - It stops Node Listen and keeps its unit until `nodetalker` has started.
    If `nodetalker` doesn't start, Node Listen is put back and started again.
  - After a Full Update (which runs Node Listen's own uninstall first), the
    `rpt.conf` lines are put back from `nodelisten_restore.json`.
  - A newer file that an older version wrote at an old path wins. An older
    stray file is kept as `….pre-nodetalker`.
- **Uninstall** removes `nodetalker.service`, its alias, both program links
  and `/usr/local/lib/asl_dvs/nodetalker`. It keeps the settings and data.
- **Going back to Node Listen 0.5.0:** run
  `sudo python3 /usr/local/bin/nodetalker.py --uninstall` first. instmon
  2.64.0 and the installer 7.4.0 do this on their own.

## 0.5.0 (2026-10-20)

Node Listen can now run a node on its own, with no Node Controller: its
favorites tune DVSwitch and M17 as well as ASL and EchoLink. The Connect tab
looks and works as before; everything new is on the Setup tab.

- **Up to 15 favorites** (was 10), now also **DMR, STFU, YSF, P25, NXDN and
  D-STAR**. FCS and XLX are not offered.
- **Favorites file in Node Controller's format.** Favorites, DMR networks and
  the digital settings are kept in `/etc/asl_dvs/nodelisten_favorites.conf`
  (mode 0600, because it holds DMR passwords), with the same sections and
  `name|...` lines as `asl_dvs.conf`. The Connect tab lists favorites in file
  order.
  - On first start the favorites in `nodelisten_favorites.json` move into it.
  - The JSON file is kept up to date with only the ASL, EchoLink and M17
    favorites (up to 10), so going back to an older Node Listen stays safe:
    older versions read any favorite they don't know as an ASL node.
- **DMR network list** (Setup tab, Digital card), up to 10:
  `name|password|address:port|url` in `[DMR_SERVERS]`, with each DMR favorite
  in its network's `[DMR_<KEY>]` section.
  - The page never receives a password. An empty password field keeps the
    saved one.
  - Renaming a network keeps its favorites. A network that a favorite uses
    can't be removed.
  - **Copy from Node Controller** adds the Dashboard's networks. Adding a
    Dashboard DMR favorite copies its network too.
- **Solo tuning (Node Controller not running):**
  - **DVSwitch modes:**
    1. Start the mode's gateway (`ysfgateway`, `p25gateway`, `nxdngateway`,
       `ircddbgatewayd`, `stfu`) if it isn't running.
    2. Link the digital bridge node.
    3. `dvswitch.sh tune disconnect`, then `mode <MODE>`.
    4. DMR only: `tune <password>@<address:port>`, skipped when that network
       is already joined.
    5. `tune <tg>`.
    - D-STAR uses Node Controller's tune string (`REF001 C` becomes
      `REF001CL`), and is unlinked first when you leave it.
  - **M17:** writes `USRP2M17.ini` the way Node Controller does, with the
    address from `M17Hosts.json` (checking that the module is published),
    restarts `usrp2m17` and links the M17 bridge node.
  - **One digital favorite on the air at a time.** Tuning one drops linked ASL
    and EchoLink favorites and the other bridge. Connecting an ASL or EchoLink
    favorite releases a digital tune. Disconnect unlinks the bridge.
  - Every `dvswitch.sh` call has a time-out, and one lock covers connect and
    disconnect. A DMR password is never logged or shown in an error.
  - What was tuned is kept in `nodelisten_tuned.json`. The Connect button
    turns into Disconnect while the bridge stays linked.
- **With Node Controller running:**
  - ASL, EchoLink and M17 go through it as before.
  - DVSwitch favorites are refused, with a note to tune them on its page, so
    the two don't both drive `dvswitch.sh`.
  - If Node Controller starts after Node Listen tuned something, Node Listen
    leaves it in control.
- **Digital card** (Setup):
  - Control mode, what was found (dvswitch.sh, Analog_Bridge, USRP2M17,
    M17Hosts.json) and the service states.
  - The digital and M17 bridge nodes and the M17 callsign. Each is set here,
    or found on its own:
    - bridge nodes: from the `rpt.conf` USRP ports that match
      `Analog_Bridge.ini` / `USRP2M17.ini`, then Node Controller, then
      1999/1917;
    - callsign: from `USRP2M17.ini`, then Node Controller.
  - The DMR networks.
  - Download and upload of the favorites file. An upload is checked line by
    line and refused if any line is bad.
- `--install` writes an empty favorites file when none exists and prints what
  it found. `--uninstall` keeps it.

## 0.4.20 (2026-10-20)

Fixes from an external-interface audit.

- **Login could reject the right password** when several logins ran at once
  and the `/etc/shadow` check was used (no `pam` module). `crypt(3)` uses one
  shared buffer; the call now runs under a lock. In a test with 16 threads,
  0.4.19 rejected about half of the correct passwords. A wrong password was
  never accepted.
- **HTTPS that can't start is no longer silent.** A certificate that won't load
  is moved aside (`….bad`) and a new one is made, once. If HTTPS still can't
  start, the page is served over plain HTTP as before (internet logins stay
  blocked without HTTPS), and the login card now says in red that the page is
  not encrypted and the password is sent in plain text.
- **`systemctl` calls have a timeout** (120 s) and report a missing or stuck
  `systemctl` instead of hanging or crashing the install.
- **Install keeps the previous version until the restart works.** The old
  `nodelisten_v….py` in `/usr/local/lib/asl_dvs/nodelisten` is removed only
  after `systemctl restart` succeeds. The copy and the symlink use unique
  temporary names. A failed `daemon-reload` or `enable` is now reported.
- **HTTP-to-HTTPS redirect:** a request with a bad `Host` header is sent to the
  Pi's LAN address, not to `127.0.0.1`.
- **Transmit:** the USRP sequence number and the transmit socket are set under
  a lock, so two threads can't send the same number or make two sockets.
- The internet-login gate (20 failed internet logins in 10 minutes pauses
  internet logins) stays. It now keeps only the last 20 failures.

## 0.4.19 (2026-10-20)

- **Headset / audio output** (new Setup card), for a wired, USB-C or
  Bluetooth headset. Saved in this browser only.
  - **Audio output:** a list of outputs where the browser can switch (Chrome
    with `setSinkId`); elsewhere a note says to pick the headset in Android's
    sound settings.
  - **Microphone for push-to-talk:** Default (follows Android), or a chosen
    mic. If the chosen mic is gone, the default is used.
  - **Headset button:** Listen on / off (as before), **Push to talk**, or Off.
    Push to talk: press once to talk, press again to stop. It uses the same
    transmit as the Talk button, with the same time-out, and the button reads
    `TALKING (headset)`. Android only passes the button to the page while Node
    Listen is playing.
  - Shows which output and microphone are in use. **Show device names** asks
    for the microphone once when the browser hides the names.
- **Headset unplugged or output lost.** When Android pauses playback on its own
  (headset unplugged, Bluetooth dropped), Node Listen stops transmitting, stops
  listening and says so, where before it kept showing "playing". When the
  headset comes back within 30 minutes, listening starts again.
- After a transmission, playback is resumed straight away if the phone paused
  it, so the sound comes back to the headset.
- **Audio check** report adds the audio output, the microphone, how many times
  the headset was unplugged or the output was lost, and how many transmissions
  came from the headset button.

## 0.4.18 (2026-10-20)

- **Connect turns into Disconnect.** On the Connect tab, the Connect card's
  button reads **Disconnect** (in red) when the selected favorite is linked, and
  pressing it drops that favorite only. Other links stay up. It goes back to
  **Connect** once the link is gone.
- **Links card:** the "Linked favorites" line, its small Disconnect button and
  the note under them are gone. The links table stays.

## 0.4.17 (2026-10-20)

- **Audio check** (new Setup card, before Audio levels). Press **Start check**,
  go to the Listen tab and use the node as usual for 2 to 15 minutes (5 by
  default): listen, talk, listen. A `CHECK 2:13` badge on the Listen tab's
  status line shows it is running (tap it to come back). When it ends, or you
  press Stop, the card shows a report. Only numbers are kept, never audio, and
  only in this browser. The check carries on across tab changes and a page
  reload; time with the page closed or asleep is reported as paused.
- **Receive** rows: time listened, speech level, peak, how far apart the
  quietest and loudest stations were (taken from the node's own level, so it
  is right even with Automatic level on), sound below 300 Hz (CTCSS tones and
  hum), playback dropouts, squelch tails heard, and the Pi's processing load.
- **Transmit** rows: your transmissions, speech level, peak, voice above
  background, how often the limiter worked and the noise gate closed while you
  talked, transmissions with gaps and the peak the Pi saw (from the Pi), and
  how many transmissions stopped because audio stopped, timed out, or were
  refused.
- Each row is green, amber or red against its target, and **What to change**
  lists suggestions with amounts. Each has **Apply**, which makes the change
  (node settings need you to be logged in), and **Undo**.
- **Compare with last check** adds the previous check's numbers next to this
  one's; **Copy report** copies it all as text for asking for help.
- **Fix: the squelch-tail gate could mute speech.** Since 0.4.15 it told hiss
  from voice by how often the audio crosses zero, and a voice rich in
  harmonics crosses zero often too, so loud speech could be muted as a tail.
  It now uses how alike neighbouring samples are (energy-weighted): voice
  scores high, hiss and de-emphasised FM squelch noise score low. Tested with
  speech at three levels and white and de-emphasised tails on Light and
  Strong: all speech kept, all tail frames muted. The Audio check counts
  squelch tails the same way.

## 0.4.16 (2026-10-20)

- **Live meter for the audio tests** (Setup tab, Microphone card). While
  **Test mic** or **Test through the node** runs, a bar shows your level from
  -60 to 0 dBFS: the average, the peak, and a peak hold for 1 second. The
  target zone (-6 to -3 dBFS) is green and above -1 dBFS is red. A thin bar
  under it shows how much the leveler or limiter is turning you down, and the
  text says "limiting 4.2 dB" or "gate closed".
- **Mic test report** after the test: a 4 s level strip (with a playhead
  during playback), the peak, the speech level, the background level, how far
  your voice is above the background, how often the limiter worked (and the
  noise gate, when it is on), and one line saying what to change, with an
  amount: "Too hot: lower Mic gain by about 7 dB", "Quiet: raise Mic gain by
  about 12 dB", "Noisy: ...", or "Good".
- **Node test report**: what you sent and what came back from the node, as
  two strips lined up in time, with both levels, the difference, the round
  trip (about 0.5 s), the peak that came back, and what to change (TX gain,
  or the node's levels in SysMon). With Automatic level on, the report says
  the levels coming back are evened out.
- **TX on the Listen tab's level bar**: while you hold push-to-talk, the bar
  under the spectrum shows your mic level, labelled TX in red; it goes back to
  the node's level when you let go. The Listen tab still fits one screen.
- All of this is worked out by the phone; nothing changes on the Pi.

## 0.4.15 (2026-10-20)

**RX cleanup** for what listeners hear, done once on the Pi for every listener
(the node and its other links are not changed). Setup tab, Audio levels card,
"RX cleanup"; all three are **on by default**, so a node that updates hears the
difference at once. They are separate from "Adjust audio levels here".

- **Cut below 300 Hz** (on): a 4th-order high-pass. A 100 Hz tone drops by about
  38 dB, 150 Hz by 24 dB, 250 Hz by 7 dB (the highest CTCSS tones are only
  partly removed); 1 kHz is unchanged.
- **Automatic level** (on): aims speech at about -20 dBFS, with up to +18 dB of
  boost and down to -6 dB. It turns down fast, up at 3 dB a second (faster for
  the first half-second of a new transmission), and holds between
  transmissions. Peaks are still soft-limited, so it never clips.
- **Squelch-tail gate** (Light): mutes the burst of hiss after a station
  unkeys, and long silences. Listeners hear the audio 80 ms later than before
  so the start of a tail can be muted too. Strong also mutes shorter, quieter
  hiss, which can clip hissy speech sounds.
- **Processing load** on the same card: the share of one CPU core the cleanup
  took over the last 5 seconds, to check it on a Pi Zero 2 W. Nothing is done
  while nobody listens, or for frames that are near silent.
- New settings `rx_hpf`, `rx_agc` and `rx_gate` (0 off, 1 light, 2 strong) in
  `nodelisten.conf`.

## 0.4.14 (2026-10-20)

- **The Listen tab fits on one screen.** Everything is in one panel, top to
  bottom: Listen / Stop with the volume, a one-line status (node, feed, RX,
  TX, listeners), the spectrum with the level bar under it, the message line,
  and push-to-talk. Only the spectrum grows or shrinks with the screen, so on
  a phone the tab doesn't scroll (checked down to 375 × 553). On a very short
  screen (a phone on its side) the spectrum hides first, and only then does the
  tab scroll.
- **Push-to-talk is an oblong button** across the panel, 80 px tall, with the
  time on the right while you talk. When someone else transmits from Node
  Listen it turns amber and reads "Busy: <who> 0:12".
- **Spectrum** of what the node is passing, 0 to 4 kHz, drawn in the page
  (nothing extra on the Pi). It starts as a waterfall; tap it to switch to
  bars and back (each browser remembers). Below 300 Hz is shaded, where CTCSS
  tones and hum sit. It runs only while you listen and the page is on screen;
  **Show the spectrum** (Setup, Playback, on by default) turns it off.
- **The Status tab is gone**; the tabs are Connect, Listen and Setup. Its node,
  feed, RX and TX lights are on the Listen tab's status line (hover for the
  details), and the Links table is at the top of the Connect tab with
  Disconnect. A browser that last had Status open shows Listen.

## 0.4.13 (2026-10-20)

- **Setup tab: cards open and close.** Each card's title is a button
  (▸ / ▾) and every card starts closed when the page opens; closed, it shows
  a one-line summary (Receive "Node 41234 sends audio here", Transmit "Set up
  and linked", Settings "HTTPS · 3 listeners", Favorites "4 / 10", and so on).
  The Log is only fetched while its card is open, and the Dashboard's
  favorites list only once the Favorites card is opened.
- **Setup tab in a new order**, one job per card: Receive, Transmit,
  Settings, Favorites, Audio levels, Microphone, Playback, Log. The old Tune
  card is split into Audio levels (with its Save and Reset), Microphone and
  Playback.
- **Connect tab: always from the main node.** The Connect from menu is gone;
  Connect and Disconnect use the main node. A page still open from an older
  version that sends a node is answered from the main node too. For an M17
  favorite on a node that isn't Node Controller's, the message says to send
  Node Controller's node's audio here instead.
- **Listen tab:** the volume slider sits to the right of Listen / Stop on the
  same line (a speaker icon replaces the word Volume). **Keep the screen on**
  moved to the Setup tab's Playback card.
- **Status tab:** the Links table keeps each link on one line: its text
  shrinks with the screen (14 px down to 10.5 px), long names end in "…" (the
  full name shows on hover), and node 1921 is marked "(TX)". Table labels no
  longer break mid-word, and the Name column is filled right after logging in.

## 0.4.12 (2026-10-20)

- **Listening starts when the page opens.** When the page loads (and after
  logging in), Node Listen starts playing the node's audio by itself. A new
  setting, **Start listening when the page opens** (Setup tab, This device's
  playback), is on by default and is kept per browser like the other playback
  settings; turn it off to go back to pressing Listen.
- Most browsers hold sound until the page has been tapped once. Then the
  Listen tab says "Tap anywhere to start listening" in amber, and the first
  tap or key press anywhere on the page starts it. Tapping Listen itself also
  works and starts one stream, not two.
- Stop still stops; listening only starts by itself on opening the page or
  logging in. With "Listen without logging in" off, nothing plays until you
  log in.

## 0.4.11.1 (2026-10-19)

- **The title bar and the tabs bar stay in place.** The title bar is fixed at
  the top and the tabs bar at the bottom; only the page between them
  scrolls. Before, the title bar could slide off on some phones. On a phone
  with a notch, the title bar clears it. Layout only, no change in behaviour.

## 0.4.11 (2026-10-19)

- **Connect says whether the link came up.** After Connect on an ASL or
  EchoLink favorite, Node Listen watches the node's links (`rpt lstats`) for
  up to 15 seconds and reports one of:
  - connected ("Node 12345 is connected to ASL 2000."),
  - still trying, in amber, when the link is there but not established yet
    (the node may be offline or busy),
  - failed, in red, when no link appeared (wrong number, or the node is
    offline or refusing connections).
  This works the same whether the connect went through Node Controller or
  straight to Asterisk. The Connect button is greyed out while it checks, and
  the result goes to the log. M17 favorites report what Node Controller
  answers, as before.

## 0.4.10 (2026-10-19)

- **M17 favorites.** A favorite can now be an M17 reflector: pick **M17** in
  the Favorites editor and type the reflector and module, for example
  `M17-USA A`, or `M17-USA @ALL` (just `M17-USA` means @ALL) for every module.
  M17 is added to the favorites only; Node Listen has no M17 tab.
- **Connect** on an M17 favorite asks Node Controller to tune the M17 bridge
  to that reflector and module and link the M17 bridge node to its node, the
  same as Connect on Node Controller's M17 tab. It goes from Node
  Controller's node only. **Disconnect** drops the M17 reflector when it is
  one of the favorites, and "Linked now" shows it.
- Needs Node Controller 9.3.92-pi02w or later. With an older Node Controller,
  or none running, an M17 favorite says so and nothing else changes; ASL and
  EchoLink favorites work as before. Older Node Listen versions skip M17
  favorites in the favorites file.
- **From the Dashboard** also offers the Dashboard's M17 favorites.

## 0.4.9 (2026-10-19)

Review cleanup: duplicate code folded together, dead code removed, a few
best-practice fixes. The page, rpt.conf edits and audio work as before.

- **Removed dead code.** The `/api/restart` route had no caller (SysMon
  restarts Node Listen with systemctl); it is gone. The talk channel no
  longer sends a "hello" message on connect, which the page never read and
  which cost an rpt.conf read and an Asterisk call each time. `/api/whoami`
  drops its unused `https` field.
- **Server helpers.** One helper runs `rpt cmd ... ilink` and clears the link
  cache (four places did both by hand); one builds the "changed, backup ..."
  answer of the rpt.conf edits (five places); small helpers find a stanza,
  check a node name, compare lines without spaces and remove a file quietly.
  The busy check for push-to-talk reads the audio activity directly instead
  of building the whole status. The status poll reads the main node once
  instead of twice. The local key and Node Controller answers are read by one
  code path each.
- **Settings save** takes the old and new settings from one snapshot.
- **Installer.** The service unit and the shared launcher are written
  atomically (temp file, then rename); the launcher text is unchanged. Two
  config reloads that did nothing are gone. The launcher check closes the
  unit files it reads.
- **Page.** Live playback and test playback build their audio buffers with
  one function; push-to-talk messages take their color from one call instead
  of patching it after (and two states that were never used are gone); the
  Settings fields and favorite copies are listed once.

## 0.4.8 (2026-10-19)

- **The login screen matches instmon's.** Login is now a centered card over a
  dark, blurred background instead of a card at the top of the page: an amber
  "Node Listen Login" title, a "Root password" field and a LOG IN button
  (greyed out while it checks), with errors in red under it. The header
  button reads "Log Out".
- **Public listening keeps working without logging in.** With public
  listening on, the login card stays closed and the player is shown; a
  **Log In** button in the header opens the card, and **Cancel** closes it.

## 0.4.7 (2026-10-19)

First step to using Node Listen from the internet (WAN), with minimal
security. Only Node Listen is meant to be reachable from outside; Node
Controller and SysMon stay on the LAN.

- **Internet access is off by default.** A new setting, `allow_wan` in
  `/etc/asl_dvs/nodelisten.conf` (no page checkbox yet), decides whether
  clients from the internet are served at all. Off (the default), they get
  403 for every page and API. **A node that already reaches Node Listen
  through a router port forward loses that access until `allow_wan = true`
  is set** (then `systemctl restart nodelisten`).
- **LAN** is private, loopback and link-local addresses, plus 100.64.0.0/10
  (Tailscale). Tailscale works with `allow_wan` off, which suits a node behind
  CGNAT, where a port forward can't work.
- **A tunnel counts as internet.** A request from the Pi itself that carries
  a proxy header (Forwarded, X-Forwarded-For, X-Real-IP, CF-Connecting-IP,
  Tailscale-Funnel-Request) is treated as coming from the internet, so a
  Cloudflare Tunnel or Tailscale Funnel can't slip past these rules; the
  forwarded address is used for logs and lockouts.
- **No password over plain HTTP from the internet.** An internet login on
  plain HTTP gets 403 before the password is checked (behind a tunnel,
  `X-Forwarded-Proto: https` counts as HTTPS). The session cookie is marked
  Secure in that case too.
- **Shared lockout for internet logins.** On top of the per-address lockout
  (5 tries), after 20 failed internet logins in 10 minutes from any
  addresses, every internet login waits until that window ends. LAN logins
  are never held. The failed-login table forgets entries after an hour and
  holds at most 1000.
- **Internet logins are logged as warnings**, with the address and
  "(internet)".

## 0.4.6 (2026-10-19)

Refactor with no change in what Node Listen or its page does: the same
rpt.conf edits, API answers, transmit packets and page behaviour.

- **Server**: one range check builds the integer settings checks (same
  messages); one helper reads and parses rpt.conf (seven places did it by
  hand); the [nodes] line for node 1921 is put in by one function, which
  Add node 1921 used to spell out twice; the audio pump and the transmit pacer
  share one 20 ms loop; the UDP sockets share one bind (a socket that fails to
  bind is now closed); the POST routes are one table instead of four
  copy-pasted error blocks; the page is built once and kept.
- **Page**: one windowed-sinc builder makes the filters for both the mic
  resampler and the playback upsampler (bit-for-bit the same coefficients);
  small helpers for messages, POST calls, gain labels, list options, playback
  and the audio context replace repeated code. Mic settings are saved with
  the same values (the keys are in a different order).

## 0.4.5 (2026-10-19)

Transmit audio fixes from an external audit (server side only; the page and
its default settings are unchanged).

- **Soft limit instead of hard clip** on the TX and RX gains (Tune card). Up to
  29000 (about -1 dBFS) the gain stays linear; above that a tanh curve rounds
  peaks off towards full scale instead of squaring them off at ±32767. This
  matters on TX: with the leveler on, the page sends peaks at -1 dBFS, so any TX
  gain above +1 dB used to clip them. Samples are now rounded, not truncated.
- **Fade-out on release**: when push-to-talk is let go, the last 20 ms frame of
  audio is faded to zero before the radio unkeys, so the transmission ends
  without a click. Time-out and deadman unkeys are unchanged.
- **Nagle off** on all page connections (`TCP_NODELAY`), so small writes such
  as listen-stream chunks go out at once instead of waiting on the browser's
  ACK. Transmit audio flows from the browser, which already sends without
  delay, so this mainly helps listening.
- Not taken from the audit: a lower TX buffer default (it only delays the
  start of a transmission, and the Tune card already offers 60 ms), a shorter
  deadman (it never fires while push-to-talk is held, even during pauses, so
  it would only add false unkeys), a server DC blocker (the page's voice filter
  already removes DC, and the keyup flag, not the audio, keys the radio) and a
  server-side leveler (the page's leveler is on by default).

## 0.4.4 (2026-10-19)

More audio options, all per device (kept in each browser) on the Tune card.

- **Leveler** (on by default): a compressor and peak limiter in the page keep
  the mic at an even level and never clip (peaks stop at -1 dBFS); it replaces
  the hard clip. **Automatic gain** is now off by default; a phone that saved
  mic settings with 0.4.1 to 0.4.3 has it turned off once, since it fights the
  leveler. Test mic says when the leveler is limiting hard.
- **Noise gate**: Off (default), Light or Strong. Between words the mic drops
  by 15 dB (Light, below -45 dBFS) or 30 dB (Strong, below -35 dBFS), with a
  250 ms hold so word endings aren't cut.
- **Radio voice** (off by default): cuts below 300 Hz and lifts 2.5 kHz by
  4 dB. Leave it off if the radio already adds pre-emphasis.
- **Test through the node**: after a confirmation, keys node 1921 for 4 s,
  records what the node sends out (its audio feed) and plays it back with the
  peak level. It goes out over the air and to linked nodes, and it obeys the
  busy lockout.
- **This device's playback**: **16-bit audio** (on by default) streams the
  node's audio as 16-bit samples instead of µ-law (128 kbit/s instead of 64)
  for cleaner quiet audio and noise tails; `/api/listen?fmt=s16`, with the
  format in the `X-Audio-Format` header, so an older Node Listen just keeps
  sending µ-law. **Smooth playback** (on by default) upsamples the 8 kHz audio
  to the phone's rate with a filter instead of the browser's basic resampler;
  Test mic playback uses it too.

## 0.4.3 (2026-10-19)

- **An update keeps node 1921 and the audio feed.** InstMon's Full Update runs
  the installed version's `--uninstall` and then the new file's `--install`.
  The uninstall removes the transmit node 1921 and the `outstreamcmd` line from
  rpt.conf, and the install used to leave them out, so Setup asked to add node
  1921 again. Now `--uninstall` notes what it removed in
  `/etc/asl_dvs/nodelisten_restore.json` (mode 0600), and an `--install` within
  30 minutes puts those lines back and deletes the note; an older note is
  ignored and deleted. A plain uninstall still leaves rpt.conf clean.
- The note is written by 0.4.3 and later, so updating from 0.4.2 or older
  still drops node 1921 that one time; press **Add node 1921** on Setup after
  that update, or install 0.4.3 from InstMon's Library card instead.

## 0.4.2 (2026-10-19)

- **Node Controller** (header) drops the arrow icon and goes back to the
  Dashboard's tab instead of opening a new one each time: it switches to the
  open Dashboard tab without reloading it, or opens the Dashboard once in a new
  tab when there isn't one. A Dashboard older than 9.3.90-pi02w doesn't name
  its tab, so the first press opens one new Dashboard tab and later presses
  reuse it.
- The page names its own tab, so the Dashboard's **Listen** button (9.3.90-pi02w
  or later) finds it even when Node Listen was opened from a bookmark.

## 0.4.1 (2026-10-19)

- **Cleaner TX audio.** The page now resamples the mic to 8 kHz with a filtered
  (windowed-sinc) resampler, so sounds above 3.4 kHz no longer fold back as
  hiss and whine; it was a plain average before.
- **TX buffer** on the Tune card: 60, 120 (default), 200 or 300 ms of mic audio
  are held before the node is fed (was a fixed 60 ms). If the phone's audio
  stalls and the buffer runs dry, Node Listen sends silence and waits for the
  buffer to refill instead of feeding the node a few ms at a time. The card shows
  **TX gaps** (live while talking, else the last transmission), and the log
  counts them at unkey. Raise the buffer if gaps show up.
- **This device's microphone** (Tune card, kept in each browser): **Automatic
  gain**, **Noise suppression**, **Echo cancellation** (now off by default; the
  listen audio is muted while you talk), **Voice filter** (cuts rumble below
  about 250 Hz) and **Mic gain** (-12 to +24 dB, applied in the page; browsers
  can't set the phone's own mic volume). With automatic gain on the browser
  undoes most of the mic gain, so turn it off for a fixed level.
- **Test mic**: records 4 s, plays back what the node would get, and rates the
  peak (too hot, good, quiet). Nothing is sent to the node.

## 0.4.0 (2026-10-19)

- **Tune card** (Setup), opt in with **Adjust audio levels here**: **Mic to node
  (TX)** and **Node to phone (RX)** gains, -12 to +12 dB, and the **Listen
  buffer** (0.15, 0.25, 0.5 or 1 s). Off, audio passes through unchanged and the
  buffer is 0.25 s. Gains apply at once, with clipping; the card shows the TX
  peak (live while talking, else the last transmission) and the RX level. When
  SysMon answers on port 9999 the card points to it for the node's own levels
  (radio, DVSwitch and USRP gains).
- **Connect from** (Connect tab): pick the local node that makes the link, from
  rpt.conf's numbered nodes (not 1921, not the Dashboard's bridge nodes); the
  main node is the default. Shown when there is a choice.
- **Connects go through Node Controller when it runs.** When the connecting node
  is the Dashboard's node and the Dashboard (pi02w 9.3.89 or later) answers, Node
  Listen sends the connect or disconnect to the Dashboard's local API
  (`POST /api/local/action` on 127.0.0.1, with the key in
  `/etc/asl_dvs/local_api.key`, made by whichever starts first, mode 0600). The
  Dashboard switches to its ASL or Echo tab (dropping any digital bridge, so the
  phone can't bridge DMR to AllStar), connects as if you had pressed Connect, and
  counts the link as its own, so its permanent-link "Bridging risk" banner and
  extra-link clean-up leave it alone. A refusal from the Dashboard is shown as
  is. Without the Dashboard, or with an older one, Node Listen connects directly
  as before.
- The header's **Node Controller** link is hidden when the Dashboard isn't
  running.
- The busy lockout's grace after Node Listen's own unkey is 1 s (was 2 s), so
  quick re-presses can't key over someone who answers straight away.

## 0.3.1 (2026-10-19)

Fixes from an audit of 0.3.0.

- **`[nodes]` line follows the IAX port.** 0.3.0 always wrote
  `1921 = radio@127.0.0.1/1921,NONE`, so on a node whose `bindport` in
  `/etc/asterisk/iax.conf` isn't 4569 (44helper's Nodes tab recommends
  4560-4580 for several nodes on one network) node 1921 could never link. Node
  Listen now reads `bindport` from `[general]` (following `#include` /
  `#tryinclude`, two levels deep) and writes `radio@127.0.0.1:<port>/1921`
  when it isn't 4569, the same rule as the Dashboard's Phone nodes. The
  transmit card says when the line is missing or has the wrong port, and **Add
  node 1921** fixes it (with a backup). Remove takes out the line whatever its
  port.
- **PTT is refused while 1921 isn't linked** ("not linked yet": Asterisk not
  restarted since it was added, or the link keeper hasn't relinked it), instead
  of appearing to transmit into nothing.
- **No false "busy" right after your own transmission.** The node's audio comes
  back on the listen feed about half a second late, so pressing PTT again
  straight after letting go was refused as busy. The busy lockout now ignores
  the 2 s after Node Listen's own unkey.
- **First press with the microphone prompt.** The browser's permission prompt
  takes focus, which released PTT at once on the very first press. Losing focus
  no longer releases PTT while the microphone is being opened.

## 0.3.0 (2026-10-19)

Node Listen becomes a phone page for the LAN: listen, push-to-talk and a short
favorites list, with no app to install.

- **Four tabs** (bottom bar): **Status** (node, receive and transmit lights,
  feed, links from `rpt lstats`), **Connect**, **Listen** (with push-to-talk)
  and **Setup** (the receive hook, the transmit node, favorites, settings, log).
  The header links to the Node Controller Dashboard (its port from
  `/etc/asl_dvs/asl_dvs.conf`, default 8989). Logged out, only Listen shows,
  and only with **Listen without logging in** on.
- **HTTPS, on by default.** Browsers only allow the microphone on a secure page.
  Node Listen makes a self-signed certificate on first start
  (`/etc/asl_dvs/nodelisten_tls/`, names and LAN addresses in it) and serves
  HTTPS on the same port; a plain `http://` request is sent a 301 to
  `https://`, so old links (the Dashboard's Listen button) still work. The
  browser shows a warning to accept. The session cookie gets `Secure`. An
  **HTTPS** setting turns it off (push-to-talk then can't work); changing it
  restarts the service.
- **Push-to-talk** to private node **1921**: hold the big button (or Space /
  Enter on it). The page records the microphone with echo cancelling, cuts it
  to 8 kHz 16-bit in the browser (AudioWorklet, ScriptProcessor fallback) and
  sends 20 ms frames over a WebSocket (`/api/talk`, login and same-origin
  required). Node Listen sends them as USRP to `127.0.0.1:32018` with keyup set,
  three keyup=0 frames on release, and drains what Asterisk sends back on
  34018. Listen audio is muted while you talk.
  - Unkeys on release, at the **time-out** (`tot_sec`, 30-600 s, default 120),
    1 s after frames stop (**dead-man**), or when the page closes, loses
    focus or is hidden.
  - **Busy lockout** (on by default): PTT is refused while the node is passing
    audio. One talker at a time.
  - Every keyup and unkey is logged with the address and length.
- **Transmit node card** (Setup): **Add node 1921** appends a `[1921]` stanza
  (the main node's template, `rxchannel = USRP/127.0.0.1:34018:32018`,
  `duplex = 0`, no hang time, no telemetry, no courtesy tone) and
  `1921 = radio@127.0.0.1/1921,NONE` under `[nodes]`, after backing rpt.conf
  up. It refuses if rpt.conf already has a `[1921]` it didn't add. **Remove**
  takes both out. A **link keeper** checks `rpt lstats` every 20 s and issues
  `rpt cmd <main> ilink 3 1921` when 1921 isn't linked.
- **Favorites, up to 10** (Setup): network (ASL or EchoLink), number and name,
  saved to `/etc/asl_dvs/nodelisten_favorites.json`. A list offers the
  Dashboard's ASL and EchoLink favorites (bridge nodes left out). Node 1921 and
  duplicates are refused. The **Connect** tab has them in a drop-down;
  Connect runs `rpt cmd <main> ilink 3 <node>` (EchoLink as `3` + six digits),
  Disconnect runs `ilink 1` for each linked favorite only, so the transmit node,
  bridges and links made elsewhere stay.
- The main node is the one picked for the receive hook, else the Dashboard's
  `asl_node`.
- The systemd watchdog also needs the transmit pacer alive, and its health
  check speaks HTTPS when HTTPS is on.
- Node 1921 is linked only while Node Listen runs: on stop (systemd's SIGTERM)
  Node Listen unlinks it (`ilink 1 1921`), and **Remove** unlinks it before
  taking it out of rpt.conf. The Dashboard (pi02w 9.3.87) leaves it alone while
  Node Listen runs and unlinks it if Node Listen isn't running.
- After you let go of PTT the listen audio stays muted for 1 s, so the delayed
  tail of your own transmission doesn't play back.
- `--uninstall` removes node 1921 as well as the `outstreamcmd` line.
- Setup-page messages with long paths wrap instead of widening the page on a
  phone.

## 0.2.0 (2026-10-18)

Background listening, aimed at Android Chrome. Page changes only; the server and
stream are unchanged.

- **Plays through a media element.** The Web Audio output now goes to a hidden
  `<audio>` element (`MediaStreamAudioDestinationNode` -> `srcObject`) instead of
  straight to the speakers. The browser then treats the page as playing media, which
  is what lets Android keep it going in the background and with the screen off. If
  the element can't play, it falls back to the 0.1.0 path.
- **Phone media controls.** Media Session metadata ("Node <number>", "Node Listen",
  the Pi's address) and play / pause / stop handlers, so the notification and lock
  screen show it and can stop or restart it. The playing / paused state follows the
  Listen button.
- **Keep the screen on while listening** (checkbox, remembered in the browser). It
  uses the Screen Wake Lock API, which browsers only allow over HTTPS or on
  localhost, so on a plain `http://<pi>:8993` page the checkbox stays hidden.
- A line under the Listen card says playback can carry on in the background.

## 0.1.0 (2026-10-18)

First release. A common tool: one stdlib-only file, built on the same skeleton
as instmon and Pibrary (root-password login, sessions and lockout, the
X-Requested-With check, the `sd_notify` watchdog, `--install` / `--uninstall`,
the shared launcher).

- **Listen card.** Listen / Stop, volume (0-200%), a level meter, and lights for
  "feed from Asterisk" and "audio passing". The browser reads `GET /api/listen`
  as a stream (8 kHz mu-law, 64 kbit/s) and plays it with Web Audio, about
  0.25-0.5 s behind the node. It reconnects by itself after 3 s if the stream
  drops. Listeners are capped (default 3; a full house gets a 503).
- **Node card.** Lists the numbered nodes in `/etc/asterisk/rpt.conf` and their
  `outstreamcmd` (own, another one, or inherited from a template). **Send its
  audio here** adds
  `outstreamcmd = /usr/bin/python3,/usr/local/bin/nodelisten.py,--feed,<udp_port>`
  to that node's stanza, with a comment line above it, after backing rpt.conf up
  to `/etc/asl_dvs/nodelisten_backups/` (last 10 kept). Only one node is hooked at
  a time. A node with someone else's `outstreamcmd` (for example Broadcastify) is
  refused. **Remove** takes the line out; **Restart Asterisk** asks first. The
  card also shows whether the feeder process is running and the UDP input state.
- **Feed mode.** `nodelisten.py --feed <port>` is what Asterisk runs: it copies
  stdin to `127.0.0.1:<port>/udp` and never stops on send errors, so Asterisk's
  pipe never blocks while Node Listen restarts.
- **Audio pump.** A 20 ms clock takes the node's audio from a short queue (0.5 s
  cap, trimmed past 0.2 s to keep the delay low) and sends silence when the node
  is quiet, so the browser's timing stays steady.
- **Settings.** Web port (8993), UDP port (6200), max listeners, and **Listen
  without logging in** (off by default: listening only, never the Node or
  Settings cards). Changing a port restarts the service; a new UDP port also
  rewrites the rpt.conf line.
- **Watchdog.** systemd's watchdog ping needs both the web server and the audio
  pump to be alive.
- Config in `/etc/asl_dvs/nodelisten.conf`. `--uninstall` removes the rpt.conf
  line (with a backup) and keeps the config and backups.
- Not yet in the installer, the uninstaller or instmon's tool list; install it
  with its own `--install` or from instmon's library.
