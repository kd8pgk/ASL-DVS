# Pibrary changelog

Current file: `pibrary_v0_15_0_20261028.py`. Before 0.14.0 Pibrary was kept outside this repo; its earlier entries are below. Newest entries first.

## 0.15.0 (2026-10-28)

- **Login is on by default.** On a first start with no saved settings, Pibrary asks for a password. Sign in with the Pibrary password if one is set, otherwise with the node's root password, the same as the other tools. If the node has neither, login stays off and the log says why, so nobody is locked out; set a password and turn on Require login in Config. A node whose saved settings already say login is off keeps that.
- **The login screen follows Node Controller.** It shows the same welcome line and license line as the other tools, and the card title is just "Pibrary". In the light theme the screen is light. The login screen's CSS lines and welcome / license markup are now part of the shared look that the repo check requires, and Pibrary is one of the tools it checks.

## 0.14.0 (2026-10-28)

Pibrary joins the repo as a common tool, in step with the other Node Control tools. It works as 0.13.1 did, apart from the points below. The file is a comment-stripped copy.

- **The look of Node Control.** The text is set in Readex Pro (built into the page, so no internet is needed). Buttons and text use one size scale, and the S / M / L size setting in View still changes the root size. Text boxes and the log stay monospace. The header gains a sub-line under the logo. The page's Content-Security-Policy now allows the built-in font (`font-src 'self' data:`); without that the browser blocks it. Cosmetic only. Readex Pro is Copyright 2019 The Readex Pro Project Authors, under the SIL Open Font License 1.1.
- **Files are written the same safe way in every tool.** Every write goes through the shared `atomic_write` (kept identical in each tool and checked by the repo check): a private temp file with a random name in the same folder, fsync, then a rename. An edited file keeps its owner and mode. A symlink at the path is replaced, not followed.
- **The port opens on install and closes on uninstall.** Install checks that Pibrary's port (9000, or the port in its config) is open in the firewall (ufw or firewalld) and opens it if it is not. With no active firewall nothing changes. Uninstall removes the service first and closes the port last. A port changed later in Config does not touch the firewall. The check is shared through `firewall_backend`, `open_firewall_port` and `close_firewall_port` in `shared/confio.py`.
- **Starts through the shared launcher.** The service runs `/usr/local/bin/asl_dvs_launch.py`, which caps memory use and trims it every few minutes on a small Pi. Install writes the launcher; uninstall removes it only when no other service uses it.
- **Internal.** The PAM check no longer leaves an unused import. No change in behaviour.

## 0.13.1 (2026-10-17)

- Duplicate finder ("Duplicates" next to Trash on each tab): files of equal size, then a quick
  hash of the first and last 1 MB, then a full SHA-256 - so identical content is found whatever
  the name. Runs as a storage job (progress, Cancel; the drive watcher waits meanwhile). Groups
  list the copies oldest first; the oldest is kept and the others are ticked; "Move ticked to the
  trash" (restorable). Copies on extra roots are shown but cannot be ticked.
  GET /api/lib/dupes, POST /api/lib/dupes/scan.

## 0.13.0 (2026-10-17)

- Cover art from folder images (no ffmpeg): cover / folder / front / album / poster .jpg .jpeg
  .png .webp in a folder (or its parent), and for a single file an image with the same name
  (Film.mp4 + Film.jpg). Found during the normal scan; served by GET /api/lib/art (path-checked,
  images only, max 10 MB, cached a day). Shown in grid tiles, folder rows, the mini-player,
  Newest files, the movie player (poster) and on the phone lock screen.

## 0.12.6 (2026-10-17)

- Playback speed 0.75-2x in the movie player and the mini-player (pitch kept; remembered per
  browser for audio and video). Sleep timer: Off / 15 / 30 / 60 min / end of track, fades out
  over 10 s and pauses.
