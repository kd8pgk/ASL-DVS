# CLAUDE.md

## Scope: Pi Zero 2 W fork first

- Current work is on the **Pi Zero 2 W (pi02w) fork**.
- **Never change the full build** (`sysmon_v*.py`, `asl_dvs_dashboard_v*.py`
  without `_pi02w_`) unless the request explicitly names the full build. A
  change made to a pi02w file is not to be copied to the full build on its own.
- The common tools (instmon, wifimon, 44helper, the installer, the watchdog,
  the uninstaller) serve both builds. When a pi02w change needs one of them,
  say so before changing it.

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
- **Tools stay compatible across versions.** Each tool goes to stable on its
  own schedule, so a node can run any mix of stable and testing versions. A
  tool that uses something only a newer version of another tool provides
  works without it when it is missing.
- **Shared code** lives in `shared/confio.py`. Each function named in its
  `USED_BY` is copied unchanged into every tool listed there (a tool's own
  wrapper may call it); `ci/check_repo.py` fails a tool whose copy differs.
  Change the reference first, then copy it into every listed tool.
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
  release build (not debuggable, no `-debug` in the name). From 0.10.27 the
  published APK is signed with a private release key kept in the repository
  secrets `NODETALKER_KEYSTORE_BASE64`, `NODETALKER_KEYSTORE_PASSWORD`,
  `NODETALKER_KEY_ALIAS` and `NODETALKER_KEY_PASSWORD`. Until those secrets
  are set (a stopgap from 2026-11-11), the workflow publishes the APK signed
  with the shared key in `android/app/debug.keystore`, and the release title
  and notes say "shared key". That key is public: once the secrets are set
  the workflow uses the private key by itself, and each phone needs one
  uninstall. Pull-request builds and a local build always use the shared
  key. Never commit the release key.
- The app is not on the stable/testing channels: those update node tools.
- **After an Android build is merged, always post its APK download link**:
  `https://github.com/kd8pgk/ASL-DVS/releases/download/android-vX.Y.Z/NodeTalker-X.Y.Z.apk`
  (check the release exists first).

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
  and fixing it removes the entry. Known today: instmon and Pibrary accept a
  login request without `X-Requested-With`.
- **Error replies carry a message.** New tools answer errors with a
  `message` key. instmon and wifimon (`error`) and 44helper (`output`) are
  recorded in the server tests as they are; move them to `message` in their
  next release and update `error_keys`.
- **Promotion waits for green.** `promote-stable` promotes only when the
  `checks` workflow passed on the newest `main` commit (other than a
  `stable.json` update). Never edit `channels/stable.json` by hand.
- **Real node before Stable.** Before lifting a hold or adding a hotfix in
  `channels/overrides.json`, run the release on a Pi Zero 2 W: link and unlink
  each mode, a Node Talker tone test, a tunnel restart, a reboot, and read the
  boot report and the Node Talker health verdict. Note the result in the pull
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
