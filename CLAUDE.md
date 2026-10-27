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
- **Kotlin and Gradle files carry no comments**, like the scripts.
- **No libraries** beyond the Kotlin standard library unless a phase needs
  one.
- **Package name** `io.github.kd8pgk.nodetalker` never changes (the Play
  Store ties the app to it).
- The `android` workflow builds and lints every change; on `main` it
  publishes the APK as a pre-release `android-vX.Y.Z`. From 0.3.2 it is a
  release build (not debuggable, no `-debug` in the name) signed with the
  shared key in `android/app/debug.keystore`; a private release key waits
  until the keystore secrets exist.
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
  `checks` workflow (needs `pyflakes` and `node`).
- `python3 -m py_compile` and `pyflakes` on changed Python files.
- `node --check` on page JavaScript after a page change. The page HTML is a
  raw string, so the source text is what is served.
- `bash -n` on changed shell scripts.
- Exercise the changed behaviour (unit test with mocks, or the page in
  headless Chromium) before opening a pull request.