- Played markers: files of 3 min or more that reach the end get "played" (synced like resume
  positions; tombstone-free); badges "played" / "at 12:34", folder rows "3/10 played", a filter
  All / Unplayed / In progress / Played, and Select mode Mark played / Mark unplayed. Continue
  watching skips played files. Limits: 5000 positions on the drive, 2000 per browser.
- View panel: "Remember open cards" (per browser, off by default) and Keyboard shortcuts; "?"
  opens the shortcut help.

## 0.12.5 (2026-10-17)

- Config backup (Config 18): Download backup (JSON; the password hash only when login is on and
  ticked), Check file -> list of changes -> tick library drive / password, type RESTORE. Every
  save also writes <library>/.pibrary/config-backup.json (no password); on a fresh SD card "Look for
  a backup on the USB drives" finds it (read-only probe mount). Restoring login on needs Keep.
- Log file on the library drive (Config 17, on by default, USB library only): .pibrary/logs/
  pibrary.log, 1 MB x 5, written every 10s, at eject, reboot and shutdown; "File" in the log heading.

## 0.12.4 (2026-10-17)

- Safe changes for a remote Pi: turning Require login on, changing / clearing the password and a
  port change (Restart now) show a Keep / Undo banner; without Keep they are undone by themselves
  (2 min; 3 min for the port, which survives the restart and needs Keep from a page on the new
  port). Keep for login / password needs the password. A port that cannot be opened at start goes
  straight back to the old one. GET/POST /api/keep.
- Reboot the Pi (Config 16): type REBOOT; needs login and root; the page reconnects by itself.
- Status "Access" line: how this page is reached (this Pi / local network or VPN / Tailscale range /
  INTERNET warning) and whether the address is an allowed host.

## 0.12.3 (2026-10-17)

- Auto-import (Config 15, needs login + a USB library): a drive with a top-level PIBRARY-IMPORT
  folder is copied in by itself 10s after it is mounted. Movies/ Audio/ PDF/ (also Videos, Music,
  Documents, ...) keep their structure; other files go to <tab>/Imported/<date>/. Never overwrites
  (a different file gets "name (2).ext"), checksum-verified, files already imported are skipped
  (record in <library>/.pibrary/autoimport/<uuid>.json), max 5000 files per run. A Pibrary*.py at
  the top is staged (not installed). The drive is ejected when done.
- Activity LED as the on-site signal: heartbeat while copying, solid when done (safe to unplug),
  fast blink on an error; back to normal when the drive is unplugged. Notification on finish/fail.

## 0.12.2 (2026-10-17)

(remote-Pi release)

- Power: vcgencmd get_throttled every 15s (under-voltage / capped / throttled / temperature, now
  and since boot). Drive health: smartctl (if installed; tries -d sat for USB adapters) every 10
  min for the library and import drives: pass/fail, temperature, hours, reallocated / pending /
  media errors, SSD wear.
- Low space: library drive below 10% or 5 GB (warning) / 2% or 1 GB (problem); SD card below 10%.
  Full-drive upload refusals say how much is free and needed.
- Alerts: one list (power, throttling, drive errors / offline, SMART, space) shown as a banner on
  every tab (Dismiss hides it until it changes), logged once per change; GET /api/alerts.
- Notifications (Config 13): ntfy address + level (everything / warnings / problems) + Send a
  test. Sent: alerts (max once an hour each), resolved problems, starts, update installed/failed.
- Heartbeat (Config 14): pings an address (e.g. healthchecks.io) every N minutes while healthy.
- Status System card shows power, drive health, notification and heartbeat state.

## 0.12.1 (2026-10-17)

- Show / Hide on card headings, hidden on every page load: the Config sections, the Status
  "System" card and the Log. Config: Finish opens by itself on unsaved changes (its heading says
  so while closed); a save error naming an entry opens that section. System only polls while open.
- Log: Copy button (works while hidden; copies the lines that pass the level / text filter).
- Search bar moved from the header to the top of every tab (scrolls with the page; key s).
- Header on one line and smaller: logo, "vX . port N", View and Log Out side by side; the
  subtitle line is gone and the hostname is the logo's tooltip.
