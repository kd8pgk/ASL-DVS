# Node Recorder changelog

Current file: `noderecorder_v0_5_14_20261107.py`. Newest entries first.

## 0.5.14 (2026-11-07)

- **Schedule windows can touch.** The rule that windows be at least 2 minutes apart is gone: back-to-back windows are allowed. Each scheduled recording starts 60 seconds after its window opens and stops 60 seconds before it closes, so two windows that meet leave a one-minute gap for the node to change over. Overlapping windows are still refused. The dry run uses the same timing. Record now is not affected.
- **Scheduled slots are at least 3 minutes long.** A scheduled entry shorter than 3 minutes is refused with a message.
- **One Schedule list.** The Setup tab no longer has its own copy of the schedule list. The Schedule tab's card is the only list, and it folds like the other cards. Its note about 2-minute windows is removed.
- **Offline banner.** When Node Recorder stops answering, a red banner says so. The page checks `/api/health` every 5 seconds and hides the banner when the server answers again.
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
