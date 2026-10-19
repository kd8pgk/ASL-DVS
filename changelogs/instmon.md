# instmon changelog

Current file: `instmon_v2_59_0_20261019.py`. Newest entries first.

## 2.59.0 (2026-10-19)

- **Component cards show only the selected build.** The SysMon and Dashboard
  cards list library files and GitHub rows for the build this node uses, and hide
  the other build's files instead of tagging them "other build". On a Pi Zero 2 W
  that follows the "Pi Zero 2 W build" choice (Pi02w fork or Full build); on any
  other Pi it is the full build. The installed file always stays listed, even when
  it is the other build (Full Update switches it). The GitHub summary counts only
  the files shown. Hidden files stay in the library; nothing is deleted, and the
  other tools' cards are unchanged.

## 2.58.0 (2026-10-18)

- **Node Listen** (`nodelisten`, port 8993) joins the tools instmon manages:
  - a component card (status, port, install, start, stop, restart, uninstall), as for
    wifimon and 44helper;
  - a library group (`/etc/asl_dvs/instmon_library/nodelisten`) for `nodelisten*.py`,
    with uploads, the home-folder scan, USB import and GitHub Updates;
  - **Full Update** updates it after wifimon, and only where it is installed ("not
    installed -- left alone" otherwise), like every other tool;
  - **Quiet System** pauses it with SysMon, the Dashboard and 44helper (the button's
    text says so).

## 2.57.0 (2026-10-18)

- **Stop Full Update.** A Stop Full Update button shows on the GitHub Updates card while
  Full Update runs. It stops the install step that is running, puts the tool being
  updated back to the version it had (from its library copy, the same way a failed
  update is put back), skips the tools not reached yet and instmon, restarts the paused
  web tools, and the finished banner says "stopped by you". Putting the old version
  back is never stopped halfway. The button is hidden while instmon installs itself.
- **A tool's install survives an instmon restart.** Full Update now runs each tool's
  `--uninstall` / `--install` as its own systemd unit (`instmon-fu-job`, through
  `systemd-run --wait`, capped at the 10-minute script limit) and reads its output from
  a log file. Restarting instmon no longer kills the install halfway through and leaves
  the tool removed. Without `systemd-run` it runs the step directly, as before.
- **Recovery after a restart in the middle of an update.** Full Update records which
  tool it is on. If instmon restarts before that tool is done, on startup it waits for
  a still-running install step to finish, then checks the tool: if it is installed
  and answering it is kept (listed as updated when it is the new version), otherwise
  the version it had is put back from the library. Then the finished banner shows.

## 2.56.0 (2026-10-18)

- **Install and uninstall output shows up as it happens.** A tool's `--install` and
  `--uninstall` now run with `PYTHONUNBUFFERED=1`, so each line it prints reaches the
  log right away. Before, Python held its printed lines until the script finished,
  and only the lines from programs it ran (such as systemctl's "Created symlink")
  came through. So during a slow step (magicbox: 44helper's install waiting for its
  restart to finish) the log looked stuck. Applies to Full Update and to the
  Install / Uninstall buttons.

## 2.55.0 (2026-10-18)

- **Full Update counts down its waits.** While it waits for a tool it just installed
  (up to 60 s to start and answer, then 60 s to make sure it stays up), the progress
  line on the Full Update card now ends with "waiting for v… to start and answer: 42s
  left" or "waiting for v… to stay up: 17s left", counting down each second. The
  countdown ends as soon as the tool answers. The rollback wait has a countdown too,
  and now logs its own "waiting up to 60s" line.

## 2.54.0 (2026-10-18)

- **Full Update says what it is waiting for.** After installing each tool it waits up to
  60 s for it to start and answer, then watches it for 60 s to make sure it stays up,
  and the log was silent for those two minutes, so it looked frozen (magicbox: after
  SysMon's install, with the Pi Zero 2 W busy enough that `lsblk` timed out). It now
  logs "waiting up to 60s for v… to start and answer" and "v… is up; watching it for
  60s". Restarting instmon in that window stops the update; Quiet System is put back
  at start, and running Full Update again finishes it.
- **The page's own log lines use local time.** Lines the page adds itself (such as
  "Full Update started -- progress shows …") were stamped in UTC, so they sat hours
  away from the server's lines. They now use the browser's local time.

## 2.53.0 (2026-10-18)

- **Start-up recovery after a power loss no longer holds up instmon or reports false
  failures.** When a disk image or Quiet System was cut off by a power loss, instmon
  restarted each stopped service with a blocking `systemctl start` (up to 30 s each)
  before serving its page. Services held at boot behind `44helper-netready` timed out
  and were reported "did NOT come back … A reboot is recommended" while they were
  still starting. Now services that are already running, or already have a start job
  queued, are left alone; the rest are started without waiting (`systemctl start
  --no-block`), and a background check watches them for up to 5 minutes
  (`INSTMON_QUIESCE_RECOVER_WAIT_SEC`, default 300) before reporting only the ones
  that really didn't come back. A service systemd refuses to start (missing or masked
  unit) is still reported at once and kept in the quiesce state file.
- Tested (mocks): active and queued units skipped; no-block start; state cleared and
  "back on the air" logged when they come up; a unit still queued at 5 minutes is the
  only one reported; a refused start reported at once; no blocking start used.

## 2.52.0 (2026-10-18)

- **Scheduled backups wait 15 minutes after boot.** A scheduled disk-image backup
  that was overdue started about a minute after boot, stopping the radio services
  while the network, the tunnel and 44helper's boot order were still bringing them
  up. Now the scheduler holds it until the node has been up 15 minutes; the card
  shows "Scheduled backup not started: the node booted N min ago …" once, and the
  backup runs on the next check after that. Manual backups are not affected.
- Tested (mocks): held 2 minutes after boot with the reason saved and logged once;
  not held 33 minutes after boot.

## 2.51.0 (2026-10-14)

Fix: a GitHub check could hang, and switching the update channel during a
check showed the old channel's result. instmon serves both builds.

- **Time limit on Check GitHub.** A check that has not finished after 4 minutes
  (`INSTMON_GH_CHECK_LIMIT_SEC`, default 240) is marked failed ("GitHub did
  not finish answering ... check this node's internet connection"), and
  Check GitHub works again. Before, a check stuck on a slow or dead connection
  stayed "Checking..." until instmon was restarted.
- **Switching the channel stops a running check.** The log says "The running
  GitHub check was stopped -- the channel changed", and when the old check
  finishes later its result is dropped ("An earlier GitHub check finished late
  -- its result was not used"). Before, the old Stable result came in after the
  switch and was shown under the Testing label, so the switch looked like it
  had not happened.
- **Progress in the log** during a check: how many files the stable list (or
  main) has, and each file it has to download to read its version ("GitHub:
  reading <file> (2 of 3)"). The result line ends with how long the check took.
  The summary line says "progress is in the log below" while it runs.
- **No doubled log lines.** When the node answered slowly, two log polls could
  overlap and print the same line twice (for example "GitHub check started"
  twice). The page now runs one log poll at a time and skips lines it already
  has.

## 2.50.0 (2026-10-14)

Release channels, and a 60-second check after each update (reliability plan,
Stage 5). instmon serves both builds. This is the first instmon that reads
the stable channel, so it is also the oldest instmon the stable channel will
ever offer.

- **Update channel** on the GitHub Updates card:
  - **Stable (default)** reads `channels/stable.json` from the repo and
    downloads each file from the exact commit listed there. The git blob id
    is checked, as before.
  - **Testing (opt-in)** is what instmon did until now: the newest file on
    `main`. Switching to Testing asks first.
  - Switching clears the last check; press Check GitHub again.
  - Manuals still come from `main`.
- **No automatic downgrade:**
  - **Library newer than stable:** the row says **Ahead of stable**, with a
    **Get stable** button. Get stable asks first, then puts the older stable
    file in the library, checked. Nothing installs until you press Install
    on it.
  - **Installed version newer than stable:** Full Update leaves the tool as
    it is ("installed vX is ahead of stable vY -- left alone").
  - **A tool with no stable build yet** shows "no stable build of X yet".
  - If the repo has no stable list, the check says so and suggests Testing.
- **60-second watch after an update.** Before, Full Update accepted a tool
  once it was running and its port was open. A build that crashed 20 s
  later, or missed its systemd watchdog, was kept and restarted over and over.
  - Now Full Update watches each updated tool (except instmon itself) for 60
    seconds. Every 3 s it checks: the service is still active, its systemd
    restart count hasn't gone up, its port is open, and it answers HTTP
    (`/healthz`, or any reply, so older tools count too). One missed answer
    is tolerated; three in a row fail.
  - If the watch fails, the existing rollback puts the previous version back.
  - A manual **Install** gets the same 60-second watch, but only logs the
    result: you picked that version yourself.
  - `INSTMON_FU_STABLE_SEC` changes the 60 s (0 turns the watch off).
- Tested:
  - Unit tests with mocks (13):
    - the channel defaults to Stable; Testing needs confirmation
    - the stable list: bad entries skipped, download URL pinned to the commit
    - no stable list -> "switch to Testing"
    - Stable reads the list, never the GitHub file listing; Testing reads
      the listing
    - Get stable: refused without its flag, refused on Testing, works on
      Stable, and the row shows Ahead of stable with the button
    - Full Update plan: ahead of stable -> left alone; no stable build ->
      says so
    - the watch: steady passes; a restart, an inactive service, or 3 missed
      answers fail; one blip is tolerated
    - a real HTTP server: a 404 counts as alive, a closed port doesn't
    - Full Update: an unsteady new version is rolled back to the old file
  - The 2.49.0 lock tests (7) still pass.
  - The page in headless Chromium:
    - the channel choice starts on Stable
    - a cancelled switch stays on Stable; a confirmed one saves Testing to
      `instmon_channel.json`
    - the summary names the channel
    - the Get stable row
    - no horizontal scroll at 390 px, no script errors
  - `ci/check_repo.py`

## 2.49.0 (2026-10-14)

A lock on every library version, so a file you want to keep can't be deleted
or replaced by accident. instmon serves both builds.

- **Lock checkbox** on each version row of each component card and library
  group, next to Install, Edit, Download and Delete.
  - Checking it locks the file at once.
  - Unchecking asks first: "Unlock X? It can then be deleted or overwritten."
    Cancel keeps it locked.
  - Locks are kept in `/etc/asl_dvs/instmon_locks.json`, so they survive
    restarts and updates. New files start unlocked.
- **While a file is locked**, instmon refuses (on the page and on the server):
  - **Delete:** the button is greyed out, and the server answers 409 if asked
    anyway.
  - **Overwriting it with different content:** Upload & stage, USB import,
    GitHub download into the library, and Edit -> Save. Uploading the
    identical file is still fine.
  - Install, Download and Edit (to read) still work.
- instmon never deleted library files on its own. Each tool's own `--install`
  and `--uninstall` manage only that tool's installed copy under
  `/usr/local/lib/asl_dvs/`, not the library, so the lock doesn't affect
  them.
- Tested:
  - against a real instmon server (7 tests):
    - delete refused while locked
    - unlock refused without confirmation, then allowed with it
    - the lock is saved to disk
    - upload: a different file is refused, the identical file and a new name
      are accepted
    - Edit -> Save refused while locked and allowed after unlocking
    - GitHub download refused while locked
    - bad requests (unknown category, missing file, `../` paths, non-boolean)
    - the row renders the checkbox and greys out Delete
  - the page in headless Chromium: check -> locked and Delete greyed; unlock
    cancelled -> stays locked; unlock confirmed -> unlocked; no horizontal
    scroll at 390 px; no script errors
  - `ci/check_repo.py`

## 2.48.0 (2026-10-14)

Web requests can no longer hang a thread forever (reliability plan,
Stage 3a). instmon serves both builds.

- Every web connection now has a 60-second idle limit. Before, there was
  none. A phone that dropped off WiFi in the middle of a request, or any
  client that connected and sent nothing, held one of instmon's threads
  until instmon restarted. On a 512 MB Pi those added up.
- The limit counts silence, not total time. A slow upload or download that
  keeps moving still finishes. Installs, Full Update and disk-image jobs
  are not affected: they run in their own threads, not on the web
  connection.
- Tested:
  - with a real server on a free port: idle clients are dropped and their
    threads freed; a client that sends its request a few bytes at a time
    still gets its answer; normal requests still work; the handler's limit
    is 60 s
  - `ci/check_repo.py`

## 2.47.0 (2026-10-13)

Easier to read: the grey-blue text is white, as in 44helper, SysMon, the Dashboard
and wifimon. instmon serves both builds. Only text colours and the title change.

- **Grey-blue text is now plain white `#ffffff`:**
  - `--text` (was `#d0dff0`), the body text
  - the header sub-line, the header meta line and the column headers (was
    `#5a7898`)
  - the script editor text (was `#c8d8e8`)
- **Notes and placeholders are no longer dimmed.** The Disk image notes, the
  quiesce note and the "(no job running)" placeholders were white at 55–75 %
  opacity, which made them grey. They are now full white.
- **The disk-image off-air warning text** is bright red (was pale salmon).
- Log lines, pop-ups and the Full Update banner were already green for success
  and red for failure; they are unchanged. Warnings stay amber.
- **Title:** the page title and logo say "Install Monitor" (was "ASL-DVS Install
  Monitor"), per the naming rule.
- Tested:
  - The page in headless Chromium, before and after: body text
    `rgb(255,255,255)`, success lines `rgb(0,255,176)`, failure lines
    `rgb(255,61,90)`, placeholders and notes at full opacity, no script errors.
  - `node --check` on the page JavaScript.

## 2.46.0 (2026-10-12)

Full Update turns on when only the manuals have changed.

- **Check GitHub** also reads the `docs` folder (one more GitHub API call).
  Manuals that are new or changed there are listed in the Full Update plan as
  **Manual NEW** or **Manual CHANGED**, and count toward turning the Full Update
  button on, so a manuals-only change can be applied without any tool update.
  The confirm dialog lists them too. If the docs list can't be read, the check
  still finishes and the last list is kept.
- The plan refreshes after Get from GitHub, an upload or import to Manuals, a
  Delete, and a Full Update, so the button goes off once nothing is pending.
- A manual you delete is remembered in `/etc/asl_dvs/instmon_manuals_deleted.json`.
  It is not listed in the plan and Full Update no longer brings it back
  (2.45.0 did). **Get from GitHub** still restores it, and an upload or USB
  import with that name clears the mark.
- Tested with GitHub mocked: a check lists new manuals and turns the button on;
  after Get from GitHub nothing is pending; a manual changed on GitHub shows as
  CHANGED; Full Update fetches it and the button goes off; a deleted manual
  stays out of the plan and isn't restored by Full Update, even after GitHub
  changes it; Get from GitHub restores it; an upload clears the mark; a check
  survives an unreachable docs list. The 2.45.0 tests still pass. Page in
  headless Chromium: plan rows, button enabled, confirm text, no script errors.

## 2.45.0 (2026-10-12)

The manuals come with the install and stay current.

- `--install` downloads the manuals (PDF) from the repo's `docs` folder into the
  Manuals folder and prints each one. With no internet the install still
  finishes and says the manuals will follow.
- When instmon starts and has never downloaded the manuals, it tries in the
  background after 5 seconds, then 1, 2 and 5 minutes later. A file in
  `/etc/asl_dvs/instmon_manuals_fetched` records the first successful download,
  so a manual you delete doesn't come back every restart.
- Full Update has a Manuals step after the scripts and before instmon's own
  update. It downloads only the manuals that are new or changed on GitHub, runs
  even when every tool is current, and lists them under **Manuals** in the
  summary ("N manual(s) updated"). If it fails, it shows as a skipped row and
  the tools still update. A manual you deleted comes back on a Full Update, as it
  does on Get from GitHub.
- The **Get from GitHub** button, `--install`, the start-up download and Full
  Update all use the same fetch and the same checks: name, 64 MB limit, git blob
  id against GitHub's list, `%PDF-` header.
- There is no setting to turn this off.
- Manuals card text and the Full Update confirm dialog mention the manuals.
- Tested with GitHub mocked: `--install` online and offline, the start-up
  retry after a network error, no re-download of a deleted manual on restart,
  Full Update taking only new or changed manuals, still checking them when every
  tool is current, a failed manuals step shown as skipped, and a running Get from
  GitHub left alone. Page loaded in headless Chromium with no script errors and
  no sideways scrolling at 390 px.

## 2.44.0 (2026-10-12)

- Manuals card: **Upload PDF** adds any PDF from your computer to Manuals, where
  it can be opened in the browser's own PDF reader or downloaded like the
  manuals from GitHub. A `.pdf` chosen in any library group's **Upload & stage**
  goes to Manuals as well (no other library group takes PDFs). The rules are
  those of a USB import: odd characters in the name become `_`, the file must
  start with `%PDF-`, and the upload size limit applies (50 MB unless
  `INSTMON_MAX_UPLOAD_MB` says otherwise). A non-PDF chosen on the Manuals card
  is refused.
- Each manual has a **Delete** button (asks first). `POST /api/docs/delete`
  only removes a `.pdf` in the Manuals folder. A manual from GitHub that is
  deleted comes back on the next Get from GitHub.
- On a phone each manual's buttons go on a line under its name.
- Tested in headless Chromium against the real handlers: a PDF with spaces in
  its name uploaded on the Manuals card (saved with `_`), a PDF uploaded through
  the Scripts group's Upload & stage, a `.sh` and an HTML file named `.pdf`
  refused, Open serving `application/pdf` inline, Delete removing one, a `../`
  name refused with 404, no page errors, and no sideways scrolling at 390 px.

## 2.43.0 (2026-10-12)

Ready for the renamed tools: the Dashboard becomes `nodecontrol`
(`nodecontrol.service`, `/usr/local/bin/nodecontrol.py`), 44helper's file
becomes `44helper_v….py`, and the installer and uninstaller become
`install_all_v….sh` and `uninstall_all_v….sh`. Old and new names both work, so
this instmon goes on a node first.

- The Dashboard is found as `nodecontrol`, or as `asl_dvs_dashboard` on a node
  that hasn't switched yet. Status, Start, Stop, Restart, Quiet System, Full
  Update and the health checks all use whichever unit is installed. The program
  is looked up at `/usr/local/bin/nodecontrol.py`, then at the old path.
- Old and new file names count as the same tool. `asl_dvs_dashboard*.py` and
  `nodecontrol*.py` are both the Dashboard, `asl_dvs_m17_44helper*.py` and
  `44helper*.py` are both 44helper, and so on, so the library, Check GitHub and
  Full Update compare them as one. Full Update sees an installed
  `asl_dvs_dashboard_pi02w` as the same build as `nodecontrol_pi02w`.
- `install_all*.sh` and `uninstall_all*.sh` are run as the installer and
  uninstaller, the same as the old names.
- Installing an older Dashboard over `nodecontrol` (Install on an ALT file, or a
  Full Update rollback): `nodecontrol.service` is disabled and removed first,
  so two dashboards never fight over port 8989. A file that names both units
  (a renamed Dashboard, which moves itself) is left to do it.
- Launcher version 3 (the same text in every tool that writes it): a tool file
  whose name starts with a digit, like `44helper_v….py`, is loaded through
  `importlib`, so its compiled copy in `__pycache__` is used instead of being
  recompiled on every start.
- Retiring `nodecontrol.service` also removes `/usr/local/bin/nodecontrol.py`
  and `/usr/local/lib/asl_dvs/nodecontrol/`, so nothing stale is left for the
  old Dashboard's own uninstall to miss.
- Tested with mocks: which unit and path are picked on an old node, a renamed
  node and a node with both; when the other unit is retired and when it is
  not; the name aliases and Full Update stems for every renamed file; and
  installer and uninstaller detection under both names.

## 2.42.0 (2026-10-12)

- Import from USB Drive takes manuals too, for a node with no internet. `.pdf`
  files are listed with the others, and importing one puts it in Manuals
  (`/etc/asl_dvs/instmon_library/docs/`) whatever library group is picked. The
  name keeps letters, digits, `.`, `_` and `-`; anything else becomes `_`
  (`ASL-DVS User Manual (copy).pdf` is saved as `ASL-DVS_User_Manual_copy.pdf`).
  The file must start with `%PDF-`, and the limit is 64 MB, the same as Get from
  GitHub. Importing the same file again does nothing. The Manuals card updates at
  once.
- Tested in headless Chromium with a folder standing in for the stick: the PDF
  is listed (a `.txt` is not), imports with the Scripts group selected, shows in
  Manuals and opens as `application/pdf`; an HTML file named `.pdf` is refused;
  a second import says it is already there; no page errors.

## 2.41.0 (2026-10-12)

- **Manuals** card, below the library. **Get from GitHub** downloads the PDFs in
  the repo's `docs` folder into `/etc/asl_dvs/instmon_library/docs/`, only those
  that are new or changed (the git blob id of the copy on the node is compared
  with GitHub's list). A download is kept only if its blob id matches the list
  and it starts with `%PDF-`; 64 MB limit per file. Each manual has **Open**,
  which shows it in a new tab in the browser's own PDF reader, and **Download**,
  which saves it. Rows line up at any width.
- `/api/docs` (list and fetch state), `POST /api/docs/fetch`, and
  `/api/docs/file?name=...` (`&download=1` to save), all behind the login. The
  file route only serves names ending in `.pdf` from that folder. PDFs are sent
  without `X-Frame-Options` and the page's `Content-Security-Policy`: the
  browser's PDF reader doesn't need them and can refuse to show a PDF under them.
- Download Full Backup leaves the manuals out; they can be fetched again.
- Tested in headless Chromium against a stubbed GitHub serving this repo's
  `docs` folder: the card fills, a second fetch downloads nothing, Open sends
  `application/pdf` inline with no frame or CSP header, Download saves the file,
  a `../` name gets 404, no page errors, and no sideways scrolling at 390 px. The
  fetch was also run against a wrong blob id, a non-PDF, an oversize entry and
  an unreachable GitHub. The inline PDF viewer itself can't be shown headless.

## 2.40.0 (2026-10-12)

First step of the standard install layout: the program lives in
`/usr/local/lib/asl_dvs/<tool>/` under its own versioned name, and
`/usr/local/bin/<tool>.py` is a symlink to it.

- `--install` copies the file to `/usr/local/lib/asl_dvs/instmon/` and points
  `/usr/local/bin/instmon.py` at it. An old plain copy at that path is replaced
  (the link is swapped in with one rename, so the path is never missing), and
  any other version left in the lib folder is removed. Running `--install`
  through the link itself changes nothing.
- `--uninstall` removes the link, the lib file, and the lib folder (and
  `/usr/local/lib/asl_dvs/` if that is then empty).
- Unit: `Type=notify` with `NotifyAccess=main`; instmon reports ready once it is
  listening on 8990. `TimeoutStartSec=600` covers a start that first has to bring
  back services left stopped by a disk-image job.
- 44helper's path is now `/usr/local/bin/44helper.py`, with
  `/opt/44helper/asl_dvs_m17_44helper.py` as a fallback. instmon uses whichever
  path the 44helper unit runs, so a node on 44helper 0.0.179 or older still
  shows it as installed.
- Before any `--install` (Install, Full Update and its rollback, and instmon's
  own update guard), a symlink at the tool's path is replaced with a plain copy
  of the file it points to. Older tools copy themselves onto that path, and
  without this the copy would land inside the newer file in the lib folder.
- Tested with mocks against a temporary root: a fresh install, an install over
  an old plain copy, and an install over a newer layout; reinstall through the
  link; uninstall; the 44helper path choice; the de-link step and the guard's
  shell version of it; and `READY=1` from a real start.

## 2.39.1 (2026-10-11)

- USB import: ext3 and ext4 drives are now mounted with `noload` as well as
  `ro`. A read-only mount still replays the journal of a drive that was not
  unmounted cleanly, and that writes to the drive. With `noload` nothing is
  written, so the drive is left exactly as it was. (A drive pulled mid-write may
  show the files as they were before that write.) ext2, FAT, exFAT and NTFS have
  no journal to replay and are mounted as before.
- USB import: no polling of its own. The drive list now comes from the Disk
  Image card's drive check, which already ran every 5 seconds, so the page asks
  for the USB drive list once per 5 seconds instead of twice (one `lsblk` run
  fewer every 5 seconds on a Pi Zero). Refresh still re-reads the drives at once.
- Tested: the mount command for each filesystem with `mount` mocked, and the card
  in headless Chromium with the API mocked: the drive list fills from the Disk
  Image poll, a new drive shows up on the next poll, `/api/usbimport/drives` is
  only fetched when Refresh is pressed.

## 2.39.0 (2026-10-11)

- **Import from USB Drive** card, above the library. It lists attached USB
  drives (never the boot disk), lets you browse their folders, and copies `.py`,
  `.sh` and `.conf` files into the library category you pick. The extension,
  file-name and size rules are the same as a browser upload, and so is the
  "doesn't look like a ... file, import anyway?" prompt. Hidden entries, symlinks
  and `System Volume Information`, `lost+found` and `$RECYCLE.BIN` are left out,
  and a folder lists at most 500 entries.
  - A drive that is not mounted yet is mounted read-only (`ro,nosuid,nodev,noexec`)
    under `/mnt/instmon-usbimport/<drive>` for each request and unmounted after.
    A drive already mounted is used where it is. FAT, exFAT, ext2/3/4 and NTFS
    (with `ntfs3` or `ntfs-3g`) are supported.
  - Paths are resolved inside the drive only: `..`, NUL bytes and links that
    point off the drive are refused, and the file is opened with `O_NOFOLLOW`.
  - It waits while a disk-image job is running.
  - The drive list refreshes every 5 seconds while the page is visible.
  - New endpoints, behind the login (and the `X-Requested-With` check for the
    POST): `GET /api/usbimport/drives`, `GET /api/usbimport/browse`,
    `POST /api/usbimport/import`.
- Browser upload and USB import now share one validation and write path.
  Upload behaves as before.
- Removed an unused `base64` import.
- Tested: browse and import against a test folder (hidden entries, symlinked
  files and folders, `..`, NUL, a name mismatch with and without force, a folder,
  unchanged re-import), and the card in headless Chromium with the API mocked.

## 2.38.3 (2026-10-07)

- Page layout: the columns on the instmon page did not line up. Each row sized its
  own version, name and badge, so a long version such as `9.3.71.13-pi02w` pushed
  its file name and badge to a different place than a short one such as `9.3.73`.
  Seen on a Galaxy Tab S6 Lite.
  - **Components:** name, version, state and port now sit in fixed columns, with
    the service name on a second line, so every component card lines up.
  - **Library lists:** version, file name and INSTALLED/ALT badge sit in fixed
    columns in every library group.
  - **GitHub update rows:** the status tag, the GitHub version, the other-build
    tag and the Update button sit in fixed columns, with the file name on a
    second line. Empty cells are now emitted so a row without a tag or button
    keeps the others in place. Badges and tags keep their natural width.
  - On a phone the page was 31 px wider than the screen because long file names
    in the GitHub rows did not wrap; they now wrap, and the page fits. The phone
    layout is otherwise unchanged (columns apply from 561 px up).
- Measured in headless Chromium at 390, 600, 800, 980 and 1280 px with every
  component, library group and GitHub status filled in: the old build was off by
  up to 188 px (library) and 80 px (GitHub) from 600 px up, the new build is
  aligned at every width with no page overflow.

## 2.38.2 (2026-10-06)

- Launcher version 2 (`/usr/local/bin/asl_dvs_launch.py`, the same file every ASL-DVS `--install` writes) adds three memory savers, each with an off switch. Create the file and restart the service to turn one off; delete it and restart to turn it back on.
  - `python3 -OO`: drops docstrings from the loaded code. Off: `/etc/asl_dvs/launch_no_optimize`
  - `MALLOC_ARENA_MAX=2`: at most 2 malloc pools instead of up to 8 per CPU core. Off: `/etc/asl_dvs/launch_no_arena_cap`
  - `malloc_trim`: 1 minute after start, then every 5 minutes, freed memory is handed back to Linux. Off: `/etc/asl_dvs/launch_no_trim`
  
  The service files are unchanged: the launcher starts Python once more with `-OO` and `MALLOC_ARENA_MAX` (same PID, so systemd notify and watchdog are not affected). The launcher itself is comment-stripped too.

- Repo copy is comment-stripped. The change history that was in the file's comments now lives in this changelog.


## Earlier history

Carried over unchanged from the comments of the files below.

### instmon_v2_38_2_20261006.py (module docstring)

```text
instmon v2.38.2 (2026-10-06) - KD8PGK Web Installer & Component Manager
Build: common (all nodes, including Pi Zero 2 W)

Full version history: see CHANGELOG.md. This docstring intentionally
stays short now -- it used to carry the entire changelog inline (see
CHANGELOG.md's own note, and its v1.26.0 entry, for why that moved).
```

### instmon_v2_38_2_20261006.py (version history comment on DATE_STR)

#### v2.38.1

v2.38.1 --uninstall no longer stops part-way if a compiled copy or the launcher is already gone (removed by another uninstall at the same moment).

#### v2.38.0

v2.38.0 Pi Zero 2 W build choice: on a Pi Zero 2 W (device-tree model "Zero 2") the GitHub Updates card shows a "Pi Zero 2 W build" choice -- Pi02w fork (default) or Full build (override), saved in /etc/asl_dvs/instmon_build.json; Full Update now installs the chosen build of SysMon and the Dashboard, and switches an installed build that does not match (full -> fork or fork -> full, shown as SWITCH) the same way it updates -- library copy, --uninstall, the other build's --install, rollback on failure; tools with one common build are not affected; on other Pis nothing changes (each component keeps the build it has). Check GitHub marks the rows of the build this node does not use as "other build".

#### v2.37.1

v2.37.1 Launcher: instmon.service now starts /usr/local/bin/asl_dvs_launch.py /usr/local/bin/instmon.py -- the launcher imports instmon instead of running it, so Python keeps the compiled copy in /usr/local/bin/__pycache__ and reuses it on every later start (about 21 MB instead of 34 MB, twice as fast to start; recompiled by itself after an update); --install writes the launcher (same file the Pi02w sysmon/dashboard and installer v6.5 write), --uninstall removes instmon's compiled copy and the launcher once no unit uses it. Pi Zero 2 W sysmon build: Check GitHub keeps the full and the Pi02w sysmon builds apart -- both match sysmon*.py, so they were one kind and only one of them showed (or a false "same version, different file" conflict); the kind now also carries the VERSION suffix ("6.13.67-pi02w" -> pi02w), so each build gets its own row and is compared only with library copies of the same build.

#### v2.37.0

v2.37.0 Quiet System + Full Update: Quiet System / Restore (GitHub Updates card) pause SysMon, the Dashboard, 44helper and the watchdog timer(s) through the quiesce core with a new "quiet" scope -- never Asterisk, the bridges, Allmon3, wifimon or instmon -- share its state file (so a restart of instmon restores them, and a disk-image job and Quiet System can never overlap), auto-restore after 30 min (INSTMON_QUIET_AUTO_RESTORE_SEC), and drop a component that a later Install/Uninstall already restarted; Full Update (next to Check GitHub) reads the same GitHub listing, picks for every installed component the newest GitHub build of the same variant (file-name stem, or the VERSION suffix such as -pi02w), downloads and checks every file first with the GitHub Update checks, then pauses the web tools and, one component at a time (44helper, wifimon, Dashboard, SysMon, Watchdog), saves a library copy of the installed file, runs its --uninstall, runs the new file's --install and waits for the service and port; a failure puts the saved copy back and the component is skipped (or listed NEEDS ATTENTION if that fails too) and the run carries on; newer install scripts go to the Scripts library only, never run; Restore, then instmon last -- replaced in place by its own --install, with a transient instmon-update-guard timer that reinstalls the old copy if port 8990 is silent 90 s later; results are saved to instmon_full_update.json and the restarted instmon reports them; summary as a popup, in the log and as a banner until dismissed; while it runs every other action, upload, editor save and disk-image job answers 409. Check GitHub now also works out the Full Update list from the same listing (no extra GitHub request).

#### v2.36.1

v2.36.1 Login refresh: when a session expires or instmon is reinstalled/restarted, the page now reloads itself instead of popping the login box over the stale page (which mangled the text and, after login, restarted every poll timer a second time); the "Session expired" message is carried across the reload via sessionStorage and shown on the fresh login box; a once-only guard means a burst of 401s reloads once, and the boot-time login (fresh page, not logged in) never reloads, so no loop.

#### v2.36.0

v2.36.0 GitHub updates: Check GitHub reads the file list of kd8pgk/ASL-DVS (main) straight from GitHub -- no manifest or checksums to maintain -- shows the newest GitHub copy of each tool in its library group, Update downloads, checks (same file GitHub listed, version, shebang, syntax, --install support) and stages it in its own library folder; uninstall_asl_dvs*.sh added to Scripts with a double confirm.

#### Entry

wifimon card now points at the wifimon v5 web dashboard (port 8991, plain HTTP, Go button); M17 Dashboard and SVX Dashboard cards removed (component, library group + upload box, library folder, home-folder sweep pattern, and the M17 branch of config install).

#### v2.30.2

v2.30.2 Progress audit: reader uses read1() (was a blocking read(256) => 4 s+ batches, nothing for short jobs), throttled copies report via the read-side dd (pv prints nothing when stderr is a pipe), ddrescue status is captured (it writes to stdout, which was /dev/null) and its kB unit parsed, one-decimal %, bytes done/total, elapsed, windowed time-left, stall warning