- Status: new "Newest files" card (open by default): the 5 most recently added files per tab,
  click to open, "Show all" opens the tab in Flat mode sorted by Recently added. GET /api/lib/recent.

## 0.12.0 (2026-10-17)

(v0.11 upload UX skipped for now)

- Fix: the pinned side tabs could slide under the header when it grew after load (Log Out button
  appearing, text wrapping, fonts, rotation). The rail now follows the header height live.
- Phone layout (< 600px): tabs become a bar at the bottom with icons and labels; mini-player,
  toasts and the queue sit above it; room for the iPhone home bar / notch; bigger tap targets and
  wrapping file rows. Tab side L/R applies to wider screens only.
- Add to home screen: web app manifest, generated PNG icons (192, 512, apple-touch 180) and iOS
  tags; opens full screen on iPhone/iPad. A full Android install needs HTTPS (later).

## 0.10.1 (2026-10-17)

- "Delete folder" button on every folder row of the library drive (no Select mode needed): the
  folder and everything in it go to the trash (restorable for 30 days); empty folders are removed.

## 0.10.0 (2026-10-17)

(v0.9 subtitles skipped for now)

- File management on each media tab (library drive only; needs Allow uploads): New folder,
  Select mode with checkboxes (All / None), Rename (files keep their extension), Move to... with a
  folder picker (no moving a folder into itself, never overwrites), Delete to the trash.
- Trash per tab at <library>/.pibrary/trash: Restore, Delete now, Empty trash; entries older than
  30 days are removed automatically (hourly check). Empty folders are removed directly.
- Empty folders on the library drive now show in Folders mode.
- Uploads go into the folder being viewed (when it is on the library drive).
- Resume positions, the audio queue and the playing item follow renamed / moved files.
- Extra roots and import drives stay read-only. The trash is not copied when switching drives.

## 0.8.4 (2026-10-17)

- Replace library drive: "Replace library with this drive" on other drives in Config entry 5, with
  a copy source (old drive / SD card / nothing). The new drive is mounted at /mnt/pibrary-new and
  filled by the usual resumable copy job; then the old drive is unmounted (lazily if it is dead),
  the new one is mounted at /mnt/pibrary-usb and becomes the library. Resume positions are merged
  across. Any failure rolls back to the old drive; the old drive is never modified and is left
  ejected (not auto-imported) until it is unplugged.
- Format a USB drive as ext4: new list of USB disks in entry 5 with "Format as ext4..." (type
  FORMAT, label default PIBRARY). Whole disk: wipefs, one GPT partition, mkfs.ext4 -m 0 with lazy
  init, then blkid + test mount. Refused for the library drive, system/swap disks and anything
  mounted outside Pibrary; a fingerprint (name, size, serial, model) guards against renamed disks.
  Cancel works until erasing starts.

## 0.8.3 (2026-10-17)

- Resume positions shared by all browsers: GET/POST /api/positions, stored on the USB library drive
  in <library>/.pibrary/positions/positions.json (never on the SD card). Newest timestamp wins;
  Forget / finishing a file is a tombstone (kept 30 days). Max 2000 positions, 200 per request.
- The server keeps changes in memory and writes them at most every 60s, before Eject and Use SD
  card, and on shutdown (SIGTERM from systemctl stop / restart / update).
- Browsers merge on load, every 5 min and when the tab becomes visible; they push changes after
  30s (2s after a pause / Forget) and on page hide. In SD mode or while the drive is offline,
  positions stay in each browser and are pushed once the drive is back.
- Status shows where resume positions are kept.

## 0.8.2 (2026-10-17)

