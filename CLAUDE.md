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
- **Every change gets a new version.** Rename the file
  (`<tool>_vX_Y_Z_YYYYMMDD.py`), update `VERSION` / `APP_VERSION` /
  `SCRIPT_VERSION`, and update the README file list. A pi02w version ends in
  `-pi02w`.
- **Versions have three parts**, `X.Y.Z` (for example `5.31.0`,
  `9.3.72-pi02w`). No four-part numbers in new builds. A tool still on four
  parts moves to the next three-part number above it (`9.3.71.18-pi02w` ->
  `9.3.72-pi02w`), so instmon still sorts the new file as newer. A tool on two
  parts adds `.0` (`5.30` -> `5.31.0`). No letter suffix (such as `x`).
- **The shared launcher** (`/usr/local/bin/asl_dvs_launch.py`) is written by
  several files. Its text must stay identical in all of them.
- **Manuals** (the user manual, the dialplan guide and the install manuals in
  `docs/`) are updated only when the request says so. A code change alone does
  not update them.

## Workflow

- After a build is pushed, open the pull request and merge it without asking.

## Before pushing

- `python3 -m py_compile` and `pyflakes` on changed Python files.
- `node --check` on page JavaScript after a page change. The page HTML is a
  raw string, so the source text is what is served.
- `bash -n` on changed shell scripts.
- Exercise the changed behaviour (unit test with mocks, or the page in
  headless Chromium) before opening a pull request.
