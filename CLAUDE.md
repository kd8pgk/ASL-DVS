# CLAUDE.md

## Scope: Pi Zero 2 W fork first

- Current work is on the **Pi Zero 2 W (pi02w) fork**.
- **Never change the full build** (`sysmon_v*.py`, `asl_dvs_dashboard_v*.py`
  without `_pi02w_`) unless the request explicitly names the full build. A
  change made to a pi02w file is not to be copied to the full build on its own.
- The common tools (instmon, wifimon, 44helper, the installer, the watchdog,
  the uninstaller) serve both builds. When a pi02w change needs one of them,
  say so before changing it.

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
  `-pi02w` (for example `9.3.71.3-pi02w`).
- **The shared launcher** (`/usr/local/bin/asl_dvs_launch.py`) is written by
  several files. Its text must stay identical in all of them.
- **Install manuals** in `docs/` name the current files and versions. Update
  the matching manual when a file it lists changes.

## Before pushing

- `python3 -m py_compile` and `pyflakes` on changed Python files.
- `node --check` on page JavaScript after a page change. The page HTML is a
  raw string, so the source text is what is served.
- `bash -n` on changed shell scripts.
- Exercise the changed behaviour (unit test with mocks, or the page in
  headless Chromium) before opening a pull request.