- Drive health: a USB drive that drops off the bus (power dip, loose cable) left a mount whose reads
  failed with EIO while the UI said "online". Now, at startup and every 15s, the library and import
  mounts are checked (mount device still present and the same as lsblk's, a read answers within 5s);
  a dead mount is lazily unmounted (no sync), shown as "error" with the reason, and remounted by
  UUID when the drive answers again. After 3 faults in 10 min auto-remount stops until the drive is
  replugged or Mount is pressed. Mount / Eject / Use SD card reset the budget.
- Copy and purge jobs stop at the first I/O error ("a drive stopped responding") instead of failing
  every remaining file; nothing is switched and nothing unverified is deleted.
- Upload / import / copy-back refusals and the Status, Config and media tabs show the drive error.
- The systemd watchdog starts after the server socket is listening (no false probe error at start).

## 0.8.1 (2026-10-17)

- Cosmetic: the side tab rail is pinned to the margin (position fixed below the header) and no
  longer scrolls with the page; it scrolls on its own only if the window is too short.
- Cosmetic: Save sits at the right edge of entry 13, away from Discard changes.

## 0.8.0 (2026-10-17)

- Audio mini-player: a bar fixed at the bottom of every tab (prev / play / next, seek, title links
  to the folder, Cast, Close). Starting a video pauses the audio and vice versa.
- Queue (saved in this browser, max 1000): clicking a track plays the current view from there;
  per-row Next / +Queue buttons; queue panel with up / down / remove / jump and Clear.
- Shuffle (once, current track first; off restores the order) and repeat off / all / one.
- Media Session: lock-screen / headset play, pause, previous, next, seek, +-10s; position state.
- Resume positions in this browser for audio and video of 3 min or more (saved every 5s, on pause
  and on page hide; cleared near the end; newest 500 kept); auto-resume with a Start over button;
  "Continue" strip of the 5 latest unfinished movies on the Movies tab.
- Keys: space toggles the video on the Movies tab or else the mini-player; n / p step the queue
  (or the movie list); q opens the queue; Esc closes the queue panel.

## 0.7.0 (2026-10-17)

- Navigation: each media tab has a Folders / Flat toggle (remembered). Folders mode shows
  breadcrumbs and folder rows (file count + size); the filter searches the current folder and
  everything below it. Backspace goes up one folder. n/p and audio auto-advance follow the view.
- Global search box in the header: searches Movies, Audio and PDF names and folders (all words
  must match), grouped results; click or Enter opens the file in its folder. Key: s.

## 0.6.1 (2026-10-17)

- Security: Host header allowlist (blocks DNS rebinding): IP literals, localhost, this hostname
  and <hostname>.local always pass; more names via allowed_hosts in the config file only.
- Security: Install of a staged update asks for the password again.
- Fix: "Use this drive" refuses while an upload is running (the upload stayed behind on the SD).
- Fix: leftover .upload-*.part files are swept only at startup / fresh mount (recursively), never
  on a config save (that deleted the temp file of a running upload).
- Fix: an ejected drive is auto-mounted again once it has been unplugged and reconnected.
- Fix: non-object JSON bodies get a 400 instead of a handler traceback; /favicon.ico is a 204.
- Fix: the session cookie is renewed while in use (it expired 12h after login even if active).
- Fix: --port no longer shows a permanent "restart required" banner; FAT/exFAT/NTFS-illegal
  upload names are rejected up front; import lists are cached per tab.

## 0.6.0 (2026-10-16)

- View panel (per browser): dark/light/auto theme, text size, density, list/grid media view.
- Sort direction toggle and a "Recently added" sort (inode change time).
- Toasts for minor messages; log viewer with level/text filters and Download.
- Cast button (browser Remote Playback / AirPlay) in the player where supported.

## 0.5.2 (2026-10-16)

- Audit fixes: lsblk failure no longer unmounts anything (2-scan debounce); failed/cancelled
  "Use this drive" unmounts what it mounted; "Use SD card" refuses while busy and unmounts first;
  "Import only" survives the watcher; migration never overwrites differing files unless opted in;
  optional checksum verify; Delete SD originals verifies SHA-256 (as a job); error payloads keep
  "problems"; import JSON cap 512KB; rollback guard checks /api/health version; 300s stream stall
  timeout with a visible countdown badge and /api/streams.
- SD-write policy: update staging lives on the library drive while mounted, syntax check is in
  memory (no temp files), SD writes (config, password, rollback copy, install) are counted.
- UI: numbered Config flow ending with Save, login-off banner, remembered tab/sort/filter,
  keyboard shortcuts, per-tab size + free-space bar, Download / Copy link.

## 0.5.1 (2026-10-15)

- Import from a second USB drive: once a library drive is set, other drives are mounted
  read-only at /mnt/pibrary-import/<uuid>; each media tab can list and copy files from them
  into the library (atomic, resumable, never modifies the source drive).

## 0.5.0 (2026-10-15)

- USB library drive: detection (lsblk), Use this drive (mount rw by UUID, layout
  <drive>/pibrary/{movies,audio,pdf}), copy-first migration from the SD card with progress,
  cancel and verify, optional delete of verified SD originals, copy back / Use SD card,
  Eject, auto-remount of the saved UUID, offline guard (never writes under an empty mountpoint).

## 0.4.1 (2026-10-15)

- Version bump only, for testing the Software update flow (stage, install, rollback guard).

## 0.4.0 (2026-10-15)

- Config tab "Software update" card (mirrors instmon's upload/stage/install flow): upload a
  Pibrary*.py (raw streamed, 5MB cap), validated (py_compile + Pibrary markers + version),
  staged in <install dir>/staged (newest 3 kept), then Install runs its own --install.
- Rollback guard: a one-shot systemd timer reinstalls the previous version if the port is
  down 60s after an update. Requires login + new allow_update setting (default off).

## 0.3.2 (2026-10-15)

- Player Close button (Movies/Audio): unloads the media, aborts the stream (frees a
  max_streams slot), clears the playing highlight. Esc closes the active player.
- Leaving the Movies tab now closes the video instead of only pausing it.

## 0.3.1 (2026-10-15)

- Fix: upload names are limited to 200 BYTES (was 200 chars; multibyte names hit ENAMETOOLONG/500).
- Fix: changing library_root/extra_roots now clears the scan cache and creates the tab subdirs.
- Fix: audio auto-advance follows the current list order even if the filter/sort changed.

## 0.3.0 (2026-10-15)

- Upload card on each media tab: raw-body XHR streamed to disk in 64KB chunks (no RAM
  buffering), per-tab extension allowlist, overwrite confirm, progress/cancel.
- Atomic writes everywhere: temp file + fsync + os.link/os.replace + directory fsync;
  stale .upload-*.part files swept at startup. New settings: max_upload_mb.
- allow_write now gates uploads (still requires login).

## 0.2.0 (2026-10-15)

- Movies / Audio / PDF tabs: per-tab subdirs (movies/, audio/, pdf/) under library_root,
  on-demand recursive scan (30s in-memory cache), filter/sort, native video/audio players
  (audio auto-advances), PDFs open in the browser reader. Range-capable streaming with a
  max_streams cap and realpath containment.

## 0.1.0 (2026-10-15)

- Left/right margin tab rail (tab_side, L/R checkboxes in Config); Status is the front
  page; Config always last. Pibrary password (scrypt, pibrary.auth, 0600) with root
  password fallback when none is set.

## 0.0.0 (2026-10-15)

- Phase 1 skeleton derived from instmon v2.51.0: HTTP server, root-account
  auth/session/lockout code (verbatim), X-Requested-With CSRF check,
  sd_notify watchdog, --install/--uninstall self-installer, in-memory log.
- Auth is OFF by default and toggled from the Config tab (live, no restart).
- Tabs: Status (placeholder), Config (INI-backed settings).
- Default port 9000. Library root /srv/pibrary/media (unused until Phase 2).
