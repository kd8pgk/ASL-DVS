# Watchdog (asl_dvs_watchdog) changelog

Current file: `asl_dvs_watchdog_v2_4_20261006.sh`. Newest entries first.

## 2.4 (2026-10-06)

- No code change from 2.3. Repo copy is comment-stripped. The change history that was in the file's comments now lives in this changelog. The title line stays (instmon can read the version from it; `SCRIPT_VERSION` is also set).


## Earlier history

Carried over unchanged from the comments of the files below.

### asl_dvs_watchdog_v2_4_20261006.sh (header comments, as of 2.3)

```text
asl_dvs_watchdog.sh  v2.4  (2026-10-06)
External liveness watchdog for asl_dvs_dashboard.service (and, as of
v2.2, any other Library-Card dashboard instance)
KD8PGK / Claude AI (Anthropic)  —  CC BY-NC 4.0

v2.3: the check now asks /api/ping and counts any HTTP answer below 500
as alive.  Dashboard v9.x requires a login for /api/status, so v2.2's
unauthenticated `curl -f .../api/status` got 401 on every run, failed
twice and restarted the dashboard every ~50 s -- the dashboard kept
dropping out, sysmon's quick link went grey, and the restarts loaded the
Pi enough to upset sysmon and instmon as well.  /api/ping is public and
cheap.  A dashboard that answers at all (even 401 or 404, e.g. an older
build without /api/ping) is up; only no answer, a timeout or a 5xx is a
failure, as before retried once before the restart.

v2.2: asl_dvs_dashboard v8.0 merged the M17 tab (USRP2M17 bridge) from
the asl_dvs_m17_dashboard feature branch into the mainline dashboard —
but ZELLO was deliberately left behind on that branch, not ported. That
means the branch didn't go away: it's still a second, independently
running dashboard process (its own port, its own systemd unit) carrying
Zello support the mainline doesn't have. Before v8.0 there was only ever
one dashboard instance to watch, so this script never needed to name
more than one set of units. Now there are two live instances again, so
this script gained instance naming:
  ASL_DVS_WATCHDOG_INSTANCE   suffixes every installed filename/unit
                                (default: unset — unsuffixed, 100%
                                backward compatible with existing
                                single-instance installs)
This lets --install be run twice on the same box, once per dashboard
instance, without either install stepping on the other's binary, unit
files, or timer. See the Usage block below for both invocations.
The change is naming-only — the actual check logic (curl /api/status,
retry once, restart on second failure) is identical for every instance;
it doesn't know or care that one instance also happens to serve M17/Zello.

v2.1: Bundled sysmon's Stage 5 regression suite (test_sysmon.py) into
this file verbatim, exposed via a new `--test` flag, per explicit
request to merge it into the watchdog. IMPORTANT — this is a direct
merge as asked for, not an endorsement that it belongs here: the
embedded suite exercises sysmon.py internals (load_config/save_config
round-trip, the radio-restart lock, check_port_duplicates,
get_services_details) and has no coverage of anything in THIS script
(check/run_check/do_install/do_uninstall/do_status). Running --test
tells you whether a sysmon build is healthy; it tells you nothing
about whether the watchdog itself is healthy. It's bundled here
purely for single-file delivery convenience, not because the watchdog
depends on or is validated by it. See do_test() below for the actual
extraction/execution mechanics.

v2.0 REWORK NOTES:
Previously this logic was split across three files (asl_dvs_watchdog.sh,
asl_dvs_watchdog.service, asl_dvs_watchdog.timer) that had to be copied
into place and wired up by hand. As of v2.0 it's a single self-installing
file: the unit files are generated in-place by --install, and the check
logic that used to be the entire script is now just the default
(no-argument) code path. This matches the "Library Card" self-install
convention used elsewhere in the suite (instmon components, wifimon,
44helper): a component script can install/uninstall itself, and
install_asl_dvs just shells out to `bash <this file> --install` rather
than reimplementing unit-writing logic for every component.

Why a single file instead of the old three: fewer things to go stale
against each other (unit content and check logic used to live in
different files with no version linkage), fewer files to stage/deliver/
track versions for, and it gets the same self-install treatment as
every other Library Card component instead of being the one thing that
still needed manual `cp` + `systemctl enable` steps.

Reliability hardening item 4 of 6 (see asl_dvs_dashboard_reliability_plan.docx).
Runs on a timer (asl_dvs_watchdog.timer), OUTSIDE the dashboard process
itself -- an independent second line of defense against hangs that the
in-process sd_notify heartbeat (asl_dvs_dashboard.py v7.781, WatchdogSec=30)
might miss. Those two mechanisms don't overlap perfectly: the in-process
heartbeat only proves _link_poll_loop is still ticking -- it says nothing
about whether the HTTP thread pool itself is wedged. This script proves
the HTTP side is actually answering requests, from outside the process,
which the in-process heartbeat structurally cannot do.

NOTE ON THE "STFU-visibility-class" enable/restart bug: several other
self-installers in this suite (dashboard, sysmon, wifimon, 44helper) had
a bug where re-running --install on an already-active persistent daemon
was a no-op -- `systemctl enable --now` doesn't restart an already-active
unit, so the OLD code stayed resident in memory even after a fresh binary
was copied into place. That bug class doesn't apply here in the same way:
this "service" is Type=oneshot, invoked fresh by the timer every
OnUnitActiveSec, so there is no long-lived watchdog process that can go
stale -- every firing re-execs whatever binary currently sits at
${BIN_PATH}. --install still runs one verification check immediately
after writing the units, just to prove the new wiring actually works
rather than relying on the next scheduled firing to find out.

Usage:
  sudo bash asl_dvs_watchdog.sh --install     install + enable + start (idempotent)
  sudo bash asl_dvs_watchdog.sh --uninstall   stop + disable + remove everything
  sudo bash asl_dvs_watchdog.sh --status      show timer/service state + recent log
  sudo bash asl_dvs_watchdog.sh               run ONE check (this is what the
                                                installed .service unit executes)

Mainline dashboard instance (unchanged from earlier versions):
  sudo bash asl_dvs_watchdog.sh --install

M17/Zello branch instance, installed alongside it on the same box —
substitute that instance's real port/unit/instance name:
  sudo ASL_DVS_WATCHDOG_INSTANCE=m17zello \
       ASL_DVS_WATCHDOG_PORT=8990 \
       ASL_DVS_WATCHDOG_TARGET=asl_dvs_m17_dashboard.service \
       bash asl_dvs_watchdog.sh --install
(--uninstall / --status / the no-arg check also take ASL_DVS_WATCHDOG_INSTANCE
to target that same instance; omit it to operate on the mainline instance.)

Installed layout (all written by --install; INSTANCE below is the value of
ASL_DVS_WATCHDOG_INSTANCE, or nothing at all -- and no "-" separator -- when
that var is unset, which reproduces the exact pre-v2.2 unsuffixed filenames):
  /usr/local/bin/asl_dvs_watchdog[-INSTANCE].sh              this script
  /etc/systemd/system/asl_dvs_watchdog[-INSTANCE].service    oneshot check
  /etc/systemd/system/asl_dvs_watchdog[-INSTANCE].timer      OnBootSec=60 OnUnitActiveSec=45

Env overrides (apply to BOTH the check path and unit generation in --install,
so they stay in sync automatically -- no more hand-editing the .service file
separately from the script like the old three-file layout required):
  ASL_DVS_WATCHDOG_PORT      dashboard /api/ping port  (default 8989)
  ASL_DVS_WATCHDOG_TARGET    systemd unit to restart on failure (default
                              asl_dvs_dashboard.service)
  ASL_DVS_WATCHDOG_INSTANCE  suffixes the installed filenames/units so
                              multiple dashboard instances can each have
                              their own independent watchdog (default:
                              unset -- unsuffixed, matches every install
                              from before v2.2). Letters, digits, "_" and
                              "-" only; anything else is rejected before
                              it ever touches a path.
```
