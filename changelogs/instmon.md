# instmon changelog

Current file: `instmon_v2_42_0_20261012.py`. Newest entries first.

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
