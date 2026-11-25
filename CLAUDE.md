# CLAUDE.md

## Scope: Pi Zero 2 W fork first

- Current work is on the **Pi Zero 2 W (pi02w) fork**.
- **Never change the full build** (`sysmon_v*.py`, `asl_dvs_dashboard_v*.py`
  without `_pi02w_`) unless the request explicitly names the full build. A
  change made to a pi02w file is not to be copied to the full build on its own.
- The common tools (instmon, wifimon, 44helper, the installer, the watchdog,
  the uninstaller) serve both builds. When a pi02w change needs one of them,
  say so before changing it.

## Archived: Node Talker for AMP

- **`amp_nodetalker_v*.py` is archived (2026-11-13).** No development until the
  owner says so: no new version, no fixes, no shared-look or shared-login
  changes, and it is left out of work that covers "every tool".
- Its file, changelog, tests and stable-channel entry stay as they are. If a
  shared function it copies (`shared/confio.py`) has to change, say so and ask
  before touching the AMP file.

## Naming: "Node Controller"

- **System names stay.** Paths, file names, service and unit names, markers and
  keys keep `asl_dvs` / `ASL-DVS` (for example `/etc/asl_dvs`,
  `asl_dvs_launch.py`, `#ASL-DVS-VIDEO-OFF#`, `ASL-DVS_User_Manual.pdf`, the
  repo name and its URLs).
- **Text docs** (manuals, guides): write "Node Controller" where the text says
  "ASL-DVS". Titles and headers drop "ASL-DVS"; a header that would be left empty
  says "Node Controller".
- **Code:** when a file gets a new version, drop "ASL-DVS" from its titles and
  headers only (page title, logo/header bar, tab and section titles, console
  banner). Other text in the code, and data it writes, stays as it is.
- **Exception:** SysMon's **ASL-DVS** tab keeps its name, in the code and in
  the docs (the tab button, its Edit-page checkbox, "Hide from ASL-DVS tab",
  and the manual's references to that tab).

## Repo conventions

- **Comment-stripped copies only.** Scripts in the repo carry no comments or
  docstrings. Keep the shebang, a Python `coding` line, and each `.sh` title
  line (`# name.sh  vX.Y (date)`), which instmon reads the version from. Text
  inside strings (page HTML/JS, units and files the tools write) is data and
  stays as it is.
- **A changelog per tool** in `changelogs/<tool>.md`. Every new version adds
  an entry at the top and updates the "Current file" line.
- **Every change gets a new version.** A release renames the file
  (`<tool>_vX_Y_Z_YYYYMMDD.py`) and updates the README file list. A cosmetic
  build (`N`, below) keeps the file name and only moves `VERSION` /
  `APP_VERSION` / `SCRIPT_VERSION` to the next four-part number. A pi02w
  version ends in `-pi02w`.
- **Versions are `X.Y.Z` or `X.Y.Z.N`.** `Z` is a release: any change in
  behaviour (for example `5.31.0`, `9.3.74-pi02w`). `N` is a cosmetic fix
  only: text, wording, colors or layout, with no change in what the code does
  (`9.3.74.1-pi02w`). Page JavaScript logic is behaviour, so it is a release.
  A release drops `N` (`9.3.74.2` -> `9.3.75`). Cosmetic builds never go to
  stable. A tool still on an old four-part number from before this rule
  (`9.3.71.18-pi02w`) moves to the next release (`9.3.72-pi02w`). A tool on
  two parts adds `.0` (`5.30` -> `5.31.0`). No letter suffix (such as `x`).
- **`bootstrap.sh` keeps its file name.** The one-line install in the README
  points at it, so it is never renamed. A change moves the version in its title
  line and adds an entry to `changelogs/bootstrap.md`.
- **Tools stay compatible across versions.** Each tool goes to stable on its
  own schedule, so a node can run any mix of stable and testing versions. A
  tool that uses something only a newer version of another tool provides
  works without it when it is missing.
- **Shared code** lives in `shared/confio.py`. Each function named in its
  `USED_BY` is copied unchanged into every tool listed there (a tool's own
  wrapper may call it); `ci/check_repo.py` fails a tool whose copy differs.
  Change the reference first, then copy it into every listed tool.
- **Login sessions follow one model** (`sess_*` and `lock_*` in
  `shared/confio.py`; each tool moves onto them in its own release). Two
  tiers: **standard** (12 h idle, no hard cap) and **strict** (2 h idle, 12 h
  hard cap). Strict: Terminal Monitor, 44helper and instmon. Everything else is
  standard. The cookie is refreshed about hourly while in use, tokens are kept
  only as hashes, a root password change ends every session, and **any logout
  button ends every session** (there is no second "log out everywhere"
  button). An alive probe (for example SysMon's console) never extends a
  session. Failed logins wait 5 s doubling to 300 s after 5 mistakes. Node
  Controller keeps the names `_SESSION_COOKIE_NAME`, `_require_auth` and
  `/api/login` that SysMon's Security tab looks for, and Node Controller and
  SysMon keep reading the shared `auth_session.json` in its current layout
  while nodes can run mixed versions.
- **The shared launcher** (`/usr/local/bin/asl_dvs_launch.py`) is written by
  several files. Its text must stay identical in all of them.
- **Manuals** (the user manual, the dialplan guide and the install manuals in
  `docs/`) are updated only when the request says so. A code change alone does
  not update them.
- **Manual font: Readex Pro.** The next time a manual or guide in `docs/src/` is
  rewritten or updated, switch its body font (`--sans`) from Inter to Readex
  Pro, embedded with `@font-face` from the same woff2 data the tools' pages
  embed (weights 400 and 700), so the PDF does not depend on the fonts of the
  machine that builds it. Keep the monospace font. Rebuild the PDF with its
  `build.mjs` and check the pages by eye.

## Android app (`android/`)

- **Node Talker Mobile** (was Node Talker for Android) is a Kotlin/Gradle
  project in `android/`. Its file, package, tag and APK names keep
  `nodetalker` / `NodeTalker`. The tool-file rules (one file per version,
  renamed each version) do not apply to it.
- **Version** is `appVersion` (`X.Y.Z`) in `android/app/build.gradle.kts`;
  `versionCode` is worked out from it. Any change under `android/` raises it
  and adds an entry at the top of `changelogs/nodetalker_android.md` with
  its "Current version" line updated (`ci/check_repo.py` checks this). No
  cosmetic fourth part.
- **The app's version mirrors Node Talker's.** When the APK is released,
  `appVersion` takes Node Talker's current `X.Y.Z` (drop a cosmetic `.N`).
  They need not match perfectly: an app-only change takes Node Talker's next
  number, and Node Talker's next release takes that number or a later one.
  The version must still be newer than on `main`, so a number is never
  reused. `versionCode` is `X*1000000 + Y*1000 + Z`; never change that
  formula back.
- **Kotlin and Gradle files carry no comments**, like the scripts.
- **No libraries** beyond the Kotlin standard library unless a phase needs
  one.
- **Package name** `io.github.kd8pgk.nodetalker` never changes (the Play
  Store ties the app to it).
- The `android` workflow builds and lints every change; on `main` it
  publishes the APK as a pre-release `android-vX.Y.Z`. From 0.3.2 it is a
  release build (not debuggable, no `-debug` in the name). Every build,
  published or not, is signed with the shared key in
  `android/app/debug.keystore` (public), so each one installs over the last.
  Signing with a private release key (added in 0.10.27) was rolled back in
  0.10.39 on 2026-11-11 and is not to be brought back until the owner asks.
- The app is not on the stable/testing channels: those update node tools.
- **After an Android build is merged, always post its APK download link**:
  `https://github.com/kd8pgk/ASL-DVS/releases/download/android-vX.Y.Z/NodeTalker-X.Y.Z.apk`
  (check the release exists first).

## Desktop app (`desktop/`)

- **Node Controller Desktop** is an Electron client in `desktop/`, written in
  JavaScript (not Python). It only shows the pages that nodes serve (see Layout);
  it holds no node tool and no Python. Linux
  first (AppImage); Windows later, after the owner approves the look. It is not
  on the stable/testing channels.
- **Crash reset.** The app writes `running.json` in its data folder at start and
  removes it on a normal quit; if it is there at the next start the last run
  did not exit cleanly and the layout is not restored (nodes, saved splits,
  certificates and learned schemes are kept). One copy runs at a time.
- **Schemes.** The tools on one node do not all use the same scheme (Node
  Controller is plain http; Node Talker, SysMon, Node Monitor and others are
  https with a self-signed certificate each), so each page has its own scheme,
  learned by retrying the other one when a page fails like a wrong scheme, and
  a node can trust several certificates.
- **Version** is `version` in `desktop/package.json` (`X.Y.Z`, no cosmetic
  fourth part). Any change under `desktop/` raises it and adds an entry at the
  top of `changelogs/nodecontroller_desktop.md` with its "Current version"
  line updated (`ci/check_repo.py` checks this).
- **No comments** in the `.js`, `.css` or `.html` files of `desktop/` (checked
  by `ci/check_repo.py`), like the scripts.
- **No runtime libraries.** `package.json` has no `dependencies`; only
  `electron`, `electron-builder` and `@electron/fuses` as dev dependencies.
- **Electron stays on 44.x.** Electron 45.4.1 crashed the whole app (a
  segfault inside Electron) when SysMon opened on a Debian machine; 44.11.5
  does not (0.11.6). Move to 45 or later only after SysMon, Node Talker and
  Node Monitor open on a Debian test machine with that version.
- **Packed at normal compression** (since 0.11.9): about 123 MB, but it
  starts about seven times faster than at maximum compression.
- **Launcher** (since 0.12.0). Only when the user clicks **Add to menu** (shown
  when the app runs from an AppImage), the app copies the AppImage to
  `~/.local/share/node-controller/`, writes
  `~/.local/share/applications/nodecontroller.desktop`, the icon under
  `~/.local/share/icons/hicolor/256x256/apps/` and the same launcher in the
  Desktop folder (read from `user-dirs.dirs`; the app runs no other program,
  and the policy test still forbids `child_process`). **Remove from menu** takes
  them all away. The window
  class and `desktopName` are `nodecontroller`, so docks group the window with
  the entry (X11 and Wayland). The AppImage's own desktop entry carries no
  `--no-sandbox` (`appImage.executableArgs` is empty). The icon is
  `desktop/build/icon.png` (512 px) and `desktop/ui/icon.png` (256 px).
- **The lockdown is the contract.** Pages get only the audio-only microphone,
  speaker choice and clipboard writes, and only from their node; they may
  request only their own node; Last Heard is the one tile that may use the
  public internet, never private addresses unless a saved node. No devtools,
  remote debugging, updater, telemetry or crash reporter; the Chromium sandbox
  stays on (where the AppImage's start script turns it off because the system
  blocks unprivileged user namespaces, the app still starts, as the owner
  chose, and writes a WARNING line to `diagnostics.log`, since 0.12.1); the packaged app refuses debugging switches. The file protocol
  fuse stays on: with it off the app cannot read its page from its archive and
  shows a blank window (0.7.0). `desktop/test/policy.test.js`
  and `desktop/test/package.js` hold this: a change that weakens it fails them,
  and a change that strengthens it updates them in the same pull request.
  `check-package` must see the packaged window report `shell-ready`: running
  from the source does not prove the AppImage works.
- **Layout.** The sidebar is 15% of the window width, never under 176 px
  (since 0.11.8/0.11.10; it was 3 of 15 units), the pages take the rest, and
  the header is a thin fixed bar (44 px, since 0.11.7). The window opens inside
  the screen's work area (at most 1280 by 800, maximized on a smaller screen)
  and can shrink to 900 by 560. The pages are Node Controller, Node Talker, SysMon, Node Monitor, Node
  Recorder, WifiMon, 44helper, Install Monitor and Terminal Monitor, and Last
  Heard; Pi-Piper and Pibrary have a sidebar entry but open in the system web
  browser, never in the app. There are no title bar tabs: the sidebar lists
  every page of every node as a single page by default, hides a page whose
  tool is stopped (unless it is open), and keeps Install Monitor at the bottom,
  always shown and never hideable. Every page opens as a single page first. The sidebar has three slots, Left, Right and Lower, each a
  stacked list of pages (any page in any slot, one selected per slot); the
  slots decide what the page area shows: one slot is one page, Left and Right
  are 6 and 6, adding Lower puts a full-width third under them (equal rows).
  Never more than three panes (no quarters). Clicking a page in a slot selects
  it and shows all the slots with focus on it; a page in no slot shows alone.
  44helper, Install Monitor and Terminal Monitor are always single pages.
  Pages that are not on screen are idle (slowed and muted), except Node
  Talker, which is never idle; pages on screen never are. Last Heard opens as
  a new single page. A page in a small pane is scaled to fit it (the pane's
  size against 800 by 500, 50% to 100%), per pane, with its own size set by −,
  + and Ctrl+0 (device emulation, not page zoom, which Chromium shares across
  a host name).
- **Title and look.** The window, its page and its logo say "Node Controller
  Desktop" (see Naming above); node page names stay as the nodes serve them.
  The shell uses the shared Node Control look: the Readex Pro files in
  `desktop/ui/fonts/` (the same woff2 data the tools embed) and the shared
  variables in `desktop/ui/style.css`; `ci/check_repo.py` checks the shared
  lines. The data folder keeps the name `Node Controller`.
- **Run before pushing:** `npm test`, `xvfb-run -a npm run smoke` and, after
  `npm run dist`, `xvfb-run -a npm run check-package` in `desktop/`, plus
  `python3 ci/check_repo.py --base origin/main`. The `desktop` workflow builds
  and tests every change and, on `main`, publishes the AppImage as a
  pre-release `desktop-vX.Y.Z` (unsigned).
- **After a desktop build is merged, post its AppImage link** (check the
  release exists first):
  `https://github.com/kd8pgk/ASL-DVS/releases/download/desktop-vX.Y.Z/NodeController-X.Y.Z.AppImage`

## Null Browser (`nullbrowser/`)

- **Null Browser** is a separate private browser in `nullbrowser/`, an Electron
  app in JavaScript, unrelated to the nodes. Its promise is that it keeps
  nothing; changes must not weaken any of these:
  - The page session is in memory only (a non-persistent partition), and so is
    the toolbar's. Chromium's working folder, and `HOME`, `XDG_*` and `TMPDIR`,
    point into a RAM folder (`/dev/shm/null-browser-<uid>-<pid>-<random>`)
    that is removed on quit, by a detached shell command that waits for the
    browser to end (Chromium writes after the last JavaScript runs), and at the
    next start if a crash left it. The smoke test checks that nothing is left
    there, and that a browsing session adds or changes nothing in the real home
    folder. Run from source, a warm-up run first builds Chromium's own font
    index, which, like the GPU process, can start before the app's own code
    moves `HOME`; that is why GPU acceleration is off. The packaged AppImage
    does not need the warm-up: its launcher (below) sets the folders before
    Chromium starts at all.
  - No log file, crash reporter, telemetry, updater, history or saved setting.
  - No downloads. A PDF, audio or video file (by type, checked against its
    first bytes) is fetched into the RAM folder and handed to the system app
    only after the user answers **Open** (never before; a file that finishes
    first waits for the answer). Anything else is refused. Camera, microphone,
    location, notifications and every device are denied. Only http and https pages; subresources also ws, wss, data and
    blob.
  - https first (public http is upgraded; "Open anyway (not secure)" when a site
    has none). Certificate errors are refused; only hosts on a private network
    may be trusted, and only until it closes.
  - Third-party cookies are accepted and dropped: never stored, never sent.
    Script pop-ups are accepted and dropped (a hidden, muted window whose
    requests are all cancelled, closed after 3 s); a clicked new-tab link opens
    in the same page. **Allow for this site** (until it closes) lets that
    site's pop-ups open for real and keeps its third-party cookies, in memory,
    for sign-ins.
  - A site's own cookies and storage (local storage, IndexedDB, service
    workers, cache) do not outlive your visit to it either: navigating to a
    different site's address or a link to one clears the site being left,
    scoped to its own origin, the moment the new page starts loading. Staying
    on one site, redirects included, is unaffected. **Allow for this site**
    exempts it from this too, for as long as it stays allowed.
  - A watchdog (`src/watchdog.js`) clears a site the same way, with a notice
    naming it and why, when it crashes the page twice in a minute, sends two
    disguised files in two minutes, keeps opening pop-ups after the pop-up
    cap three times in thirty seconds, has its page contact fifteen
    different hosts in ten seconds, or pins the page's process above 60% of
    a CPU core for three five-second samples running while nothing is
    clicked or typed. It only clears and tells you; the page stays open. An
    allowed site is exempt, same as the leaving-a-site clear above.
  - JavaScript JIT off (`--jitless`) and GPU acceleration off (no graphics
    driver caches on disk). The user agent is plain Chromium; nothing else is
    disguised. It is private, not anonymous.
  - The packaged app refuses debugging and certificate switches.
- **Look.** The toolbar and its pages use the shared Node Control look: the
  Readex Pro files in `nullbrowser/ui/fonts/` (the same woff2 data the tools
  embed) and the shared variables in `nullbrowser/ui/style.css`, which
  `ci/check_repo.py` checks as it does the desktop app's.
- **Version** is `version` in `nullbrowser/package.json` (`X.Y.Z`); any change
  under `nullbrowser/` raises it and adds an entry at the top of
  `changelogs/nullbrowser.md` with its "Current version" line updated
  (`ci/check_repo.py` checks this). No comments in its `.js`, `.css` or `.html`
  files; no runtime libraries (only `electron`, `electron-builder` and
  `@electron/fuses` as dev dependencies).
- **Electron:** the newest supported release that passes the Debian check (44.x
  today, like the desktop app). It reaches any website, so every Electron
  security release means a rebuild.
- **Run before pushing:** `npm test`, `xvfb-run -a npm run smoke` and, after
  `npm run dist`, `xvfb-run -a npm run check-package` in `nullbrowser/`, plus
  `python3 ci/check_repo.py --base origin/main`. The `nullbrowser` workflow
  builds and tests every change and, on `main`, publishes the AppImage as a
  pre-release `nullbrowser-vX.Y.Z` (unsigned).
- **After a Null Browser build is merged, post its AppImage link** (check the
  release exists first):
  `https://github.com/kd8pgk/ASL-DVS/releases/download/nullbrowser-vX.Y.Z/NullBrowser-X.Y.Z.AppImage`
- **Bookmarks.** A star button opens a panel of bookmarks, with **Import…**
  for a bookmarks export (the `.html` file Chrome, Firefox, Edge and Safari
  write, in the Netscape bookmark format). Only `http://` and `https://`
  links are read in; everything else in the file is skipped. The imported
  list lives only in memory, capped at 500, and is gone once Null Browser
  closes; nothing is written to disk.
- **Faster JavaScript.** A toolbar button (**JIT: Off**/**JIT: On**) asks
  first, then restarts Null Browser as a whole new process with the JIT
  compiler on or off for that run only; nothing is written to disk to
  remember the choice, so the next start is `--jitless` again.
- **Packaged (0.5.0).** `npm run dist` builds a Linux AppImage
  (`electron-builder`, normal compression, the same fuses as the desktop app).
  `build/afterPack.js` renames the real binary to `nullbrowser-bin` and puts a
  shell launcher in its place (`nullbrowser`): the launcher picks a RAM
  folder, creates it with the same layout `ram.js` would, and sets `HOME`,
  `XDG_*` and `TMPDIR` to point into it **before** the real binary (and so
  Chromium) ever starts, closing the font-index gap a source run still has.
  `main.js` adopts that folder (`NULLBROWSER_PRELAUNCH_DIR`) instead of
  making its own. `check-package` (`test/package.js`) builds on the desktop
  app's packaged checks (fuses, the asar file list, refused debugging
  switches, no listening port) and adds its own: the real home folder stays
  empty from the very first start, with no warm-up needed, and the RAM
  folder the launcher made is removed on quit like any other. The icon is
  `nullbrowser/build/icon.png` (512 px) and `nullbrowser/ui/icon.png`
  (256 px). Not on the stable/testing channels, like the desktop app.
- **Naming: litterbug and rammaid.** A function whose job is to take
  something in and let nothing come back out of it (a pop-up window that
  fetches nothing and is destroyed, a request cancelled with no response) is
  named `litterbug*` (`litterbugSink`, `litterbugClose`,
  `litterbugRequest`, `litterbugIds`, `LITTERBUG_MS`, `MAX_LITTERBUGS`,
  `LITTERBUG_OPTIONS`). A function whose job is to remove files from the RAM
  folder is named `rammaid*` (`rammaidRemove`, `rammaidSweep`,
  `rammaidAfterExit`, `rammaidFile` for one downloaded file, and the
  top-level `rammaid()` that runs them at quit).
  Keep using these names for anything new of the same kind, in `nullbrowser/`
  only; nothing in `desktop/` is renamed.

## Attack lab (`attacklab/`)

- **A test server that attacks the two Null Browsers with harmless
  stand-ins**, never real malware: files with the wrong magic bytes (an `MZ`
  or ELF header, a shell script, HTML, the EICAR test string) dressed as PDFs,
  songs and videos, a polyglot PDF, a `../` file name, oversize and endless
  files, redirect loops, a self-signed https port, pop-up floods, permission
  grabs, dangerous link schemes, a ClickFix copy trick, a fake lock screen,
  alert loops, a memory bomb, a CPU busy loop and storage that tries to
  survive a restart. The server decides each verdict from what reaches it
  (`/results`); tests it cannot see from its side are marked by hand or by
  the runner.
- `node attacklab/server.js --port 8088 --host 0.0.0.0` serves it to a phone
  on the same network (Null Browser Mobile); `node attacklab/run-desktop.js`
  drives the desktop Null Browser from source with Playwright and prints the
  verdicts. Node built-ins only, no comments, like the apps. Not run in CI
  yet.

## Null Browser Mobile (`nullbrowser-android/`)

- **Null Browser Mobile** is a separate, scoped-down Android sibling of Null
  Browser, in its own top-level folder (not inside `android/`, which is Node
  Talker Mobile's), built on Android's `WebView` rather than embedding
  Chromium directly the way the desktop build does. It is a deliberately
  smaller promise, stated plainly rather than claimed as parity: it keeps
  what an app can control through WebView's own APIs, and drops what it
  can't, instead of reaching for an unsupported workaround.
  - One screen, one `WebView`: an address bar, back/forward/reload, a blank
    start page, no tabs, no history, no saved settings. Everything (cookies,
    storage, cache, the private downloads folder) is cleared when the app
    closes (`BrowserActivity.onDestroy`).
  - Third-party cookies dropped (`CookieManager.setAcceptThirdPartyCookies`).
    Every permission request (camera, microphone, location and the rest) is
    denied without asking.
  - https tried first; a certificate error is refused outright, with no
    trust-for-session yet. No downloads except a PDF, audio or video file,
    content-sniffed against its first bytes the same way the desktop build
    is, fetched into the app's private cache and handed to the user's own
    app only after they say Open. A script pop-up without a real tap on the
    page is refused outright, with a notice; a tapped link that would open a
    new window loads in the same page instead.
  - **What WebView does not give an app a supported way to control, and so
    is not attempted:** disabling the JIT compiler, passing Chromium
    command-line switches (closing the ones the desktop build closes, such
    as the DNS-over-HTTPS probe or the spell-check dictionary fetch), or
    reading a separately sandboxed renderer process's own CPU usage (the
    watchdog's CPU-while-idle signal). The desktop build's RAM-folder
    machinery (the packaged launcher, `rammaid*`) does not apply either:
    every Android app already gets its own OS-sandboxed private storage, so
    there is no shared `$HOME` for it to leak into in the first place.
  - **Planned, not dropped:** bookmark import, the per-site leave-and-clear
    storage behavior, pop-ups accepted-but-starved instead of refused
    outright, and the watchdog's other four signals (crash-loop, repeated
    disguised files, the pop-up cap kept being hit, request fan-out) all
    have a workable Android equivalent and are later versions, the same way
    they were later versions of the desktop build.
- **No libraries beyond the Kotlin standard library** (and JUnit for tests),
  like Node Talker Mobile; this is why file hand-off uses a small hand-written
  `ContentProvider` (`DownloadProvider.kt`) instead of AndroidX's
  `FileProvider`.
- **Version** is `appVersion` (`X.Y.Z`) in
  `nullbrowser-android/app/build.gradle.kts`; any change under
  `nullbrowser-android/` raises it and adds an entry at the top of
  `changelogs/nullbrowser_android.md` with its "Current version" line updated
  (`ci/check_repo.py` checks this, the same `check_android_app` helper Node
  Talker Mobile uses). No comments in its Kotlin or Gradle files, like Node
  Talker Mobile.
- **Package name** `io.github.kd8pgk.nullbrowser`; its own `debug.keystore`
  (not shared with Node Talker Mobile's), committed the same way, so test
  builds install over each other but never over Node Talker Mobile.
- The `nullbrowser-android` workflow builds, tests and lints every change
  and, on `main`, publishes the APK as a pre-release
  `nullbrowser-android-vX.Y.Z` (not on the stable/testing channels, like the
  other apps in this section).
- **After a build is merged, post its APK download link** (check the release
  exists first):
  `https://github.com/kd8pgk/ASL-DVS/releases/download/nullbrowser-android-vX.Y.Z/NullBrowserMobile-X.Y.Z.apk`

## Workflow

- After a build is pushed, open the pull request and merge it, without
  asking, once the `checks` workflow passes on it. A failing check is fixed
  in the same pull request.
- **Release channels.** `main` is the testing channel (opt-in on nodes).
  Stable is the default: `channels/stable.json`, written only by the
  `promote-stable` workflow from the rules in `channels/rules.json`. Per tool,
  a release becomes stable once four newer releases of that tool are on `main`
  and it has been there 3 days, or once it has been the newest release for 14
  days. Cosmetic builds don't count. `channels/overrides.json` (changed only
  through a pull request) can hold a release back or hotfix it to stable at
  once. Never edit `channels/stable.json` by hand.

## Before pushing

- `python3 ci/check_repo.py --base origin/main` runs the same checks as the
  `checks` workflow (needs `pyflakes`, `node` and `shellcheck`). It also
  fails on any comment or docstring in a script, and notes page functions that
  are never named and docs that still name a replaced file.
- `python3 -m py_compile` and `pyflakes` on changed Python files.
- `node --check` on page JavaScript after a page change. The page HTML is a
  raw string, so the source text is what is served.
- `bash -n` and `shellcheck -S error` on changed shell scripts.
- `python3 ci/test_ci.py` after any change to a tool or to `ci/`.
- Exercise the changed behaviour (unit test with mocks, or the page in
  headless Chromium) before opening a pull request.

## Testing and audit policy

- **What CI runs.** The `checks` workflow runs on every pull request, on every
  push to `main`, and weekly (the weekly run checks every script, not only
  changed ones), on Python 3.11 and 3.13. A pull request is merged only when
  both legs pass.
- **Every web tool is in the server tests.** Each tool that serves a page is
  listed in `ci/test_servers.py` (`SERVERS`), `ci/test_security.py`
  (`EXPECT`), and, for the pi02w and common tools, `ci/test_install.py`
  (`TOOLS`). A new tool is added to all three in the pull request that adds it.
  A route that answers without a login on purpose goes in `PUBLIC_BY_DESIGN`.
- **Run the suites that cover the change.**
  - Routes, login or server code: `sudo python3 ci/test_servers.py` (also
    with `ASL_TEST_VIA_LAUNCHER=1`, the way services start on a node) and
    `sudo python3 ci/test_security.py`.
  - Node Talker or Node Recorder audio: the three baseline suites and
    `ci/test_talker_stream.py`.
  - `--install` or `--uninstall` code: `ASL_TEST_INSTALL=1 python3
    ci/test_install.py`, as root, only on a disposable machine (it installs
    into the system folders).
  - The logged-in checks need `ASL_TEST_ROOT_PASSWORD`. CI sets it; never set
    a root password on a node or a shared machine for a test.
- **The security table is the contract.** `EXPECT` in `ci/test_security.py`
  records each tool's response headers and request guards. A change that
  weakens one fails CI. A change that strengthens one updates the table in the
  same pull request. A known gap is listed in `KNOWN_GAPS` until it is fixed,
  and fixing it removes the entry. None known today.
- **Error replies carry a message.** Every tool answers errors with a
  `message` key. wifimon (`error`) and 44helper (`output`) keep their old key
  beside it while nodes run mixed versions.
- **Promotion waits for green.** `promote-stable` promotes only when the
  `checks` workflow passed on the newest `main` commit (other than a
  `stable.json` update). Never edit `channels/stable.json` by hand.
- **Real node before Stable.** Before lifting a hold or adding a hotfix in
  `channels/overrides.json`, run the release on a Pi Zero 2 W: link and unlink
  each mode, a tunnel restart, a reboot, and read the boot report, the
  Node Talker health verdict and the Node Talker Balancer card (it starts by
  itself and reports each minute). Note the result in the pull
  request.
- **Unused code.** A page function that `check_repo.py` reports as never named
  is removed in that tool's next release (today: `_ovLevelLabel` and
  `qmEsc` in 44helper).
- **Docs follow the code.** When `check_repo.py` notes that a summary in
  `docs/src/` names a replaced file, recheck that summary against the new
  code (constants, routes, counts) before it is rebuilt, and update its source
  line.
- **Not covered by CI.** Real hardware (Asterisk, DVSwitch, WireGuard, the
  radio path) and the disk-image jobs. They are checked on a node (above), and
  a disk-image change is also tested by hand on spare drives.
