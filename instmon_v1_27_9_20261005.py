#!/usr/bin/env python3

"""instmon v1.27.9 (2026-10-05) - KD8PGK Web Installer & Component Manager

v1.27.9 - Quiet System, Check for updates and Full Update.
  Quiet System / Restore (Upload card): stops whichever of the watchdog
timer, SysMon, Dashboard, M17 Dashboard, SVX Dashboard and 44helper are
running, so a small Pi (Zero 2 W) has memory for uploads and installs.
The list is fixed in QUIET_SERVICES -- radio, Asterisk, Allmon3, SSH,
wifimon, Cockpit and instmon are never touched.  Restore starts only what
Quiet stopped, in reverse order (watchdog timer last); a component that a
later Install/Uninstall already restarted or removed is dropped from the
list.  State is kept in /var/lib/instmon/quiet.json, so it survives an
instmon restart; auto-restore after 30 min (INSTMON_QUIET_AUTO_RESTORE_SEC),
also applied at startup if the saved quiet is older than that.  A banner
shows while quiet; quieted component cards read QUIET.
  Check for updates / Full Update (new Updates card): reads the public
repo kd8pgk/ASL-DVS (branch main) through the GitHub API -- source fixed
in code, HTTPS only, redirects only to the same GitHub hosts, 8 MB cap per
file, and each download must match GitHub's blob hash.  For each
installed component the newest repo build of the same variant is picked
by the version and date in its file name (a Pi02w sysmon stays on Pi02w
builds; plain and M17 dashboards are separate).  Installed versions come
from the VERSION line, or for files without one (wifimon, 44helper) from
a library or repo file with identical content; unknown versions are
listed, never auto-updated.  Not-installed components are left alone,
config files are never downloaded, the retired watchdog never offered.
  Full Update runs in the background: check, download and verify
everything (syntax check, --install/--uninstall present) before changing
anything, Quiet, then one component at a time in the order 44helper,
wifimon, SVX, Dashboard, M17 Dashboard, SysMon: save a library copy of
the installed file, run its --uninstall, run the new file's --install,
wait for the service (and its port) to come up.  A failure reinstalls
the saved copy and the component is skipped; if that fails too it is
listed as NEEDS ATTENTION.  The run carries on either way and ends with
Restore and a summary (log, toast, banner until dismissed).  New install
scripts go into the library's Scripts section and are never run.
instmon goes last, after Restore: replaced in place by its own --install
(an --uninstall would stop this process first), with a transient
instmon-update-guard timer that reinstalls the saved copy if port 8990
doesn't answer 90 s later.  Results are saved to
/var/lib/instmon/update.json first and the restarted instmon reports
them.  While Full Update runs, every action except Journal, plus Upload
and the editor's Save, answers 409.
  Checks run: pyflakes, node --check on the page script, 44 simulated
cases (fake GitHub serving this repo's files, stubbed systemd: normal
run, order, rollback, rollback failure, bad hash, syntax error, offline,
nothing to do, Pi02w variant, instmon restart hand-off, Quiet
persistence and auto-restore), a read-only check against the live repo,
and the page driven in Chromium.

v1.27.8 - Watchdog (asl_dvs_watchdog.sh) retired as a component.  The
dashboard's own systemd unit already has Restart=always + WatchdogSec=30,
and watchdog v2.2 restarted a healthy v9.x dashboard every ~50 s (its
/api/status check got the new login 401).  Removed the "watchdog"
category everywhere: LIB_SUBDIRS, ALLOWED_EXT, COMPONENTS (no more
Watchdog status card), HOME_SCAN_PATTERN_MAP, _LIBRARY_GROUPS and the
Upload <select>.  New RETIRED_FILE_GLOBS: a file named
asl_dvs_watchdog*.sh is now skipped by the home-dir scan and refused by
Upload (even forced) -- without it the "scripts" row's asl_dvs*.sh
pattern would have filed it under Scripts, where Run Script would run
it.  An already-installed watchdog is removed by install_asl_dvs v6.4
(Run Script), or by hand: sudo bash /usr/local/bin/asl_dvs_watchdog.sh
--uninstall.  The old library/watchdog dir is left on disk, untracked.
  Upload fix: parse_multipart() stripped every trailing CR/LF off each
part, so an uploaded file lost its own final newline(s) and the staged
copy no longer matched the original byte-for-byte (different sha256, so
"installed" / up-to-date checks could disagree with the file you sent).
It now removes only the multipart framing.

v1.27.7 - Added M17 Dashboard (asl_dvs_m17_dashboard.py) as its own tracked
component, sibling to Dashboard rather than sharing its single COMPONENTS
entry. It was previously only half-supported: HOME_SCAN_PATTERN_MAP already
recognized asl_dvs_m17_dashboard*.py and filed it under the "dashboard"
category so it would appear in the library, but COMPONENTS has exactly one
dashboard entry (service asl_dvs_dashboard, install_link
/usr/local/bin/asl_dvs_dashboard.py) and several call sites do
next(c for c in COMPONENTS if c["category"]==cat) expecting a single
match -- so on a node running the M17 variant instead of the plain one:
build_status() checked the wrong systemd service/port and reported the
Dashboard card as down even when M17 Dashboard was actually running;
run_self_uninstall_bg() would run --uninstall against the wrong
install_link entirely; and _action_install_config()'s post-write restart
target was hardcoded to the "dashboard" category, so writing a new
asl_dvs.conf on an M17-only node would try to restart a service that was
never installed instead of the one actually consuming that config.
  Fixed by giving M17 Dashboard a real, independent COMPONENTS entry
(same pattern as the SVX Dashboard addition in v1.27.3-v1.27.5): new
"m17_dashboard" entries in LIB_SUBDIRS (own library subdir, split out
of the shared "dashboard" one), ALLOWED_EXT, COMPONENTS (service
asl_dvs_m17_dashboard, port 8989 -- same port as Dashboard since the two
are mutually-exclusive alternate builds for the same node role, not
concurrent services), _LIBRARY_GROUPS, and the Upload form's category
<select>. HOME_SCAN_PATTERN_MAP's "dashboard" row now matches only
asl_dvs_dashboard*.py; a new "m17_dashboard" row matches
asl_dvs_m17_dashboard*.py. _action_install_config() now picks whichever
of dashboard / m17_dashboard is actually installed on the node (checked
in that order) as the restart target instead of assuming "dashboard";
its JS confirm() text was also updated to stop naming "the Dashboard
service" specifically. Verified against a fixture with only
asl_dvs_m17_dashboard.py installed (no plain Dashboard): build_status()
now correctly reports M17 Dashboard as the active/listening component,
Uninstall runs against the correct install_link, and a config install
restarts asl_dvs_m17_dashboard rather than the untracked/absent
asl_dvs_dashboard. Also verified the existing plain-Dashboard-only and
both-installed cases still resolve correctly, and that svx/other
categories are unaffected (byte-diffed their COMPONENTS/library entries
against v1.27.6).

v1.27.6 - Bug: handle_upload() only ever validated category membership and
file extension, never the filename itself -- so any .py file uploaded
against any .py-accepting category (dashboard/sysmon/wifimon/44helper/svx/
instmon) was silently accepted and staged into that category's library
dir. Reported case: a SVX Dashboard file got uploaded into the 44helper
card. Fixed by reusing HOME_SCAN_PATTERN_MAP (already trusted for the
automatic home-dir sweep) to validate the uploaded filename against that
category's expected glob(s) at upload time. On a mismatch the backend
returns {"mismatch": true, "expected": [...]} instead of a plain error;
the frontend catches that and offers a confirm()-gated retry with
force=1 for the rare legitimate case (e.g. a renamed dev build) --
forced uploads are logged as a warning event so they're visible in the
log tab afterward, not silent. Verified against 6 scenarios including the
exact reported bug, its forced-override path, correctly-named files for
every newly-covered category, a second cross-category mismatch, and the
loose multi-pattern config category to confirm it wasn't over-restricted.

v1.27.5 - _LIBRARY_GROUPS (the Version Library section's card list) was
the one remaining hardcoded svx-shaped gap after v1.27.3/v1.27.4 -- like
the Upload dropdown, it's a hand-maintained list rather than derived from
LIB_SUBDIRS, so SVX had no library card even though scan_library() was
already finding its files correctly. Added ("SVX Dashboard","svx",
"install") alongside the other self-installing components. Verified
end-to-end against a fixture containing the real svx_dashboard_v0_0_0.py:
render_library_html() produces a card with the correct version (0.0.0,
read from the file's own VERSION constant), filename, and an Install
button wired to data-category="svx".

v1.27.4 - v1.27.3 added "svx" to LIB_SUBDIRS/ALLOWED_EXT/COMPONENTS/
HOME_SCAN_PATTERN_MAP, all of which handle_upload() already consumes
generically -- but missed that the Upload form's category <select> is a
hardcoded HTML list, not generated from LIB_SUBDIRS, so SVX had no way to
be selected for a manual upload even though the backend would have
accepted it. Added the missing <option value="svx">. Confirmed no other
hardcoded category list exists in the file (only one <select> total).
Verified end-to-end against a fixture: category/extension validation,
safe_join() path resolution into the svx subdir, and the actual
compare_before_write() all succeed for a staged svx_dashboard*.py file.

v1.27.3 - Added SVX Dashboard (svx_dashboard.py) as a seventh installable
component: new "svx" entries in LIB_SUBDIRS, ALLOWED_EXT, COMPONENTS
(port 8991), and HOME_SCAN_PATTERN_MAP (svx_dashboard*.py). No other code
changes -- build_status(), render_components_html(), and the home-dir
sweep are all already generic over these tables (per the v1.27.2 Stage C/D
refactor below), so this was purely additive. Verified against a live
fixture: scan_library() found the staged file and read its version
correctly, build_status() returned all 7 components with SVX Dashboard at
the expected port, render_components_html() rendered its card.

v1.27.2 - Internal refactor only. No UI, endpoint, or behavior changes --
every stage below was verified byte-identical (render_page() output) or
exercised against a stubbed equivalence harness (route/action dispatch)
comparing this file's output to v1.27.1's, request for request, before
being accepted. Same refactor discipline as asl_dvs_m17_44helper v0.0.23.

  Stage A - the inline <style> block inside HTML_TEMPLATE (previously
    escaped with doubled {{ }} braces throughout, to survive
    HTML_TEMPLATE's str.format() call) is now _CSS, assembled from 6
    named sub-constants (_CSS_BASE, _CSS_LAYOUT, _CSS_COMPONENTS,
    _CSS_LIBRARY, _CSS_LOG, _CSS_EDITOR). HTML_TEMPLATE now has a plain
    {css} placeholder in its place -- no more hand-maintained brace
    doubling to keep in sync every time the CSS is edited. Verified:
    render_page() output byte-identical to v1.27.1 with build_status()/
    render_components_html()/render_library_html() stubbed to isolate
    the template change from filesystem-dependent status data.

  Stage B - same treatment for the inline <script> block: now _JS,
    assembled from 5 named sub-constants (_JS_LOG_POLL, _JS_STATUS_TOAST,
    _JS_EDITOR, _JS_ACTIONS, _JS_INIT), substituted via a plain {script}
    placeholder. Verified render_page() output byte-identical to v1.27.1
    the same way as Stage A.

  Stage C - render_library_html() used to be 8 hardcoded, near-identical
    calls to render_library_group_html() -- one per library-dict key,
    copy-pasted whenever a new category was added. Replaced with a
    _LIBRARY_GROUPS table of (title, category, action_label) tuples,
    iterated in the same order as the original calls. Looked at unifying
    render_components_html() and render_library_group_html() into one
    shared card-rendering helper too, but the two build structurally
    different markup (single-row component card vs. a card containing
    multiple nested librow sub-rows) -- forcing them together would add
    indirection without removing real duplication, so they stay separate.
    Verified: render_library_html() output byte-identical to v1.27.1
    against a realistic 8-category library dict, and end-to-end through
    render_page().

  Stage D - three elif chains replaced with dispatch tables:
      - handle_action()'s 11-way action chain -> _ACTION_HANDLERS.
        save_alternate's no-body method signature (it never took a body
        argument) is absorbed into its own lambda rather than special-
        cased inside handle_action() itself.
      - do_GET's path chain -> _GET_ROUTES. The three routes that used
        to have their logic written inline (/api/status, /api/log,
        /api/file) are now small named _route_status()/_route_log()/
        _route_file() methods -- same code, just given names and pulled
        out of the branching.
      - do_POST's 3-way path chain -> _POST_ROUTES (already-named
        methods, trivial conversion).
    Verified: 28 cases (10 GET routes including query-param handling and
    the 404 fallback, all 11 actions plus unknown-action and no-action
    edge cases, and malformed JSON on /api/action and /api/file) all
    matched v1.27.1 exactly via a stubbed test harness that swapped every
    filesystem/subprocess-dependent method for a call-recording stub and
    diffed the resulting (status, content_type, body) tuples.

v1.27.1 - Comms SERV Restart correction, per confirmed sysmon service
table: added Allmon3 (allmon3.service) as a fifth service in the group,
and changed the bounce mechanism from a single `systemctl restart` per
service to a coordinated full stop-all -> COMMS_RESTART_PAUSE_SEC (3s)
pause -> start-all across the whole group. A plain restart can start the
new process before the old one has released its RTP/USRP sockets, and
these five all talk to Asterisk's AMI, so restarting one at a time while
the others are still up/down produces avoidable connection errors between
them -- stopping everything together, pausing, then bringing it all back
up together is the more reliable bounce for this stack.

v1.27.0 - New "System &amp; Comms" card (bottom of the dashboard, below
Backup &amp; Export): three new POST /api/action actions, none tied to
COMPONENTS/LIB_SUBDIRS like everything else in this file --
  - "comms_restart" / Comms SERV Restart button: restarts Asterisk,
    Analog_Bridge, MMDVM_Bridge, and STFU in sequence against a fixed
    server-side whitelist (COMMS_RESTART_SERVICES) -- these four are
    owned/managed by the Dashboard, not instmon; this is just a quick
    "bounce the whole comms stack" button for a wedged node. Returns a
    per-service ok/fail summary (HTTP 207 if any failed) rather than an
    all-or-nothing result.
  - "reboot" / Reboot Pi and "shutdown" / Shutdown Pi buttons: `systemctl
    reboot` / `systemctl poweroff`, gated behind a fixed server-side
    action (not a client-supplied command) and DOUBLE confirm() dialogs
    client-side given the blast radius (whole node, not just instmon).
    Both use the same systemd-run --on-active=2 --collect detached-unit
    pattern as install_service()'s v1.26.1 self-restart fix, for the
    same reason: fire the actual reboot/poweroff from a transient unit
    outside instmon's own process/cgroup, delayed ~2s, so the HTTP
    response and log line make it out before the node starts going down
    instead of the request just hanging.

v1.26.1 - BUGFIX: self-install would silently die mid-run. Reported as
"instmon --install fails silently" on a Pi 4B. Root cause: install_service()
ended with a synchronous `systemctl restart instmon.service`. Whenever the
--install run was itself a child of the already-running instmon.service
(any self-install: the web UI's own "Install" button on the instmon
library row, or re-running --install by hand while the old service was
still active), that restart tore down the WHOLE cgroup -- including this
very process -- the instant the restart began. The copy/unit-file/enable
steps had already completed, so nothing was left half-installed, but the
process got killed before it could print completion or let the HTTP
response reach the browser. Fixed by handing the restart to a detached,
2-second-delayed transient unit via `systemd-run --on-active=2 --collect`,
which lives outside instmon.service's cgroup and survives the very
restart it triggers, giving this process time to finish printing/logging
first. See the comment right above the systemd-run call in
install_service() for the full explanation.

v1.26.0 - Two changes, plus a deferred item:
  - Library card row layout: action buttons (Install/Run, Edit, Download,
    Delete) now sit on their own row below the name/version/status badge
    instead of being crammed onto the same line -- cleaner on narrower
    viewports. New .librow-actions CSS class; .librow-top now holds only
    ver/name/badge. Components card layout is unchanged (already fine).
  - Startup home-dir sweep: run() now calls the new
    scan_home_for_new_code() once at startup, which looks at the top
    level of HOME_SCAN_DIR (defaults to the running user's home dir, i.e.
    os.path.expanduser("~"); override with INSTMON_HOME_SCAN_DIR) for
    files matching the suite's known naming patterns
    (HOME_SCAN_PATTERN_MAP) and moves any that aren't already staged
    into the matching library subdir -- same category set the Upload
    dropdown offers (dashboard/sysmon/wifimon/44helper/instmon/
    scripts/config). Never overwrites a same-named library file with
    different content (disambiguates with a __homescan_<epoch> suffix
    instead); identical content is left alone silently. Disable with
    INSTMON_HOME_SCAN_ENABLED=0 if this isn't wanted on a given node.

  TODO (deferred to next bump, per explicit request): trim this module
  docstring itself down to a short title/version/license line for the
  stripped delivery copy, moving the changelog prose into a regular
  in-code comment block that only survives in the _ref copy. Left as
  the current single-docstring "config header" shape for this release.

v1.25.0 - Added asl_dvs_watchdog.sh as a tracked, installable component
(new "watchdog" category/library subdir/COMPONENTS entry), alongside
Dashboard/SysMon/wifimon/44helper/instmon. Since watchdog is the suite's
first *bash* self-installer (every prior COMPONENTS entry is a .py using
argparse's --install / a def install_service()), three previously
Python-only assumptions had to be generalized rather than just adding a
table row:
  - _scan_file_header_uncached()'s self-install/self-uninstall/version
    detection only matched Python patterns (add_argument("--install") +
    def install_service(), etc). Added a bash-pattern branch (--install)/
    do_install, --uninstall)/do_uninstall, SCRIPT_VERSION="x.y") that is
    tried whenever the Python patterns don't match, instead of assuming
    every library file is a .py.
  - run_self_install_bg() / run_self_uninstall_bg() had "python3" hardcoded
    as the interpreter. A watchdog install/uninstall would have silently
    tried to run a bash script with the Python interpreter and failed.
    Both now pick bash vs python3 off the file extension.
  - _action_install() unconditionally ran check_python_syntax() (py_compile)
    on every staged file before allowing install -- would have hard-blocked
    every watchdog install with a bogus "syntax error" since a .sh file
    is not valid Python. Added check_bash_syntax() (bash -n) and dispatch
    on extension so each script type is checked with its own syntax check.
"""

import argparse 
import base64 
import fnmatch 
import hashlib 
import hmac 
import html 
import http .server 
import json 
import os 
import py_compile 
import re 
import shutil 
import socket 
import subprocess 
import sys 
import threading 
import time 
import urllib .parse 
import urllib .request 
import urllib .error 
import shlex 
import tempfile 
import zipfile 
from collections import deque 
from datetime import datetime 


PORT =8990 
VERSION ="1.27.9"
DATE_STR ="2026-10-05"


INSTALLER_SCRIPT_GLOB ="install_asl_dvs*.sh"






INTERACTIVE_ONLY_SCRIPT_GLOBS =("wifi_menu*.sh","wifi-menu*.sh")


SCRIPT_TIMEOUT_SEC =int (os .environ .get ("INSTMON_SCRIPT_TIMEOUT_SEC","600"))


INSTALL_BIN_PATH ="/usr/local/bin/instmon.py"
SYSTEMD_SERVICE_PATH ="/etc/systemd/system/instmon.service"

SYSTEMD_SERVICE_CONTENT ="""[Unit]
Description=instmon Web Installer & Component Manager
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/bin/instmon.py
Restart=always
RestartSec=3s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""


LIBRARY_DIR =os .environ .get ("INSTMON_LIBRARY_DIR","/etc/asl_dvs/instmon_library")
CONFIG_DIR =os .environ .get ("INSTMON_CONFIG_DIR","/etc/asl_dvs")
CONFIG_NAME =os .environ .get ("INSTMON_CONFIG_NAME","asl_dvs.conf")
# v1.27.9: Quiet System and Full Update state (survives an instmon restart).
STATE_DIR =os .environ .get ("INSTMON_STATE_DIR","/var/lib/instmon")






HOME_SCAN_DIR =os .environ .get ("INSTMON_HOME_SCAN_DIR",os .path .expanduser ("~"))
HOME_SCAN_ENABLED =os .environ .get ("INSTMON_HOME_SCAN_ENABLED","1")!="0"


AUTH_USER =os .environ .get ("INSTMON_AUTH_USER","")
AUTH_PASS =os .environ .get ("INSTMON_AUTH_PASS","")
AUTH_ENABLED =bool (AUTH_USER and AUTH_PASS )


LIB_SUBDIRS ={
"dashboard":os .path .join (LIBRARY_DIR ,"dashboard"),
"m17_dashboard":os .path .join (LIBRARY_DIR ,"m17_dashboard"),
"sysmon":os .path .join (LIBRARY_DIR ,"sysmon"),
"wifimon":os .path .join (LIBRARY_DIR ,"wifimon"),
"44helper":os .path .join (LIBRARY_DIR ,"44helper"),
"instmon":os .path .join (LIBRARY_DIR ,"instmon"),
"svx":os .path .join (LIBRARY_DIR ,"svx"),
"scripts":os .path .join (LIBRARY_DIR ,"scripts"),
"config":os .path .join (LIBRARY_DIR ,"config"),
}


ALLOWED_EXT ={
"dashboard":(".py",),
"m17_dashboard":(".py",),
"sysmon":(".py",),
"wifimon":(".py",),
"44helper":(".py",),
"instmon":(".py",),
"svx":(".py",),
"scripts":(".sh",),
"config":(".conf",),
}


COMPONENTS =[
{
"name":"Dashboard",
"service":"asl_dvs_dashboard",
"port":8989 ,


"install_link":"/usr/local/bin/asl_dvs_dashboard.py",
"category":"dashboard",
},
{
"name":"M17 Dashboard",
"service":"asl_dvs_m17_dashboard",
"port":8989 ,
"install_link":"/usr/local/bin/asl_dvs_m17_dashboard.py",
"category":"m17_dashboard",
},
{
"name":"SysMon",
"service":"sysmon",
"port":9999 ,
"install_link":"/usr/local/bin/sysmon.py",
"category":"sysmon",
},
{
"name":"wifimon",
"service":"wifimon",
"port":None ,
"install_link":"/usr/local/bin/wifimon.py",
"category":"wifimon",
},
{
"name":"44helper",
"service":"44helper",
"port":9997 ,
"install_link":"/opt/44helper/asl_dvs_m17_44helper.py",
"category":"44helper",
},
{
"name":"instmon",
"service":"instmon",
"port":PORT ,
"install_link":INSTALL_BIN_PATH ,
"category":"instmon",
},
{
"name":"SVX Dashboard",
"service":"svx_dashboard",
"port":8991 ,
"install_link":"/usr/local/bin/svx_dashboard.py",
"category":"svx",
},
]




INSTALLABLE_CATEGORIES ={c ["category"]for c in COMPONENTS }










# v1.27.8: retired components -- skipped by the home-dir scan and refused by
# Upload, so they can't land in another category (asl_dvs_watchdog*.sh would
# otherwise match the "scripts" row's asl_dvs*.sh).
RETIRED_FILE_GLOBS =("asl_dvs_watchdog*.sh",)


def _is_retired_file (name ):
    lname =name .lower ()
    return any (fnmatch .fnmatch (lname ,g )for g in RETIRED_FILE_GLOBS )


HOME_SCAN_PATTERN_MAP =[
("dashboard",["asl_dvs_dashboard*.py"]),
("m17_dashboard",["asl_dvs_m17_dashboard*.py"]),
("sysmon",["sysmon*.py","asl_dvs_sysmon*.py","asl_dvs_m17_sysmon*.py"]),
("wifimon",["wifimon*.py"]),
("44helper",["asl_dvs_m17_44helper*.py","44helper*.py"]),
("instmon",["instmon*.py"]),
("svx",["svx_dashboard*.py"]),
("config",["asl_dvs*.conf","sysmon*.conf","wifimon*.conf"]),
("scripts",["install_asl_dvs*.sh","wifi_menu*.sh","wifi-menu*.sh","asl_dvs*.sh"]),
]










COMMS_RESTART_SERVICES =[
("Asterisk","asterisk.service"),
("Analog_Bridge","analog_bridge.service"),
("MMDVM_Bridge","mmdvm_bridge.service"),
("STFU","stfu.service"),
("Allmon3","allmon3.service"),
]






COMMS_RESTART_PAUSE_SEC =3 


LOG_MAX_LINES =500 
_log =deque (maxlen =LOG_MAX_LINES )
_log_lock =threading .Lock ()
_log_seq =0 


_running_scripts =set ()
_running_scripts_lock =threading .Lock ()


_running_installs =set ()
_running_installs_lock =threading .Lock ()


def log_event (message ,level ="info"):
    global _log_seq 
    with _log_lock :
        _log_seq +=1 
        _log .append ({
        "id":_log_seq ,
        "ts":datetime .now ().strftime ("%Y-%m-%d %H:%M:%S"),
        "level":level ,
        "msg":message ,
        })


def ensure_dirs ():
    for path in LIB_SUBDIRS .values ():
        os .makedirs (path ,exist_ok =True )


def safe_join (base_dir ,filename ):
    base_real =os .path .realpath (base_dir )
    candidate =os .path .realpath (os .path .join (base_dir ,os .path .basename (filename )))
    if candidate ==base_real or not candidate .startswith (base_real +os .sep ):
        return None 
    return candidate 


def _file_sha256_uncached (path ):
    if not os .path .isfile (path ):
        return None 
    h =hashlib .sha256 ()
    with open (path ,"rb")as f :
        for chunk in iter (lambda :f .read (65536 ),b""):
            h .update (chunk )
    return h .hexdigest ()


def _category_for_home_file (name ):
    if _is_retired_file (name ):
        return None 
    lname =name .lower ()
    for category ,globs in HOME_SCAN_PATTERN_MAP :
        if any (fnmatch .fnmatch (lname ,g .lower ())for g in globs ):
            return category 
    return None 


def scan_home_for_new_code ():
    moved =[]
    if not HOME_SCAN_ENABLED :
        return moved 

    ensure_dirs ()
    try :
        names =os .listdir (HOME_SCAN_DIR )
    except OSError as exc :
        log_event (f"Home-dir scan skipped ({HOME_SCAN_DIR }): {exc }","warn")
        return moved 

    for name in sorted (names ):
        full =os .path .join (HOME_SCAN_DIR ,name )
        if not os .path .isfile (full )or os .path .islink (full ):
            continue 

        category =_category_for_home_file (name )
        if category is None :
            continue 

        ext =os .path .splitext (name )[1 ].lower ()
        if ext not in ALLOWED_EXT .get (category ,()):
            continue 

        dest_dir =LIB_SUBDIRS [category ]
        dest =os .path .join (dest_dir ,name )

        if os .path .exists (dest ):
            if _file_sha256_uncached (dest )==_file_sha256_uncached (full ):
                continue 
            base ,ext2 =os .path .splitext (name )
            dest =os .path .join (dest_dir ,f"{base }__homescan_{int (time .time ())}{ext2 }")

        try :
            os .makedirs (dest_dir ,exist_ok =True )
            shutil .move (full ,dest )
        except OSError as exc :
            log_event (f"Home-dir scan: failed to move {name }: {exc }","err")
            continue 

        staged_name =os .path .basename (dest )
        moved .append ((name ,category ,staged_name ))
        log_event (f"Home-dir scan: found {name } -> staged to library/{category }/{staged_name }","ok")

    if moved :
        with _file_meta_cache_lock :
            _file_meta_cache .clear ()

    return moved 


def compare_before_write (dest_path ,data_bytes ):
    dest_dir =os .path .dirname (dest_path )
    if dest_dir :
        os .makedirs (dest_dir ,exist_ok =True )
    if os .path .isfile (dest_path ):
        with open (dest_path ,"rb")as f :
            existing =f .read ()
        if existing ==data_bytes :
            return False ,"unchanged (skipped write)"
    tmp_path =dest_path +".tmp"
    with open (tmp_path ,"wb")as f :
        f .write (data_bytes )
    os .replace (tmp_path ,dest_path )
    return True ,"written"


def systemctl_is_active (service ):
    try :
        result =subprocess .run (
        ["systemctl","is-active",service ],
        capture_output =True ,text =True ,timeout =3 ,
        )
        return result .stdout .strip ()or "unknown"
    except (FileNotFoundError ,subprocess .TimeoutExpired ):
        return "unknown"


def port_open (port ,host ="127.0.0.1",timeout =0.5 ):
    if port is None :
        return None 
    try :
        with socket .create_connection ((host ,port ),timeout =timeout ):
            return True 
    except OSError :
        return False 


def attempt_rollback (dest_path ,backup_path ,comp ):

    if not os .path .isfile (backup_path ):
        return False ,None ,None 
    try :
        shutil .copy2 (backup_path ,dest_path )
    except OSError :
        return False ,None ,None 
    subprocess .run (["systemctl","restart",comp ["service"]],capture_output =True ,text =True ,timeout =10 )
    time .sleep (1.5 )
    state =systemctl_is_active (comp ["service"])
    listening =port_open (comp ["port"])
    log_event (f"Rolled back {comp ['name']} to previous version (now {state })","warn")
    return True ,state ,listening 


ROLLBACK_HISTORY_DEPTH =int (os .environ .get ("INSTMON_ROLLBACK_HISTORY_DEPTH","3"))


def _rotate_backups (dest_path ,depth =ROLLBACK_HISTORY_DEPTH ):

    if depth <1 :
        return 
    for n in range (depth ,1 ,-1 ):
        src =dest_path +(".prev"if n ==2 else f".prev{n -1 }")
        dst =dest_path +f".prev{n }"
        if os .path .isfile (src ):
            try :
                os .replace (src ,dst )
            except OSError :
                pass 


def install_file_with_verification (data ,dest_path ,comp ):

    had_existing =os .path .isfile (dest_path )
    backup_path =dest_path +".prev"
    try :
        if had_existing :
            _rotate_backups (dest_path )
            shutil .copy2 (dest_path ,backup_path )
        wrote ,reason =compare_before_write (dest_path ,data )
    except OSError as exc :
        return {
        "wrote":False ,"reason":"error","restarted":False ,
        "active":None ,"listening":None ,
        "message":f"Failed writing {dest_path }: {exc }","level":"err",
        }

    result ={"wrote":wrote ,"reason":reason ,"restarted":False ,"active":None ,"listening":None }
    if not wrote :
        result ["message"]="Already installed (unchanged) -- no restart needed."
        result ["level"]="info"
        return result 

    def rollback_suffix ():
        if not had_existing :
            return " No previous version was available to roll back to."
        rolled_back ,rb_state ,_ =attempt_rollback (dest_path ,backup_path ,comp )
        if rolled_back and rb_state =="active":
            return " Rolled back to the previous version, which is running again."
        elif rolled_back :
            return f" Attempted rollback, but the previous version is now '{rb_state }' too -- check manually."
        return " Rollback attempt failed -- check manually."

    restart =subprocess .run (
    ["systemctl","restart",comp ["service"]],
    capture_output =True ,text =True ,timeout =10 ,
    )
    result ["restarted"]=True 
    if restart .returncode !=0 :
        err_tail =(restart .stderr or restart .stdout or "unknown error").strip ()[:200 ]
        log_event (f"systemctl restart {comp ['service']} failed: {err_tail }","err")
        result ["message"]=f"{comp ['service']} failed to restart: {err_tail }.{rollback_suffix ()}"
        result ["level"]="err"
        return result 


    time .sleep (1.5 )
    state =systemctl_is_active (comp ["service"])
    listening =port_open (comp ["port"])
    result ["active"]=state 
    result ["listening"]=listening 

    if state =="active"and listening :
        log_event (f"{comp ['name']} restarted OK, listening on port {comp ['port']}","ok")
        result ["message"]=f"{comp ['name']} restarted and is listening on port {comp ['port']}."
        result ["level"]="ok"
    elif state =="active":
        log_event (f"{comp ['name']} restarted, active but not yet listening on port {comp ['port']}","warn")
        result ["message"]=f"{comp ['name']} is active but not yet listening on port {comp ['port']} (may still be starting)."
        result ["level"]="warn"
    else :
        log_event (f"{comp ['name']} restarted but is now '{state }'","err")
        result ["message"]=f"{comp ['name']} is now '{state }' after restart.{rollback_suffix ()}"
        result ["level"]="err"

    return result 


FILE_HEADER_SCAN_CAP =32768 


def _scan_file_header_uncached (path ):

    if not os .path .isfile (path ):
        return None ,False ,False 
    try :
        with open (path ,"r",encoding ="utf-8",errors ="replace")as f :
            content =f .read ()
    except OSError :
        return None ,False ,False 
    head =content [:FILE_HEADER_SCAN_CAP ]
    m =re .search (r'^\s*VERSION\s*=\s*"([^"]+)"',head ,re .MULTILINE )
    version =m .group (1 )if m else None 
    self_install =('add_argument("--install"'in content )and ("def install_service"in content )
    self_uninstall =('add_argument("--uninstall"'in content )and ("def uninstall_service"in content )

    
    
    
    
    
    if version is None :
        m =re .search (r'^\s*SCRIPT_VERSION\s*=\s*"([^"]+)"',head ,re .MULTILINE )
        version =m .group (1 )if m else None 
    if not self_install :
        self_install =("--install)"in content )and ("do_install"in content )
    if not self_uninstall :
        self_uninstall =("--uninstall)"in content )and ("do_uninstall"in content )

    return version ,self_install ,self_uninstall 


def _interp_for (path ):
    
    
    return "bash"if path .lower ().endswith (".sh")else "python3"


_file_meta_cache ={}
_file_meta_cache_lock =threading .Lock ()


def _file_meta (path ):

    try :
        st =os .stat (path )
    except OSError :
        return None ,None ,False ,False 
    stamp =(st .st_mtime ,st .st_size )
    with _file_meta_cache_lock :
        cached =_file_meta_cache .get (path )
        if cached and cached [0 ]==stamp :
            return cached [1 ],cached [2 ],cached [3 ],cached [4 ]
    sha =_file_sha256_uncached (path )
    ver ,self_install ,self_uninstall =_scan_file_header_uncached (path )
    with _file_meta_cache_lock :
        _file_meta_cache [path ]=(stamp ,sha ,ver ,self_install ,self_uninstall )
    return sha ,ver ,self_install ,self_uninstall 


def file_sha256 (path ):
    sha ,_ver ,_self_install ,_self_uninstall =_file_meta (path )
    return sha 


def read_installed_version (path ):
    _sha ,ver ,_self_install ,_self_uninstall =_file_meta (path )
    return ver 


def script_has_self_install (path ):

    _sha ,_ver ,self_install ,_self_uninstall =_file_meta (path )
    return self_install 


def script_has_self_uninstall (path ):

    _sha ,_ver ,_self_install ,self_uninstall =_file_meta (path )
    return self_uninstall 


def check_python_syntax (path ):

    tmp_cfile =None 
    try :
        with tempfile .NamedTemporaryFile (suffix =".pyc",delete =False )as tmp :
            tmp_cfile =tmp .name 
        py_compile .compile (path ,cfile =tmp_cfile ,doraise =True )
        return None 
    except py_compile .PyCompileError as exc :
        return str (getattr (exc ,"msg",exc ))
    except (SyntaxError ,ValueError )as exc :
        return str (exc )
    except OSError as exc :
        return f"Could not check syntax: {exc }"
    finally :
        if tmp_cfile and os .path .exists (tmp_cfile ):
            try :
                os .remove (tmp_cfile )
            except OSError :
                pass 


def check_bash_syntax (path ):
    try :
        result =subprocess .run (
        ["bash","-n",path ],capture_output =True ,text =True ,timeout =10 ,
        )
        if result .returncode !=0 :
            return result .stderr .strip ()or f"bash -n exited {result .returncode }"
        return None 
    except (FileNotFoundError ,subprocess .TimeoutExpired )as exc :
        return f"Could not check syntax: {exc }"


def check_script_syntax (path ):
    
    
    
    
    if path .lower ().endswith (".sh"):
        return check_bash_syntax (path )
    return check_python_syntax (path )


def human_size (num_bytes ):
    for unit in ("B","KB","MB","GB"):
        if num_bytes <1024 :
            return f"{num_bytes :.0f} {unit }"if unit =="B"else f"{num_bytes :.1f} {unit }"
        num_bytes /=1024 
    return f"{num_bytes :.1f} TB"


def resolve_installed_target (comp ):

    return os .path .realpath (comp ["install_link"])


def scan_library ():
    ensure_dirs ()
    out ={cat :[]for cat in LIB_SUBDIRS }
    for cat ,dir_path in LIB_SUBDIRS .items ():
        try :
            names =os .listdir (dir_path )
        except OSError :
            names =[]
        for name in names :
            full =os .path .join (dir_path ,name )
            if not os .path .isfile (full ):
                continue 
            stat =os .stat (full )
            entry ={
            "name":name ,
            "size":human_size (stat .st_size ),
            "mtime":datetime .fromtimestamp (stat .st_mtime ).strftime ("%Y-%m-%d %H:%M"),
            "mtime_epoch":stat .st_mtime ,
            "category":cat ,
            }
            if cat in INSTALLABLE_CATEGORIES :
                ver =read_installed_version (full )
                entry ["version"]=ver or "?"
                comp =next ((c for c in COMPONENTS if c ["category"]==cat ),None )
                if comp :
                    entry ["installed"]=(file_sha256 (full )==file_sha256 (resolve_installed_target (comp )))
                else :
                    entry ["installed"]=False 
            elif cat =="config":
                live_cfg =os .path .join (CONFIG_DIR ,CONFIG_NAME )
                entry ["installed"]=(file_sha256 (full )==file_sha256 (live_cfg ))
                entry ["version"]="config"
            else :
                entry ["installed"]=None 
                entry ["version"]="script"
            out [cat ].append (entry )
        out [cat ].sort (key =lambda e :e ["mtime_epoch"],reverse =True )
    return out 


def build_status ():
    components =[]
    quiet =quiet_snapshot ()
    for comp in COMPONENTS :
        state =systemctl_is_active (comp ["service"])
        listening =port_open (comp ["port"])
        installed_target =resolve_installed_target (comp )
        components .append ({
        "name":comp ["name"],
        "service":comp ["service"],
        "port":comp ["port"],
        "category":comp ["category"],
        "state":state ,
        "listening":listening ,
        "version":read_installed_version (installed_target )or "?",


        "installed":os .path .isfile (installed_target ),
        "quiet":comp ["service"]in quiet ["stopped"],
        })
    return {
    "quiet":quiet ,
    "update":update_snapshot (),
    "components":components ,
    "library":scan_library (),
    "config":{
    "name":CONFIG_NAME ,
    "installed":os .path .isfile (os .path .join (CONFIG_DIR ,CONFIG_NAME )),
    },
    }


def is_installer_script (name ):

    return fnmatch .fnmatch (name .lower (),INSTALLER_SCRIPT_GLOB .lower ())


def is_interactive_only_script (name ):

    return any (fnmatch .fnmatch (name .lower (),g .lower ())for g in INTERACTIVE_ONLY_SCRIPT_GLOBS )


def run_script_bg (script_path ,script_name ,env_overrides =None ):

    if env_overrides :
        shown =" ".join (f"{k }={v }"for k ,v in env_overrides .items ())
        log_event (f"Running script: {script_name } ({shown })","info")
    else :
        log_event (f"Running script: {script_name }","info")
    try :
        env =os .environ .copy ()
        if env_overrides :
            env .update (env_overrides )
        proc =subprocess .Popen (
        ["bash",script_path ],
        stdout =subprocess .PIPE ,stderr =subprocess .STDOUT ,
        text =True ,bufsize =1 ,env =env ,
        )
        for line in proc .stdout :
            log_event (line .rstrip ("\n"),"info")
        proc .wait (timeout =SCRIPT_TIMEOUT_SEC )
        if proc .returncode ==0 :
            log_event (f"Script finished OK: {script_name }","ok")
        else :
            log_event (f"Script exited {proc .returncode }: {script_name }","err")
    except subprocess .TimeoutExpired :
        proc .kill ()
        log_event (f"Script timed out ({SCRIPT_TIMEOUT_SEC }s), killed: {script_name }","err")
    except Exception as exc :
        log_event (f"Script failed to run: {script_name }: {exc }","err")
    finally :
        with _running_scripts_lock :
            _running_scripts .discard (script_name )


def run_self_install_bg (script_path ,script_name ,comp ):

    log_event (f"Installing {script_name } ({comp ['name']}) -- running its own --install...","info")
    try :
        proc =subprocess .Popen (
        [_interp_for (script_path ),script_path ,"--install"],
        stdout =subprocess .PIPE ,stderr =subprocess .STDOUT ,
        text =True ,bufsize =1 ,
        )
        for line in proc .stdout :
            log_event (line .rstrip ("\n"),"info")
        proc .wait (timeout =SCRIPT_TIMEOUT_SEC )
        if proc .returncode ==0 :
            log_event (f"Install finished OK: {script_name } ({comp ['name']})","ok")
            quiet_forget (comp ["service"])
        else :
            log_event (f"Install exited {proc .returncode }: {script_name } ({comp ['name']})","err")
    except subprocess .TimeoutExpired :
        proc .kill ()
        log_event (f"Install timed out ({SCRIPT_TIMEOUT_SEC }s), killed: {script_name } ({comp ['name']})","err")
    except Exception as exc :
        log_event (f"Install failed to run: {script_name } ({comp ['name']}): {exc }","err")
    finally :
        with _running_installs_lock :
            _running_installs .discard (comp ["service"])


def stage_installed_copy_if_missing (comp ):

    target =resolve_installed_target (comp )
    target_hash =file_sha256 (target )
    if target_hash is None :
        return False ,None ,"",f"could not hash the installed {comp ['name']} file at {target }"

    lib_dir =LIB_SUBDIRS [comp ["category"]]
    ensure_dirs ()
    try :
        existing_names =os .listdir (lib_dir )
    except OSError as exc :
        return False ,None ,"",f"could not read the {comp ['category']} library dir: {exc }"

    for existing_name in existing_names :
        full =os .path .join (lib_dir ,existing_name )
        if os .path .isfile (full )and file_sha256 (full )==target_hash :
            return False ,existing_name ,f"already present in the library as {existing_name }",None 

    base_name =os .path .basename (target )
    candidate =base_name 
    n =2 
    while os .path .exists (os .path .join (lib_dir ,candidate )):
        stem ,ext =os .path .splitext (base_name )
        candidate =f"{stem }_{n }{ext }"
        n +=1 

    try :
        shutil .copy2 (target ,os .path .join (lib_dir ,candidate ))
    except OSError as exc :
        return False ,None ,"",f"could not stage a library copy before uninstall: {exc }"

    log_event (f"Staged installed {comp ['name']} file into the library as {candidate } before uninstall","info")
    return True ,candidate ,f"staged a library copy as {candidate }",None 


def run_self_uninstall_bg (comp ):

    script_path =comp ["install_link"]
    log_event (f"Uninstalling {comp ['name']} -- running its own --uninstall...","info")
    try :
        proc =subprocess .Popen (
        [_interp_for (script_path ),script_path ,"--uninstall"],
        stdout =subprocess .PIPE ,stderr =subprocess .STDOUT ,
        text =True ,bufsize =1 ,
        )
        for line in proc .stdout :
            log_event (line .rstrip ("\n"),"info")
        proc .wait (timeout =SCRIPT_TIMEOUT_SEC )
        if proc .returncode ==0 :
            log_event (f"Uninstall finished OK: {comp ['name']}","ok")
            quiet_forget (comp ["service"])
        else :
            log_event (f"Uninstall exited {proc .returncode }: {comp ['name']}","err")
    except subprocess .TimeoutExpired :
        proc .kill ()
        log_event (f"Uninstall timed out ({SCRIPT_TIMEOUT_SEC }s), killed: {comp ['name']}","err")
    except Exception as exc :
        log_event (f"Uninstall failed to run: {comp ['name']}: {exc }","err")
    finally :
        with _running_installs_lock :
            _running_installs .discard (comp ["service"])


# v1.27.9: Quiet System -- stop the node's optional web UIs and helpers so a
# small Pi (Zero 2 W) has memory and CPU for uploads, installs and Full
# Update.  The list is fixed here; the browser never names a unit.  Radio,
# Asterisk, Allmon3, SSH, wifimon (Wi-Fi fallback), Cockpit and instmon
# itself are never touched.  The watchdog timer goes first -- it would
# otherwise restart the dashboard it watches.
QUIET_SERVICES =[
("Watchdog timer","asl_dvs_watchdog.timer"),
("SysMon","sysmon"),
("Dashboard","asl_dvs_dashboard"),
("M17 Dashboard","asl_dvs_m17_dashboard"),
("SVX Dashboard","svx_dashboard"),
("44helper","44helper"),
]

QUIET_AUTO_RESTORE_SEC =int (os .environ .get ("INSTMON_QUIET_AUTO_RESTORE_SEC","1800"))

QUIET_STATE_PATH =os .path .join (STATE_DIR ,"quiet.json")

_quiet_lock =threading .Lock ()
_quiet ={"on":False ,"since":0.0 ,"reason":"","stopped":[]}
_quiet_timer =None 


def _write_json_atomic (path ,payload ):
    os .makedirs (os .path .dirname (path ),exist_ok =True )
    tmp_path =path +".tmp"
    with open (tmp_path ,"w")as f :
        json .dump (payload ,f )
    os .replace (tmp_path ,path )


def _read_json (path ):
    try :
        with open (path )as f :
            return json .load (f )
    except (OSError ,ValueError ):
        return None 


def _systemctl (verb ,unit ,timeout =15 ):
    try :
        r =subprocess .run (["systemctl",verb ,unit ],capture_output =True ,text =True ,timeout =timeout )
    except (FileNotFoundError ,subprocess .TimeoutExpired )as exc :
        return False ,str (exc )
    return r .returncode ==0 ,(r .stderr or r .stdout or "").strip ()[:200 ]


def _quiet_save ():
    try :
        _write_json_atomic (QUIET_STATE_PATH ,_quiet )
    except OSError as exc :
        log_event (f"Quiet: could not save state to {QUIET_STATE_PATH}: {exc}","warn")


def _quiet_arm_timer (delay ):
    global _quiet_timer 
    if _quiet_timer :
        _quiet_timer .cancel ()
    _quiet_timer =None 
    if QUIET_AUTO_RESTORE_SEC >0 :
        _quiet_timer =threading .Timer (max (delay ,1 ),_quiet_auto_restore )
        _quiet_timer .daemon =True 
        _quiet_timer .start ()


def _quiet_auto_restore ():
    if update_running ():
        # Full Update restores at its own end; check again later.
        _quiet_arm_timer (60 )
        return 
    log_event (f"Quiet: auto-restore after {QUIET_AUTO_RESTORE_SEC // 60} min","warn")
    quiet_restore ("auto-restore")


def quiet_snapshot ():
    with _quiet_lock :
        return {
        "on":_quiet ["on"],
        "since":_quiet ["since"],
        "since_text":datetime .fromtimestamp (_quiet ["since"]).strftime ("%H:%M")if _quiet ["on"]else "",
        "reason":_quiet ["reason"],
        "stopped":list (_quiet ["stopped"]),
        "auto_restore_min":QUIET_AUTO_RESTORE_SEC //60 ,
        }


def quiet_on (reason ):
    with _quiet_lock :
        if _quiet ["on"]:
            return {"already":True ,"stopped":list (_quiet ["stopped"]),"failed":[]}
        stopped ,failed =[],[]
        for label ,unit in QUIET_SERVICES :
            if systemctl_is_active (unit )!="active":
                continue 
            ok ,err =_systemctl ("stop",unit )
            state =systemctl_is_active (unit )
            if ok and state !="active":
                stopped .append (unit )
                log_event (f"Quiet: stopped {label} ({unit})","info")
            else :
                failed .append (label )
                log_event (f"Quiet: {label} ({unit}) did not stop (now {state}) {err}","err")
        _quiet .update (on =True ,since =time .time (),reason =reason ,stopped =stopped )
        _quiet_save ()
    _quiet_arm_timer (QUIET_AUTO_RESTORE_SEC )
    return {"already":False ,"stopped":stopped ,"failed":failed }


def quiet_restore (reason ):
    global _quiet_timer 
    with _quiet_lock :
        if not _quiet ["on"]:
            return {"already":True ,"started":[],"failed":[]}
        started ,failed =[],[]
        labels =dict ((unit ,label )for label ,unit in QUIET_SERVICES )
        # Reverse order: the watchdog timer comes back last, after what it watches.
        for unit in reversed (_quiet ["stopped"]):
            label =labels .get (unit ,unit )
            ok ,err =_systemctl ("start",unit )
            state =systemctl_is_active (unit )
            if ok and state =="active":
                started .append (unit )
                log_event (f"Restore: started {label} ({unit})","ok")
            else :
                failed .append (label )
                log_event (f"Restore: {label} ({unit}) did not start (now {state}) {err}","err")
        _quiet .update (on =False ,since =0.0 ,reason ="",stopped =[])
        _quiet_save ()
        if _quiet_timer :
            _quiet_timer .cancel ()
            _quiet_timer =None 
    log_event (f"Quiet: system restored ({reason})","ok"if not failed else "err")
    return {"already":False ,"started":started ,"failed":failed }


def quiet_forget (service ):
    # An install/uninstall already started (or removed) this service, so
    # Restore must not touch it again.
    with _quiet_lock :
        if service in _quiet ["stopped"]:
            _quiet ["stopped"].remove (service )
            _quiet_save ()


def quiet_resume_at_startup ():
    saved =_read_json (QUIET_STATE_PATH )
    if not saved or not saved .get ("on"):
        return 
    with _quiet_lock :
        _quiet .update (on =True ,since =float (saved .get ("since")or time .time ()),
        reason =str (saved .get ("reason")or ""),
        stopped =[u for u in saved .get ("stopped",[])if u in dict ((s ,l )for l ,s in QUIET_SERVICES )])
    age =time .time ()-_quiet ["since"]
    if QUIET_AUTO_RESTORE_SEC >0 and age >=QUIET_AUTO_RESTORE_SEC :
        log_event ("Quiet: was still on from before instmon restarted and is past its auto-restore time -- restoring now","warn")
        quiet_restore ("startup")
    else :
        log_event (f"Quiet: still on from before instmon restarted ({len(_quiet['stopped'])} service(s) stopped)","warn")
        _quiet_arm_timer (QUIET_AUTO_RESTORE_SEC -age )


# v1.27.9: Check for updates / Full Update from GitHub.  Source is fixed
# here (public repo, read-only, HTTPS); the browser can't point it anywhere
# else.  Every download is checked against GitHub's own blob hash.
UPDATE_REPO ="kd8pgk/ASL-DVS"
UPDATE_BRANCH ="main"
UPDATE_API_BASE ="https://api.github.com"
UPDATE_RAW_HOST ="raw.githubusercontent.com"
UPDATE_HTTP_TIMEOUT =30 
UPDATE_MAX_FILE_BYTES =8 *1024 *1024 
UPDATE_START_TIMEOUT_SEC =int (os .environ .get ("INSTMON_UPDATE_START_TIMEOUT_SEC","60"))
UPDATE_SELF_GUARD_SEC =90 

# One component at a time, in this order; instmon last because installing
# it restarts this process.
UPDATE_ORDER =["44helper","wifimon","svx","dashboard","m17_dashboard","sysmon","instmon"]

# Name stem of a plain (non-variant) build, used when the installed file's
# own name doesn't carry one (e.g. /usr/local/bin/wifimon.py).
UPDATE_DEFAULT_STEM ={
"dashboard":"asl_dvs_dashboard",
"m17_dashboard":"asl_dvs_m17_dashboard",
"sysmon":"sysmon",
"wifimon":"wifimon",
"44helper":"asl_dvs_m17_44helper",
"instmon":"instmon",
"svx":"svx_dashboard",
}

UPDATE_STATE_PATH =os .path .join (STATE_DIR ,"update.json")
UPDATE_STAGING_DIR =os .path .join (STATE_DIR ,"staging")

_REPO_NAME_RE =re .compile (r"^(?P<stem>.+?)_v(?P<ver>\d+(?:_\d+)*?)(?:_(?P<date>\d{8}))?\.(?:py|sh)$",re .IGNORECASE )

_update_lock =threading .Lock ()
_update ={
"running":False ,"phase":"","current":"","started":0.0 ,"finished":0.0 ,
"error":"","updated":[],"skipped":[],"attention":[],"scripts":[],
"unchanged":[],"banner":False ,"instmon_pending":None ,
}
_update_check ={"at":0.0 ,"result":None }


def update_running ():
    with _update_lock :
        return _update ["running"]


def _update_set (**kw ):
    with _update_lock :
        _update .update (kw )


def _update_save ():
    with _update_lock :
        payload =dict (_update )
    try :
        _write_json_atomic (UPDATE_STATE_PATH ,payload )
    except OSError as exc :
        log_event (f"Full Update: could not save state: {exc}","warn")


def update_snapshot ():
    with _update_lock :
        snap =json .loads (json .dumps (_update ))
    snap ["check"]=_update_check ["result"]
    snap ["check_at"]=(datetime .fromtimestamp (_update_check ["at"]).strftime ("%H:%M")
    if _update_check ["at"]else "")
    return snap 


def _version_tuple (text ):
    if not text :
        return None 
    m =re .match (r"^\s*v?(\d+(?:[._]\d+)*)",str (text ))
    if not m :
        return None 
    return tuple (int (p )for p in re .split (r"[._]",m .group (1 )))


def _parse_repo_name (name ):
    m =_REPO_NAME_RE .match (name )
    if not m :
        return os .path .splitext (name )[0 ].lower (),None ,""
    return m .group ("stem").lower (),_version_tuple (m .group ("ver")),m .group ("date")or ""


def _git_blob_sha (data ):
    return hashlib .sha1 (b"blob %d\0"%len (data )+data ).hexdigest ()


def _file_git_blob_sha (path ):
    try :
        with open (path ,"rb")as f :
            return _git_blob_sha (f .read ())
    except OSError :
        return None 


class _SameHostRedirect (urllib .request .HTTPRedirectHandler ):
    def redirect_request (self ,req ,fp ,code ,msg ,headers ,newurl ):
        host =urllib .parse .urlparse (newurl ).hostname or ""
        if urllib .parse .urlparse (newurl ).scheme !="https"or host not in _update_allowed_hosts ():
            raise urllib .error .HTTPError (newurl ,code ,f"redirect to {host} refused",headers ,fp )
        return super ().redirect_request (req ,fp ,code ,msg ,headers ,newurl )


def _update_allowed_hosts ():
    return {urllib .parse .urlparse (UPDATE_API_BASE ).hostname ,UPDATE_RAW_HOST }


def _http_get (url ,max_bytes ):
    parsed =urllib .parse .urlparse (url )
    if parsed .scheme !="https"or parsed .hostname not in _update_allowed_hosts ():
        raise ValueError (f"refusing to fetch {url} (only {', '.join(sorted(_update_allowed_hosts()))})")
    req =urllib .request .Request (url ,headers ={
    "User-Agent":f"instmon/{VERSION}",
    "Accept":"application/vnd.github+json"if parsed .hostname !=UPDATE_RAW_HOST else "*/*",
    })
    opener =urllib .request .build_opener (_SameHostRedirect )
    with opener .open (req ,timeout =UPDATE_HTTP_TIMEOUT )as resp :
        data =resp .read (max_bytes +1 )
    if len (data )>max_bytes :
        raise ValueError (f"{url} is larger than {max_bytes // (1024 * 1024)} MB")
    return data 


def _fetch_repo_listing ():
    url =(f"{UPDATE_API_BASE}/repos/{UPDATE_REPO}/contents"
    f"?ref={urllib.parse.quote(UPDATE_BRANCH)}")
    items =json .loads (_http_get (url ,4 *1024 *1024 ).decode ("utf-8"))
    if not isinstance (items ,list ):
        raise ValueError ("unexpected reply from GitHub")
    return [i for i in items if isinstance (i ,dict )and i .get ("type")=="file"
    and isinstance (i .get ("name"),str )and isinstance (i .get ("sha"),str )]


def _repo_candidates (listing ):
    # category -> list of repo entries, each with its parsed name.  Config
    # files are never offered (they would overwrite this node's settings),
    # nor retired ones.
    out ={}
    for item in listing :
        name =item ["name"]
        if "/"in name or name .startswith ("."):
            continue 
        cat =_category_for_home_file (name )
        if cat is None or cat =="config":
            continue 
        if os .path .splitext (name )[1 ].lower ()not in ALLOWED_EXT .get (cat ,()):
            continue 
        stem ,ver ,date =_parse_repo_name (name )
        out .setdefault (cat ,[]).append ({
        "name":name ,"sha":item ["sha"],"size":int (item .get ("size")or 0 ),
        "download_url":item .get ("download_url")or "",
        "stem":stem ,"ver":ver ,"date":date ,
        })
    return out 


def _newest (entries ):
    return max (entries ,key =lambda e :(e ["ver"]or (),e ["date"],e ["name"]))


def _ver_text (t ):
    return ".".join (str (n )for n in t )if t else "?"


def _installed_identity (comp ,by_blob ):
    # (stem, version tuple, how) for the installed file.  Version comes from
    # its VERSION line, else from a library or repo file with identical
    # content (wifimon and 44helper have no VERSION line).
    target =resolve_installed_target (comp )
    base =os .path .basename (target )
    stem ,name_ver ,_date =_parse_repo_name (base )
    ver_str =read_installed_version (target )or ""
    ver =_version_tuple (ver_str )or name_ver 
    if not _REPO_NAME_RE .match (base ):
        stem =UPDATE_DEFAULT_STEM [comp ["category"]]
        suffix =re .search (r"-([a-z0-9]+)\s*$",ver_str ,re .IGNORECASE )
        if suffix :
            stem =f"{stem}_{suffix.group(1).lower()}"
    if ver is None :
        blob =_file_git_blob_sha (target )
        sha =file_sha256 (target )
        lib_dir =LIB_SUBDIRS [comp ["category"]]
        try :
            lib_names =os .listdir (lib_dir )
        except OSError :
            lib_names =[]
        for name in lib_names :
            if _REPO_NAME_RE .match (name )and file_sha256 (os .path .join (lib_dir ,name ))==sha :
                stem ,ver ,_date =_parse_repo_name (name )
                break 
        if ver is None and blob in by_blob :
            stem ,ver ,_date =_parse_repo_name (by_blob [blob ])
    return stem ,ver 


def update_check ():
    listing =_fetch_repo_listing ()
    by_blob ={i ["sha"]:i ["name"]for i in listing }
    cands =_repo_candidates (listing )
    components =[]
    for cat in UPDATE_ORDER :
        comp =next (c for c in COMPONENTS if c ["category"]==cat )
        row ={"category":cat ,"name":comp ["name"],"status":"","note":"",
        "installed_version":"","repo_file":"","repo_version":""}
        components .append (row )
        target =resolve_installed_target (comp )
        if not os .path .isfile (target ):
            row .update (status ="not_installed",note ="not installed -- left alone")
            continue 
        stem ,inst_ver =_installed_identity (comp ,by_blob )
        row ["installed_version"]=_ver_text (inst_ver )if inst_ver else (read_installed_version (target )or "?")
        same_variant =[e for e in cands .get (cat ,[])if e ["stem"]==stem ]
        if not same_variant :
            row .update (status ="not_in_repo",note =f"no {stem} build in the repo")
            continue 
        best =_newest (same_variant )
        row .update (repo_file =best ["name"],repo_version =_ver_text (best ["ver"]),sha =best ["sha"],
        size =best ["size"],download_url =best ["download_url"])
        if _file_git_blob_sha (target )==best ["sha"]:
            row .update (status ="current",note ="same file as the repo")
        elif inst_ver is None :
            row .update (status ="unknown",note ="can't tell the installed version -- update it by hand from the library")
        elif best ["ver"]and best ["ver"]>inst_ver :
            row .update (status ="update",note =f"{_ver_text(inst_ver)} -> {_ver_text(best['ver'])}")
        elif best ["ver"]==inst_ver :
            row .update (status ="current",note ="same version (file differs locally)")
        else :
            row .update (status ="newer_installed",note ="installed build is newer than the repo")
    scripts =[]
    lib_blobs =set ()
    try :
        for name in os .listdir (LIB_SUBDIRS ["scripts"]):
            b =_file_git_blob_sha (os .path .join (LIB_SUBDIRS ["scripts"],name ))
            if b :
                lib_blobs .add (b )
    except OSError :
        pass 
    by_stem ={}
    for e in cands .get ("scripts",[]):
        by_stem .setdefault (e ["stem"],[]).append (e )
    for stem in sorted (by_stem ):
        best =_newest (by_stem [stem ])
        scripts .append ({"name":best ["name"],"sha":best ["sha"],"size":best ["size"],
        "download_url":best ["download_url"],
        "status":"in_library"if best ["sha"]in lib_blobs else "new"})
    result ={"components":components ,"scripts":scripts ,
    "updates":sum (1 for c in components if c ["status"]=="update"),
    "new_scripts":sum (1 for s in scripts if s ["status"]=="new")}
    _update_check .update (at =time .time (),result =result )
    return result 


def _download_verified (entry ,dest_path ):
    url =entry .get ("download_url")or ""
    if not url :
        raise ValueError ("no download address from GitHub")
    data =_http_get (url ,UPDATE_MAX_FILE_BYTES )
    if _git_blob_sha (data )!=entry ["sha"]:
        raise ValueError ("download doesn't match GitHub's hash for the file")
    os .makedirs (os .path .dirname (dest_path ),exist_ok =True )
    with open (dest_path ,"wb")as f :
        f .write (data )
    return data 


def _stage_to_library (category ,name ,data ):
    # Same name already in the library with different content (edited
    # locally) is kept; the download gets a suffixed name instead.
    lib_dir =LIB_SUBDIRS [category ]
    os .makedirs (lib_dir ,exist_ok =True )
    dest =safe_join (lib_dir ,name )
    if dest is None :
        raise ValueError (f"bad file name {name}")
    if os .path .isfile (dest ):
        with open (dest ,"rb")as f :
            if f .read ()==data :
                return dest 
        stem ,ext =os .path .splitext (name )
        dest =os .path .join (lib_dir ,f"{stem}__github_{int(time.time())}{ext}")
    compare_before_write (dest ,data )
    with _file_meta_cache_lock :
        _file_meta_cache .clear ()
    return dest 


def _run_cli (script_path ,flag ):
    # Runs a component file's own --install / --uninstall and waits; output
    # goes to the log.  Returns the exit code (None if it never ran).
    try :
        proc =subprocess .Popen (
        [_interp_for (script_path ),script_path ,flag ],
        stdout =subprocess .PIPE ,stderr =subprocess .STDOUT ,text =True ,bufsize =1 ,
        )
    except OSError as exc :
        log_event (f"Could not run {os.path.basename(script_path)} {flag}: {exc}","err")
        return None 
    try :
        for line in proc .stdout :
            log_event (line .rstrip ("\n"),"info")
        proc .wait (timeout =SCRIPT_TIMEOUT_SEC )
    except subprocess .TimeoutExpired :
        proc .kill ()
        log_event (f"{os.path.basename(script_path)} {flag} timed out ({SCRIPT_TIMEOUT_SEC}s), killed","err")
        return None 
    return proc .returncode 


def _wait_healthy (comp ):
    deadline =time .time ()+UPDATE_START_TIMEOUT_SEC 
    state ="unknown"
    while time .time ()<deadline :
        state =systemctl_is_active (comp ["service"])
        if state =="active"and (comp ["port"]is None or port_open (comp ["port"])):
            return True ,state 
        time .sleep (2 )
    if state =="active":
        return False ,f"running but not answering on port {comp['port']}"
    return False ,state 


def _update_one (comp ,row ,new_path ):
    name =comp ["name"]
    target =resolve_installed_target (comp )
    if not script_has_self_uninstall (target ):
        return "skipped","installed file has no --uninstall, left alone"
    staged ,old_name ,_note ,stage_err =stage_installed_copy_if_missing (comp )
    if stage_err :
        return "skipped",f"couldn't save a copy of the installed version ({stage_err}), left alone"
    old_path =os .path .join (LIB_SUBDIRS [comp ["category"]],old_name )
    old_ver =row ["installed_version"]

    _update_set (current =f"{name}: uninstalling v{old_ver}")
    log_event (f"Full Update: {name}: uninstalling v{old_ver}","info")
    rc =_run_cli (comp ["install_link"],"--uninstall")
    if rc !=0 :
        log_event (f"Full Update: {name}: --uninstall exited {rc}; installing the new file anyway","warn")
    quiet_forget (comp ["service"])

    _update_set (current =f"{name}: installing v{row['repo_version']}")
    log_event (f"Full Update: {name}: installing {os.path.basename(new_path)}","info")
    rc =_run_cli (new_path ,"--install")
    ok ,state =_wait_healthy (comp )if rc ==0 else (False ,f"--install exited {rc}")
    if ok :
        log_event (f"Full Update: {name} updated v{old_ver} -> v{row['repo_version']}","ok")
        return "updated",f"v{old_ver} -> v{row['repo_version']}"

    reason =f"new version failed ({state})"
    log_event (f"Full Update: {name}: {reason} -- reinstalling v{old_ver}","err")
    _update_set (current =f"{name}: rolling back to v{old_ver}")
    rc =_run_cli (old_path ,"--install")
    ok ,state =_wait_healthy (comp )if rc ==0 else (False ,f"--install exited {rc}")
    if ok :
        log_event (f"Full Update: {name} rolled back to v{old_ver}","warn")
        return "skipped",f"{reason}; rolled back to v{old_ver}"
    log_event (f"Full Update: {name} NEEDS ATTENTION -- the old version didn't come back either ({state})","err")
    return "attention",f"{reason}; rollback to v{old_ver} also failed ({state}) -- not running"


def _arm_instmon_guard (old_path ):
    # After instmon restarts into the new version, a transient systemd timer
    # checks the port; if the new instmon never answers, it reinstalls the
    # saved old copy.  Runs outside this process, which is about to exit.
    check =(f"timeout 5 bash -c '</dev/tcp/127.0.0.1/{PORT}' || "
    f"{_interp_for(old_path)} {shlex.quote(old_path)} --install")
    subprocess .run (["systemctl","stop","instmon-update-guard.timer","instmon-update-guard.service"],
    capture_output =True ,text =True ,timeout =10 )
    subprocess .run (["systemctl","reset-failed","instmon-update-guard.service"],
    capture_output =True ,text =True ,timeout =10 )
    r =subprocess .run ([
    "systemd-run","--quiet","--collect",f"--on-active={UPDATE_SELF_GUARD_SEC}",
    "--unit=instmon-update-guard","bash","-c",check ,
    ],capture_output =True ,text =True ,timeout =15 )
    return r .returncode ==0 ,(r .stderr or "").strip ()[:200 ]


def _update_finish (error =""):
    _update_set (running =False ,phase ="done",current ="",finished =time .time (),error =error ,banner =True )
    _update_save ()
    snap =update_snapshot ()
    parts =[]
    if error :
        parts .append (f"stopped: {error}")
    parts .append (f"{len(snap['updated'])} updated")
    if snap ["skipped"]:
        parts .append (f"{len(snap['skipped'])} skipped")
    if snap ["attention"]:
        parts .append (f"{len(snap['attention'])} NEED ATTENTION")
    if snap ["scripts"]:
        parts .append (f"{len(snap['scripts'])} script(s) added to the library")
    level ="err"if (snap ["attention"]or error )else ("warn"if snap ["skipped"]else "ok")
    log_event ("Full Update finished: "+", ".join (parts ),level )
    for r in snap ["skipped"]:
        log_event (f"  skipped {r['name']}: {r['note']}","warn")
    for r in snap ["attention"]:
        log_event (f"  NEEDS ATTENTION {r['name']}: {r['note']}","err")


def run_full_update_bg ():
    try :
        _run_full_update ()
    except Exception as exc :
        log_event (f"Full Update: unexpected error: {exc}","err")
        if update_snapshot ()["phase"]not in ("done","instmon"):
            if quiet_snapshot ()["on"]:
                quiet_restore ("Full Update error")
            _update_finish (f"unexpected error: {exc}")


def _run_full_update ():
    log_event ("Full Update: checking GitHub for new files...","info")
    _update_set (phase ="checking",current ="checking GitHub")
    try :
        check =update_check ()
    except Exception as exc :
        _update_finish (f"couldn't read GitHub ({exc}) -- nothing was changed")
        return 
    plan =[c for c in check ["components"]if c ["status"]=="update"]
    new_scripts =[s for s in check ["scripts"]if s ["status"]=="new"]
    _update_set (unchanged =[{"name":c ["name"],"note":c ["note"]}for c in check ["components"]
    if c ["status"]!="update"])
    if not plan and not new_scripts :
        log_event ("Full Update: everything is already current -- nothing to do","ok")
        _update_finish ()
        return 

    shutil .rmtree (UPDATE_STAGING_DIR ,ignore_errors =True )
    os .makedirs (UPDATE_STAGING_DIR ,exist_ok =True )
    skipped ,scripts_done =[],[]

    _update_set (phase ="downloading",current ="downloading")
    staged =[]
    for row in plan :
        name =row ["repo_file"]
        _update_set (current =f"downloading {name}")
        try :
            data =_download_verified (row ,os .path .join (UPDATE_STAGING_DIR ,name ))
            tmp =os .path .join (UPDATE_STAGING_DIR ,name )
            err =check_script_syntax (tmp )
            if err :
                raise ValueError (f"syntax error in download: {err[:120]}")
            _sha ,_ver ,can_install ,can_uninstall =_file_meta (tmp )
            if not (can_install and can_uninstall ):
                raise ValueError ("download has no --install/--uninstall")
            lib_path =_stage_to_library (row ["category"],name ,data )
        except Exception as exc :
            log_event (f"Full Update: {row['name']}: {name} skipped -- {exc}","err")
            skipped .append ({"name":row ["name"],"note":f"{name}: {exc}"})
            continue 
        log_event (f"Full Update: downloaded and checked {name}","ok")
        staged .append ((row ,lib_path ))
    for s in new_scripts :
        _update_set (current =f"downloading {s['name']}")
        try :
            data =_download_verified (s ,os .path .join (UPDATE_STAGING_DIR ,s ["name"]))
            err =check_bash_syntax (os .path .join (UPDATE_STAGING_DIR ,s ["name"]))
            if err :
                raise ValueError (f"syntax error in download: {err[:120]}")
            _stage_to_library ("scripts",s ["name"],data )
        except Exception as exc :
            log_event (f"Full Update: script {s['name']} skipped -- {exc}","err")
            skipped .append ({"name":s ["name"],"note":str (exc )})
            continue 
        log_event (f"Full Update: added script {s['name']} to the library (not run)","ok")
        scripts_done .append ({"name":s ["name"],"note":"added to the library Scripts (not run)"})
    shutil .rmtree (UPDATE_STAGING_DIR ,ignore_errors =True )
    _update_set (skipped =list (skipped ),scripts =scripts_done )

    if not staged :
        _update_finish ()
        return 

    _update_set (phase ="quieting",current ="quieting the system")
    quiet_on ("Full Update")

    updated ,attention =[],[]
    instmon_job =None 
    for row ,lib_path in staged :
        comp =next (c for c in COMPONENTS if c ["category"]==row ["category"])
        if comp ["category"]=="instmon":
            instmon_job =(comp ,row ,lib_path )
            continue 
        _update_set (phase ="updating")
        with _running_installs_lock :
            _running_installs .add (comp ["service"])
        try :
            outcome ,note =_update_one (comp ,row ,lib_path )
        finally :
            with _running_installs_lock :
                _running_installs .discard (comp ["service"])
        entry ={"name":comp ["name"],"note":note }
        {"updated":updated ,"skipped":skipped ,"attention":attention }[outcome ].append (entry )
        _update_set (updated =list (updated ),skipped =list (skipped ),attention =list (attention ))

    _update_set (phase ="restoring",current ="restoring the system")
    quiet_restore ("Full Update")

    if instmon_job is None :
        _update_finish ()
        return 

    comp ,row ,lib_path =instmon_job 
    _staged_new ,old_name ,_note ,stage_err =stage_installed_copy_if_missing (comp )
    if stage_err :
        skipped .append ({"name":"instmon","note":f"couldn't save a copy of the installed version ({stage_err}), left alone"})
        _update_set (skipped =list (skipped ))
        _update_finish ()
        return 
    old_path =os .path .join (LIB_SUBDIRS ["instmon"],old_name )
    guard_ok ,guard_err =_arm_instmon_guard (old_path )
    if not guard_ok :
        skipped .append ({"name":"instmon","note":f"couldn't arm the rollback guard ({guard_err}), left alone"})
        _update_set (skipped =list (skipped ))
        _update_finish ()
        return 
    # instmon is replaced in place by its own --install (an --uninstall
    # would stop this process before the new one went in).  Results are
    # saved first: the restart ends this process, and the new instmon reads
    # them back at startup.
    _update_set (phase ="instmon",current =f"instmon: installing v{row['repo_version']}",
    instmon_pending ={"from":row ["installed_version"],"to":row ["repo_version"]})
    _update_save ()
    log_event (f"Full Update: instmon: installing v{row['repo_version']} -- this page reconnects when it restarts","info")
    rc =_run_cli (lib_path ,"--install")
    if rc !=0 :
        subprocess .run (["systemctl","stop","instmon-update-guard.timer"],capture_output =True ,text =True ,timeout =10 )
        skipped .append ({"name":"instmon","note":f"--install exited {rc}; still on v{row['installed_version']}"})
        _update_set (skipped =list (skipped ),instmon_pending =None )
        _update_finish ()
        return 
    # Its --install schedules the restart ~2 s out; still here a while later
    # means it didn't happen.
    time .sleep (45 )
    log_event ("Full Update: instmon was installed but hasn't restarted yet","warn")
    skipped .append ({"name":"instmon","note":f"v{row['repo_version']} installed; takes effect when instmon restarts"})
    _update_set (skipped =list (skipped ),instmon_pending =None )
    _update_finish ()


def update_resume_at_startup ():
    saved =_read_json (UPDATE_STATE_PATH )
    if not saved :
        return 
    with _update_lock :
        for key in _update :
            if key in saved :
                _update [key ]=saved [key ]
        _update ["running"]=False 
    pending =_update .get ("instmon_pending")
    if pending :
        mine =_version_tuple (VERSION )
        if mine and mine ==_version_tuple (pending .get ("to")):
            _update ["updated"].append ({"name":"instmon","note":f"v{pending.get('from')} -> v{VERSION}"})
        else :
            _update ["skipped"].append ({"name":"instmon","note":f"new version didn't take; running v{VERSION}"})
        _update ["instmon_pending"]=None 
        _update_finish ()
    elif saved .get ("phase")not in ("done",""):
        _update_finish ("instmon restarted in the middle of the update")
        if quiet_snapshot ()["on"]:
            quiet_restore ("Full Update interrupted")


def update_dismiss ():
    _update_set (banner =False )
    _update_save ()


BADGE_BY_STATE ={
"active":("RUNNING","b-run"),
"inactive":("STOPPED","b-stop"),
"failed":("FAILED","b-stop"),
"unknown":("UNKNOWN","b-src"),
}


def esc (s ):

    return html .escape (str (s ),quote =True )


def render_components_html (components ):
    cards =[]
    for c in components :
        label ,cls =BADGE_BY_STATE .get (c ["state"],("UNKNOWN","b-src"))
        if c .get ("quiet")and c ["state"]!="active":
            label ,cls ="QUIET","b-quiet"
        if c ["port"]is None :
            port_note ="no web UI"
        else :
            port_note =f'port {c ["port"]}'if c ["listening"]else f'port {c ["port"]} (not listening)'


        uninstall_btn =(
        f'<button data-action="uninstall" data-service="{c ["service"]}" '
        f'data-category="{c ["category"]}" data-name="{esc (c ["name"])}">Uninstall</button>'
        if c ["installed"]else ""
        )
        cards .append (f"""
  <div class="card">
    <div class="row">
      <b>{c ['name']}</b>
      <span class="ver">v{c ['version']}</span>
      <span class="badge {cls }">{label }</span>
      <span class="small" style="color:var(--grn)">{port_note }</span>
      <span class="muted small">{c ['service']}</span>
      <span style="flex:1"></span>
      <button data-action="journal" data-service="{c ['service']}">Journal</button>
      <button data-action="stop" data-service="{c ['service']}" data-name="{esc (c ['name'])}">Stop</button>
      {uninstall_btn }
    </div>
  </div>""")
    return "".join (cards )


def render_library_group_html (title ,category ,entries ,action_label ):
    rows =[]
    for e in entries :


        name =esc (e ["name"])

        if e ["installed"]is True :
            badge ,bcls ="INSTALLED","b-inst"
        elif e ["installed"]is False :
            badge ,bcls ="ALT","b-src"
        else :
            badge ,bcls ="READY","b-inst"


        installer_attr =""
        interactive_only =False 
        if category =="scripts":
            if is_interactive_only_script (e ["name"]):
                interactive_only =True 
                run_label ,run_btn_style ="",""
            elif is_installer_script (e ["name"]):
                run_label ="Install"
                run_btn_style =' style="background:var(--grn);color:#070b10;border-color:var(--grn)"'
                installer_attr =' data-installer="1"'
            else :
                run_label ="Run Script"
                run_btn_style =""
        elif category =="config":
            run_label ,run_btn_style ="Install Config",""
        else :


            run_label ,run_btn_style ="Install",""

        run_btn =(
        '<span class="small muted" title="Menu-driven script -- run by hand over SSH instead">Interactive -- run via SSH</span>'
        if interactive_only else 
        f'<button data-action="{action_label }" data-category="{category }" data-name="{name }"{installer_attr }{run_btn_style }>{run_label }</button>'
        )

        rows .append (f"""
    <div class="librow">
      <div class="librow-top">
        <span class="ver">{esc (e ['version'])}</span>
        <span>{name }</span>
        <span class="badge {bcls }">{badge }</span>
      </div>
      <div class="librow-actions">
        {run_btn }
        <button data-action="edit" data-category="{category }" data-name="{name }">Edit</button>
        <button data-action="download" data-category="{category }" data-name="{name }">Download</button>  <!-- [PHASE 3] -->
        <button class="b-del" data-action="delete" data-category="{category }" data-name="{name }">Delete</button>
      </div>
      <div class="librow-bot small muted">
        <span>Source: library</span>
        <span>&middot;</span>
        <span>{esc (e ['mtime'])}</span>
        <span>&middot;</span>
        <span>{esc (e ['size'])}</span>
      </div>
    </div>""")
    if not rows :
        rows .append ('<div class="small muted" style="padding:.4rem .2rem">-- empty --</div>')
    return f"""
  <div class="card libgrp">
    <div style="margin-bottom:.3rem;color:var(--cyn)"><b>{esc (title )}</b></div>
    {''.join (rows )}
  </div>"""


_LIBRARY_GROUPS: list [tuple [str ,str ,str ]]=[
    ("Dashboard","dashboard","install"),
    ("M17 Dashboard","m17_dashboard","install"),
    ("SysMon","sysmon","install"),
    ("wifimon","wifimon","install"),
    ("44helper","44helper","install"),
    ("SVX Dashboard","svx","install"),
    ("instmon","instmon","install"),
    ("Scripts (.sh)","scripts","run_script"),
    ("Configuration","config","install_config"),
]


def render_library_html (library ):
    return "".join (
    render_library_group_html (title ,category ,library [category ],action_label )
    for title ,category ,action_label in _LIBRARY_GROUPS
    )



_CSS_BASE = """:root{
  /* ── palette matched to asl_dvs_dashboard ── */
  --bg:#0d1117; --surface:#161e2e; --surface2:#1e2a3f;
  --border:#2e4060; --border2:#3a5278;
  --amber:#ffd040; --amber-dim:#6b4800;
  --green:#00ffb0; --green-dim:#005538;
  --red2:#ff3d5a; --red-dim:#6b0e20;
  --blue:#22d4ff; --blue-dim:#083a58;
  --text:#d0dff0; --text-bright:#f0f8ff;
  --mono:'Courier New',Courier,monospace;
  --sans:Arial,Helvetica,sans-serif;
  /* aliases -- kept so existing var(--cyn)/var(--grn)/var(--yel)/var(--red)
     references sprinkled through inline styles and JS-built markup pick
     up the matched palette without every call site needing a rename */
  --panel:var(--surface); --line:var(--border2);
  --fg:var(--text); --muted:#5a7898;
  --cyn:var(--blue); --grn:var(--green); --yel:var(--amber); --red:var(--red2);
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--fg);font-family:var(--sans);
  font-size:.9rem;line-height:1.5;min-height:100vh;padding-bottom:2.5rem}
::-webkit-scrollbar{width:8px;height:8px}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}
"""

_CSS_LAYOUT = """
/* ── Title bar ── */
header{background:linear-gradient(90deg,#0f1a2e,#161e2e 50%,#0f1a2e);
  border-bottom:2px solid var(--amber);padding:.5rem 1rem;
  display:flex;align-items:center;justify-content:space-between;gap:.5rem;
  position:sticky;top:0;z-index:100;
  box-shadow:0 2px 0 rgba(255,208,64,.25),0 6px 30px rgba(0,0,0,.7)}
.hdr-left{display:flex;flex-direction:column;min-width:0}
.hdr-right{display:flex;flex-direction:column;align-items:flex-end;flex-shrink:0;white-space:nowrap}
.logo{font-family:var(--mono);font-size:1.15rem;font-weight:700;color:var(--amber);
  letter-spacing:.08em;text-shadow:0 0 10px rgba(255,208,64,.9),0 0 30px rgba(255,208,64,.5),0 0 60px rgba(255,208,64,.2)}
.logo-sub{font-size:.68rem;letter-spacing:.18em;text-transform:uppercase;color:#5a7898;margin-top:.15rem}
#hdr-version{font-family:var(--mono);font-size:.98rem;font-weight:700;color:var(--amber);
  letter-spacing:.06em;text-shadow:0 0 8px rgba(255,208,64,.5)}
.hdr-meta{font-family:var(--mono);font-size:.68rem;color:#5a7898;letter-spacing:.04em;margin-top:.15rem}

/* ── Layout ── */
.wrap{max-width:860px;margin:0 auto;padding:1rem;display:flex;flex-direction:column;gap:.55rem}
.hdr{color:#5a7898;font-family:var(--mono);font-weight:700;font-size:.7rem;
  letter-spacing:.24em;text-transform:uppercase;margin:1.2rem 0 .45rem;
  padding-bottom:.25rem;border-bottom:1px solid var(--border)}
"""

_CSS_COMPONENTS = """.card{background:var(--surface);border:1px solid var(--border2);border-radius:0 6px 6px 6px;
  padding:.7rem .9rem;margin-bottom:.6rem;box-shadow:0 4px 20px rgba(0,0,0,.35)}
.row{display:flex;flex-wrap:wrap;gap:.4rem .9rem;align-items:center}
.badge{font-family:var(--mono);font-size:.66rem;padding:.08rem .5rem;border-radius:4px;
  border:1px solid;font-weight:700;letter-spacing:.05em;text-transform:uppercase}
.b-inst{color:var(--grn);border-color:var(--green-dim);background:rgba(0,255,176,.07);text-shadow:0 0 8px rgba(0,255,176,.4)}
.b-src{color:var(--muted);border-color:var(--border2)}
.b-run{color:var(--grn);border-color:var(--green-dim);background:rgba(0,255,176,.07);text-shadow:0 0 8px rgba(0,255,176,.4)}
.b-stop{color:var(--red);border-color:var(--red-dim);background:rgba(255,61,90,.08);text-shadow:0 0 8px rgba(255,61,90,.4)}
button{font-family:var(--mono);font-size:.8rem;font-weight:700;letter-spacing:.04em;
  text-transform:uppercase;background:transparent;color:var(--cyn);
  border:1px solid var(--blue-dim);border-radius:4px;padding:.32rem .85rem;cursor:pointer;
  transition:all .14s}
button:hover{filter:brightness(1.5);box-shadow:0 0 10px currentColor}
button:active{transform:scale(.95)}
button.b-del{color:var(--red);border-color:var(--red-dim)}
button:disabled{opacity:.4;cursor:default;filter:none;box-shadow:none}
button.b-danger{color:var(--red);border-color:var(--red2);background:rgba(255,61,90,.1);
  text-shadow:0 0 8px rgba(255,61,90,.5)}
button.b-comms{color:var(--amber);border-color:var(--amber-dim);background:rgba(255,208,64,.08);
  text-shadow:0 0 8px rgba(255,208,64,.4)}
.danger-card{border-color:var(--red-dim)}
.b-quiet{color:var(--yel);border-color:var(--amber-dim);background:rgba(255,208,64,.08)}
/* v1.27.9: Quiet System + Full Update */
.banner{border:1px solid var(--amber-dim);background:rgba(255,208,64,.08);color:var(--yel);
  border-radius:6px;padding:.55rem .8rem;margin-bottom:.6rem;display:flex;flex-wrap:wrap;
  gap:.4rem .9rem;align-items:center;font-family:var(--mono);font-size:.8rem}
.banner.ok{border-color:var(--green-dim);background:rgba(0,255,176,.06);color:var(--grn)}
.banner.err{border-color:var(--red-dim);background:rgba(255,61,90,.08);color:var(--red)}
.banner ul{margin:.2rem 0 0 1.1rem;color:var(--fg)}
.upd-table{width:100%;border-collapse:collapse;margin-top:.5rem;font-size:.78rem}
.upd-table td{padding:.25rem .4rem;border-top:1px solid var(--border)}
.upd-table td.st{font-family:var(--mono);font-weight:700;white-space:nowrap}
.st-update{color:var(--yel)}.st-current{color:var(--grn)}.st-other{color:var(--muted)}
#upd-progress{font-family:var(--mono);font-size:.8rem;color:var(--cyn);margin-top:.4rem}
.muted{color:var(--muted)}
.small{font-size:.74rem}
"""

_CSS_LIBRARY = """.libgrp{margin-bottom:.9rem}
.librow{display:flex;flex-direction:column;gap:.25rem;
  padding:.55rem .7rem;border-bottom:1px solid var(--border);transition:background .1s}
.librow:last-child{border-bottom:none}
.librow:hover{background:var(--surface2)}
.librow-top{display:flex;flex-wrap:wrap;gap:.4rem .9rem;align-items:center}
.librow-actions{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center}
.librow-bot{display:flex;flex-wrap:wrap;gap:.6rem;align-items:center}
.ver{font-family:var(--mono);color:var(--yel);font-weight:700;min-width:5.5rem;text-shadow:0 0 6px rgba(255,208,64,.35)}
input[type=file]{color:var(--muted);font-size:.78rem;max-width:100%}
"""

_CSS_LOG = """#log{background:#070b10;border:1px solid var(--border2);border-radius:0 6px 6px 6px;
  padding:.6rem .8rem;margin-top:.5rem;white-space:pre-wrap;
  font-family:var(--mono);font-size:.78rem;max-height:450px;overflow:auto;display:block;
  box-shadow:0 4px 20px rgba(0,0,0,.35)}
.log-ok{color:var(--grn)}
.log-err{color:var(--red)}
.log-warn{color:var(--yel)}

/* Feedback toasts -- matched to the dashboard's #toast-stack/.toast-item */
#toast-container{
  position:fixed; bottom:1.5rem; right:1.2rem; z-index:1200;
  display:flex; flex-direction:column; gap:.45rem; max-width:92vw;
}
.toast{
  background:#1a2438; border:1px solid var(--border2); border-radius:8px;
  padding:.7rem 1.2rem; font-family:var(--mono); font-size:.88rem; line-height:1.4;
  color:var(--text-bright); box-shadow:0 8px 40px rgba(0,0,0,.8);
  opacity:0; transform:translateX(2rem); transition:opacity .2s ease, transform .2s ease;
}
.toast-show{opacity:1; transform:translateX(0)}
.toast-ok{border-color:var(--green-dim); color:var(--grn); box-shadow:0 0 20px rgba(0,255,176,.2)}
.toast-warn{border-color:var(--amber-dim); color:var(--yel); box-shadow:0 0 20px rgba(255,208,64,.2)}
.toast-err{border-color:var(--red-dim); color:var(--red); box-shadow:0 0 20px rgba(255,61,90,.2)}
.toast-info{border-color:var(--blue-dim); color:var(--cyn); box-shadow:0 0 20px rgba(34,212,255,.2)}

"""

_CSS_EDITOR = """/* Editor Overlay (Stage 8/9, Library Card Rework Plan) -- replaces
   the old centered-dialog editor pattern with sysmon's full-screen
   uf-overlay/uf-box shape (confirmed by reading
   sysmon_v6_2_3_20260808.py: #uf-overlay/#uf-box/#uf-hdr/#uf-toolbar/
   #uf-textarea). Adapted, not copied verbatim:
     - var(--teal) -> var(--cyn) throughout; instmon doesn't define
       --teal, and --cyn is already this file's accent color for the
       old editor's header text, so this keeps the same visual role
       instmon already had rather than introducing a new color.
     - No #uf-promoted-bar and no Restart/Reload-Daemon buttons --
       those are unit-file-specific concepts (systemd override paths,
       daemon-reload) that don't apply to instmon's generic
       library-file editor.
     - Dropped sysmon's position:sticky + compensating 3.5rem
       textarea top-padding on #uf-hdr/#uf-toolbar: that combination
       exists in sysmon because its editor is reused in several
       scroll contexts; instmon's #uf-box is a plain flex column
       (header, toolbar, then a flex:1 textarea) where the header and
       toolbar are already pinned above the one scrollable child by
       the flex layout itself, so sticky positioning has nothing to
       do and the padding hack it was compensating for isn't needed
       either.
*/
#uf-overlay {
  display:none; position:fixed; inset:0;
  background:rgba(0,0,0,.8); backdrop-filter:blur(4px);
  z-index:500; align-items:center; justify-content:center; padding:0;
}
#uf-overlay.open { display:flex; }
#uf-box {
  background:var(--surface); border:1px solid var(--border2);
  border-radius:0; width:100vw; height:100vh; max-width:none;
  height:100dvh; max-height:100dvh;
  display:flex; flex-direction:column; box-shadow:none;
}
#uf-hdr {
  background:linear-gradient(90deg,#0f1a2e,#161e2e 50%,#0f1a2e);
  border-bottom:2px solid var(--cyn); padding:.55rem 1rem;
  display:flex; align-items:center; justify-content:space-between;
  flex-shrink:0; box-shadow:0 2px 0 rgba(34,212,255,.15);
}
#uf-title {
  font-family:var(--mono); font-size:.858rem;
  color:var(--cyn); letter-spacing:.08em;
  text-shadow:0 0 8px rgba(34,212,255,.4);
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}
#uf-hdr-right { display:flex; align-items:center; gap:.4rem; flex-shrink:0; }
#uf-close {
  font-family:var(--mono); font-size:.858rem; color:var(--fg);
  cursor:pointer; padding:.15rem .55rem; border:1px solid var(--border2);
  border-radius:3px; transition:all .14s;
}
#uf-close:hover { color:var(--red); border-color:var(--red-dim); }
#uf-toolbar {
  display:flex; align-items:center; gap:.4rem;
  padding:.38rem 1rem; background:#131c2d;
  border-bottom:1px solid var(--border); flex-shrink:0;
}
#uf-path {
  font-family:var(--mono); font-size:.715rem; color:var(--fg);
  flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}
#uf-status { font-family:var(--mono); font-size:.77rem; color:var(--fg); flex-shrink:0; }
#uf-textarea {
  flex:1; background:#0a1020; color:#c8d8e8;
  font-family:var(--mono); font-size:.836rem; line-height:1.65;
  border:none; outline:none; padding:.8rem 1rem;
  resize:none; tab-size:4; white-space:pre; overflow:auto; min-height:0;
}
#uf-textarea::-webkit-scrollbar { width:4px; height:4px; }
#uf-textarea::-webkit-scrollbar-thumb { background:var(--border2); border-radius:2px; }
"""

_CSS = (
    _CSS_BASE
    + _CSS_LAYOUT
    + _CSS_COMPONENTS
    + _CSS_LIBRARY
    + _CSS_LOG
    + _CSS_EDITOR
)



_JS_LOG_POLL = """let lastLogId = 0;
const MAX_CLIENT_LOG_LINES = 500;

function logLine(entry) {
  const el = document.getElementById('log');
  const cls = entry.level === 'ok' ? 'log-ok' : entry.level === 'err' ? 'log-err' : entry.level === 'warn' ? 'log-warn' : '';
  const span = document.createElement('div');
  if (cls) span.className = cls;
  span.textContent = `[${entry.ts}] ${entry.msg}`;
  el.appendChild(span);
  // Mirror the server's LOG_MAX_LINES cap on the client side too --
  // otherwise a long-running open tab appends log lines to the DOM
  // forever (server-side history is capped, but the browser never
  // was), and the tab eventually bogs down and needs a reload.
  while (el.childNodes.length > MAX_CLIENT_LOG_LINES) {
    el.removeChild(el.firstChild);
  }
  el.scrollTop = el.scrollHeight;
  lastLogId = entry.id;
}

async function pollLog() {
  try {
    const r = await fetch(`/api/log?since=${lastLogId}`);
    const data = await r.json();
    for (const entry of data.entries) logLine(entry);
  } catch (e) { /* server restarting or unreachable, ignore this tick */ }
}

"""

_JS_STATUS_TOAST = """async function refreshStatus() {
  try {
    const r = await fetch('/api/status');
    const data = await r.json();
    document.getElementById('components').innerHTML = data.components_html;
    document.getElementById('library').innerHTML = data.library_html;
    renderQuietUpdate(data.quiet, data.update);
    wireButtons();
  } catch (e) { /* ignore this tick */ }
}

// v1.27.9: Quiet System + Full Update
let _quietState = null;
let _updateState = null;
let _updateWasRunning = null;

function _esc(t) {
  return String(t == null ? '' : t).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}

const _UPD_STATUS = {
  update: ['UPDATE', 'st-update'], current: ['CURRENT', 'st-current'], not_installed: ['NOT INSTALLED', 'st-other'],
  not_in_repo: ['NOT ON GITHUB', 'st-other'], newer_installed: ['NEWER HERE', 'st-other'], unknown: ['UNKNOWN', 'st-other'],
  new: ['NEW', 'st-update'], in_library: ['IN LIBRARY', 'st-current'],
};

function renderCheck(check) {
  const box = document.getElementById('upd-results');
  if (!box) return;
  if (!check) { box.innerHTML = ''; return; }
  const rows = check.components.map(c => {
    const [lbl, cls] = _UPD_STATUS[c.status] || [c.status, 'st-other'];
    return `<tr><td>${_esc(c.name)}</td><td class="st ${cls}">${lbl}</td><td>${_esc(c.note)}</td><td class="muted">${_esc(c.repo_file)}</td></tr>`;
  }).concat(check.scripts.map(sc => {
    const [lbl, cls] = _UPD_STATUS[sc.status] || [sc.status, 'st-other'];
    return `<tr><td>Script</td><td class="st ${cls}">${lbl}</td><td>${sc.status === 'new' ? 'goes to the library (not run)' : ''}</td><td class="muted">${_esc(sc.name)}</td></tr>`;
  }));
  box.innerHTML = `<table class="upd-table">${rows.join('')}</table>`;
}

function _resultList(title, items) {
  if (!items || !items.length) return '';
  return `<div><b>${title}</b><ul>${items.map(r => `<li>${_esc(r.name)}: ${_esc(r.note)}</li>`).join('')}</ul></div>`;
}

function renderQuietUpdate(quiet, upd) {
  _quietState = quiet; _updateState = upd;
  const running = !!(upd && upd.running);
  const banners = [];
  if (quiet && quiet.on) {
    banners.push(`<div class="banner"><span>System quiet since ${_esc(quiet.since_text)} (${_esc(quiet.reason)}):
      ${quiet.stopped.length ? _esc(quiet.stopped.join(', ')) + ' stopped' : 'nothing was running'}.
      Auto-restore after ${quiet.auto_restore_min} min.</span>
      ${running ? '' : '<button data-action="restore">Restore</button>'}</div>`);
  }
  if (upd && upd.banner && !running) {
    const bad = (upd.attention || []).length || upd.error;
    const cls = bad ? 'err' : ((upd.skipped || []).length ? '' : 'ok');
    banners.push(`<div class="banner ${cls}"><div style="flex:1">
      <b>Full Update finished${upd.error ? ' -- ' + _esc(upd.error) : ''}</b>
      ${_resultList('Updated', upd.updated)}${_resultList('Skipped', upd.skipped)}
      ${_resultList('NEEDS ATTENTION', upd.attention)}${_resultList('Scripts', upd.scripts)}
      ${(upd.updated || []).length + (upd.skipped || []).length + (upd.attention || []).length + (upd.scripts || []).length ? '' : '<div>Nothing needed updating.</div>'}
      </div><button data-action="update_dismiss">Dismiss</button></div>`);
  }
  const bEl = document.getElementById('banners');
  if (bEl) bEl.innerHTML = banners.join('');

  const prog = document.getElementById('upd-progress');
  if (prog) prog.textContent = running ? `Full Update running: ${upd.phase}${upd.current ? ' -- ' + upd.current : ''}` : '';
  const meta = document.getElementById('upd-meta');
  if (meta && upd && upd.check_at) {
    const c = upd.check;
    meta.textContent = `Checked ${upd.check_at}: ${c.updates} component update(s), ${c.new_scripts} new script(s).`;
  }
  renderCheck(upd && upd.check);

  const fu = document.getElementById('full-update-btn');
  if (fu) fu.disabled = running || !(upd && upd.check && (upd.check.updates || upd.check.new_scripts));
  const qb = document.getElementById('quiet-btn');
  if (qb) qb.disabled = running || !!(quiet && quiet.on);
  const rb = document.getElementById('restore-btn');
  if (rb) rb.disabled = running || !(quiet && quiet.on);
  document.querySelectorAll('#components button, #library button, #upbtn').forEach(b => {
    if (b.dataset.action !== 'journal') b.disabled = running;
  });

  if (_updateWasRunning === true && !running && upd && upd.phase === 'done') {
    const n = (upd.updated || []).length, sk = (upd.skipped || []).length, at = (upd.attention || []).length;
    showToast(`Full Update finished: ${n} updated, ${sk} skipped${at ? ', ' + at + ' NEED ATTENTION' : ''}.`, at ? 'err' : (sk ? 'warn' : 'ok'));
  }
  _updateWasRunning = running;
}

function showToast(message, level) {
  if (!message) return;
  const cls = {ok: 'toast-ok', warn: 'toast-warn', err: 'toast-err', info: 'toast-info'}[level] || 'toast-info';
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${cls}`;
  toast.textContent = message;
  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add('toast-show'));
  const dismissAfter = level === 'err' ? 7000 : 4000;
  setTimeout(() => {
    toast.classList.remove('toast-show');
    setTimeout(() => toast.remove(), 300);
  }, dismissAfter);
}

async function postAction(body) {
  const r = await fetch('/api/action', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  let data = {};
  try { data = await r.json(); } catch (e) {}
  const level = data.level || (r.ok ? 'ok' : 'err');
  const message = data.message || data.error || (r.ok ? 'Done.' : `Request failed (${r.status})`);
  showToast(message, level);
  if (!r.ok) {
    const msg = document.getElementById('upmsg');
    if (msg) msg.textContent = data.error || `Request failed (${r.status})`;
  }
  return data;
}

"""

_JS_EDITOR = """// Editor functions
// Editor overlay JS (Stage 8/9, Library Card Rework Plan). _editCategory
// and _editName track which library file is open, since uf-overlay's
// buttons (onclick="ufSave()" etc.) don't carry that context on their
// own the way the old per-open closures did.
let _editCategory = '';
let _editName = '';

function ufSetStatus(msg, ok) {
  const el = document.getElementById('uf-status');
  if (!el) return;
  el.textContent = msg || '';
  el.style.color = ok === true ? 'var(--grn)' : ok === false ? 'var(--red)' : 'var(--fg)';
}

function closeEditor() {
  document.getElementById('uf-overlay').classList.remove('open');
  _editCategory = '';
  _editName = '';
}

function ufOverlayClick(e) {
  if (e.target === document.getElementById('uf-overlay')) closeEditor();
}

async function ufCopy() {
  // Mirrors sysmon's _copyWithVerify(): try the async Clipboard API
  // first, fall back to a hidden-textarea execCommand('copy') for
  // browsers/contexts that block navigator.clipboard, then read the
  // clipboard back to confirm the write actually landed in full --
  // some mobile browsers silently truncate large clipboard writes.
  const ta = document.getElementById('uf-textarea');
  if (!ta || !ta.value) { showToast('Nothing to copy', 'err'); return; }
  let wrote = false;
  try {
    await navigator.clipboard.writeText(ta.value);
    wrote = true;
  } catch (e) {
    const tmp = document.createElement('textarea');
    tmp.value = ta.value;
    tmp.style.position = 'fixed';
    tmp.style.left = '-9999px';
    tmp.setAttribute('readonly', '');
    document.body.appendChild(tmp);
    tmp.focus();
    tmp.setSelectionRange(0, tmp.value.length);
    try { document.execCommand('copy'); wrote = true; } catch (e2) { wrote = false; }
    document.body.removeChild(tmp);
  }
  if (!wrote) { showToast('Copy failed', 'err'); return; }
  try {
    const check = await navigator.clipboard.readText();
    if (check === ta.value) {
      showToast('Copied', 'ok');
    } else {
      showToast(`Copy may be incomplete (${check.length} of ${ta.value.length} characters) -- try again, or use a desktop browser if this persists.`, 'warn');
    }
  } catch (e) {
    // Clipboard readText() isn't available/permitted everywhere the
    // write above just succeeded on (notably some mobile browsers) --
    // that's not a failure, just an unconfirmed success.
    showToast('Copied -- could not confirm on this browser', 'info');
  }
}

async function ufSave() {
  if (!_editName) return;
  const newContent = document.getElementById('uf-textarea').value;
  const btn = document.getElementById('uf-save-btn');
  if (btn) btn.disabled = true;
  ufSetStatus('Saving...');
  try {
    const saveRes = await fetch('/api/file', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({file: _editName, category: _editCategory, content: newContent})
    });
    const saveData = await saveRes.json();
    if (!saveRes.ok) {
      ufSetStatus(`Save failed: ${saveData.error || saveRes.status}`, false);
      return;
    }
    ufSetStatus(`Saved (${saveData.reason})`, true);
    await refreshStatus();
    setTimeout(closeEditor, 900);
  } catch (e) {
    ufSetStatus('Save error: ' + e.message, false);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function openEditor(category, name) {
  _editCategory = category;
  _editName = name;
  document.getElementById('uf-title').textContent = `Edit: ${name}`;
  document.getElementById('uf-path').textContent = `${category}/${name}`;
  document.getElementById('uf-textarea').value = '';
  ufSetStatus('Loading...');
  document.getElementById('uf-overlay').classList.add('open');

  try {
    const r = await fetch(`/api/file?file=${encodeURIComponent(name)}&category=${encodeURIComponent(category)}`);
    if (!r.ok) {
      const data = await r.json();
      ufSetStatus(`Failed to load: ${data.error || r.status}`, false);
      return;
    }
    const text = await r.text();
    document.getElementById('uf-textarea').value = text;
    ufSetStatus('');
  } catch (e) {
    ufSetStatus('Error: ' + e.message, false);
  }
}

"""

_JS_ACTIONS = """function wireButtons() {
  document.querySelectorAll('button[data-action]').forEach(btn => {
    if (btn._wired) return;
    btn._wired = true;
    btn.addEventListener('click', async () => {
      const action = btn.dataset.action;
      btn.disabled = true;
      try {
        if (action === 'journal') {
          await postAction({action: 'journal', service: btn.dataset.service});
        } else if (action === 'install') {
          if (!confirm(`Install ${btn.dataset.name}? This will restart its service.`)) { btn.disabled = false; return; }
          await postAction({action: 'install', category: btn.dataset.category, name: btn.dataset.name});
        } else if (action === 'uninstall') {
          if (!confirm(`Uninstall ${btn.dataset.name}? This stops and removes the service entirely (unit, symlink, and installed files). This cannot be undone from here -- you'll need to Install it again afterward.`)) { btn.disabled = false; return; }
          await postAction({action: 'uninstall', category: btn.dataset.category});
        } else if (action === 'stop') {
          if (!confirm(`Stop ${btn.dataset.name}? The service will stop responding until it's started again.`)) { btn.disabled = false; return; }
          await postAction({action: 'stop', service: btn.dataset.service});
        } else if (action === 'install_config') {
          if (!confirm(`Install ${btn.dataset.name} as the active config? This will restart whichever is installed, Dashboard or M17 Dashboard.`)) { btn.disabled = false; return; }
          await postAction({action: 'install_config', name: btn.dataset.name});
        } else if (action === 'run_script') {
          if (btn.dataset.installer === '1') {
            // Full-stack shell installer: same confirm bar as the
            // per-component Install/Reinstall buttons, since it can
            // restart both the Dashboard and SysMon services.
            if (!confirm(`Run ${btn.dataset.name}? This installs/updates the Dashboard and SysMon services and may restart them. Runs non-interactively -- no terminal prompts.`)) { btn.disabled = false; return; }
            // Only needed for a bare node with no existing config and
            // no legacy dvswitch.conf to migrate -- leave blank for
            // an update or a migratable config and the script won't
            // touch them. Cancelling either prompt aborts the whole
            // run; leaving a prompt blank just omits that one var.
            const callsign = prompt('Callsign for first-run setup (leave blank if not needed):', '');
            if (callsign === null) { btn.disabled = false; return; }
            const node = prompt('Node number for first-run setup (leave blank if not needed):', '');
            if (node === null) { btn.disabled = false; return; }
            const body = {action: 'run_script', name: btn.dataset.name};
            if (callsign.trim()) body.auto_callsign = callsign.trim();
            if (node.trim()) body.auto_node = node.trim();
            await postAction(body);
          } else {
            await postAction({action: 'run_script', name: btn.dataset.name});
          }
        } else if (action === 'edit') {
          await openEditor(btn.dataset.category, btn.dataset.name);
        } else if (action === 'download') {  // [PHASE 3]
          window.location.href = '/api/download?file=' + encodeURIComponent(btn.dataset.name) + '&category=' + encodeURIComponent(btn.dataset.category);
        } else if (action === 'delete') {
          if (!confirm(`Delete ${btn.dataset.name} from the library?`)) { btn.disabled = false; return; }
          await postAction({action: 'delete', category: btn.dataset.category, name: btn.dataset.name});
        } else if (action === 'save_alternate') {
          await postAction({action: 'save_alternate'});
        } else if (action === 'comms_restart') {
          if (!confirm('Stop Asterisk, Analog_Bridge, MMDVM_Bridge, STFU, and Allmon3, pause 3s, then start them back up? All active calls/links on this node will drop for the duration.')) { btn.disabled = false; return; }
          await postAction({action: 'comms_restart'});
        } else if (action === 'quiet') {
          if (!confirm('Quiet the system? Stops SysMon, Dashboard, M17 Dashboard, SVX Dashboard, 44helper and the watchdog timer (whichever are running) until you press Restore -- auto-restore after 30 min. Radio, Asterisk, Allmon3, SSH and Wi-Fi stay up.')) { btn.disabled = false; return; }
          await postAction({action: 'quiet'});
        } else if (action === 'restore') {
          await postAction({action: 'restore'});
        } else if (action === 'check_updates') {
          showToast('Checking GitHub...', 'info');
          await postAction({action: 'check_updates'});
        } else if (action === 'update_dismiss') {
          await postAction({action: 'update_dismiss'});
        } else if (action === 'full_update') {
          const c = _updateState && _updateState.check;
          const list = c ? c.components.filter(x => x.status === 'update').map(x => `  ${x.name}: ${x.note}`) : [];
          const sc = c ? c.scripts.filter(x => x.status === 'new').map(x => `  ${x.name} (library only, not run)`) : [];
          if (!confirm('Full Update from GitHub?\\n\\n' + (list.length ? 'Components, one at a time:\\n' + list.join('\\n') + '\\n\\n' : '') +
                       (sc.length ? 'New scripts:\\n' + sc.join('\\n') + '\\n\\n' : '') +
                       'The system is quieted first and restored at the end. Each component is uninstalled, then the new version installed; one that fails is rolled back and skipped. instmon goes last and this page reconnects after it restarts.')) { btn.disabled = false; return; }
          await postAction({action: 'full_update'});
        } else if (action === 'reboot') {
          if (!confirm('Reboot this Pi? Every service on it -- including this instmon page -- goes unreachable until it finishes booting back up.')) { btn.disabled = false; return; }
          if (!confirm('Really sure? This is a full node reboot, not just instmon.')) { btn.disabled = false; return; }
          await postAction({action: 'reboot'});
        } else if (action === 'shutdown') {
          if (!confirm('Shut down this Pi? It will power off and stay off until someone power-cycles it in person (or via a smart PDU).')) { btn.disabled = false; return; }
          if (!confirm('Really sure? There is no remote way to turn it back on from this page once it powers off.')) { btn.disabled = false; return; }
          await postAction({action: 'shutdown'});
        }
        await refreshStatus();
      } finally {
        btn.disabled = false;
      }
    });
  });
  const saveBtn = document.getElementById('save-alt-btn');
  if (saveBtn && !saveBtn._wired) {
    saveBtn._wired = true;
    saveBtn.addEventListener('click', async () => {
      saveBtn.disabled = true;
      await postAction({action: 'save_alternate'});
      await refreshStatus();
      saveBtn.disabled = false;
    });
  }
}

"""

_JS_INIT = """document.getElementById('upbtn').addEventListener('click', async () => {
  const fileInput = document.getElementById('file');
  const cat = document.getElementById('upcat').value;
  const msg = document.getElementById('upmsg');
  if (!fileInput.files.length) { msg.textContent = 'Choose a file first.'; return; }

  async function doUpload(force) {
    const fd = new FormData();
    fd.append('category', cat);
    fd.append('file', fileInput.files[0]);
    if (force) fd.append('force', '1');
    const r = await fetch('/api/upload', {method: 'POST', body: fd});
    const data = await r.json();
    return {r, data};
  }

  msg.textContent = 'Uploading...';
  try {
    let {r, data} = await doUpload(false);
    if (!r.ok && data.mismatch) {
      const proceed = confirm(
        (data.error || 'Filename does not match this category.') +
        '\\n\\nUpload anyway?'
      );
      if (proceed) {
        ({r, data} = await doUpload(true));
      } else {
        msg.textContent = 'Upload cancelled.';
        return;
      }
    }
    msg.textContent = r.ok ? `Staged: ${data.name}` : (data.error || 'Upload failed');
    showToast(data.message || data.error || (r.ok ? 'Uploaded.' : 'Upload failed'), data.level || (r.ok ? 'ok' : 'err'));
    if (r.ok) { fileInput.value = ''; await refreshStatus(); }
  } catch (e) {
    msg.textContent = 'Upload failed: ' + e;
  }
});

// [PHASE 3] Backup button
document.getElementById('backup-btn').addEventListener('click', function() {
  window.location.href = '/api/backup';
});

wireButtons();
// Skip poll ticks while the tab isn't visible -- no point hitting
// the server every 2s/5s for a background tab, especially on the
// travel node where bandwidth/battery can be tight. Catches up
// immediately with one poll of each as soon as the tab becomes
// visible again, rather than waiting out the rest of the interval.
setInterval(() => { if (!document.hidden) pollLog(); }, 2000);
setInterval(() => { if (!document.hidden) refreshStatus(); }, 5000);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) { pollLog(); refreshStatus(); }
});
pollLog();
refreshStatus();
"""

_JS = (
    _JS_LOG_POLL
    + _JS_STATUS_TOAST
    + _JS_EDITOR
    + _JS_ACTIONS
    + _JS_INIT
)


def render_page ():
    status =build_status ()
    components_html =render_components_html (status ["components"])
    library_html =render_library_html (status ["library"])
    log_html ="-- System ready --\n"+f"instmon v{VERSION } ({DATE_STR }) backend online, {len (status ['components'])} component(s) tracked."
    return HTML_TEMPLATE .format (
    version =VERSION ,
    date =DATE_STR ,
    port =PORT ,
    css =_CSS ,
    script =_JS ,
    components_html =components_html ,
    library_html =library_html ,
    log_html =log_html ,
    )


HTML_TEMPLATE ="""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ASL-DVS Install Monitor &mdash; instmon</title>
<style>
{css}</style>
</head>
<body>
<header>
  <div class="hdr-left">
    <div class="logo">ASL-DVS Install Monitor</div>
    <div class="logo-sub">Node Software Installer &amp; Component Manager</div>
  </div>
  <div class="hdr-right">
    <span id="hdr-version">v{version}</span>
    <span class="hdr-meta">{date} &middot; port {port}</span>
  </div>
</header>
<div class="wrap">

<div id="banners"></div>

<div class="hdr">Components</div>
<div id="components">{components_html}
</div>

<div class="hdr">Updates</div>
<div class="card">
  <div class="row">
    <button data-action="check_updates">Check for updates</button>
    <button class="b-comms" id="full-update-btn" data-action="full_update" disabled>Full Update</button>
    <span class="small muted" id="upd-meta">Compares installed components with github.com/kd8pgk/ASL-DVS.</span>
  </div>
  <div class="small muted" style="margin-top:.35rem">
    Full Update: quiets the system, downloads and checks every newer file, then uninstalls the old and installs the new
    one component at a time (instmon last). A component that fails is rolled back, skipped and listed at the end.
    New install scripts go to the library's Scripts section -- they are never run for you.</div>
  <div id="upd-progress"></div>
  <div id="upd-results"></div>
</div>

<div class="hdr">Version Library &amp; Scripts Hub</div>
<div class="small muted" style="margin-bottom:.4rem">
  Install any listed version, run shell scripts, or manage alternative configuration files.</div>
<div id="library">{library_html}
</div>

<div class="hdr">Upload</div>
<div class="card">
  <div class="row">
    <select id="upcat">
      <option value="dashboard">Dashboard (.py)</option>
      <option value="m17_dashboard">M17 Dashboard (.py)</option>
      <option value="sysmon">SysMon (.py)</option>
      <option value="wifimon">wifimon (.py)</option>
      <option value="44helper">44helper (.py)</option>
      <option value="svx">SVX Dashboard (.py)</option>
      <option value="instmon">instmon (.py)</option>
      <option value="scripts">Script (.sh)</option>
      <option value="config">Config (.conf)</option>
    </select>
    <input type="file" id="file">
    <button id="upbtn">Upload &amp; stage</button>
  </div>
  <div class="small muted" style="margin-top:.35rem">
    Accepts a component .py, an install/utility .sh script, or a .conf file matching the category selected above.</div>
  <div id="upmsg" class="small" style="margin-top:.35rem"></div>
  <div class="row" style="margin-top:.6rem">
    <button class="b-comms" id="quiet-btn" data-action="quiet">Quiet System</button>
    <button id="restore-btn" data-action="restore" disabled>Restore</button>
    <span class="small muted">Before a big upload or install on a small Pi: stops SysMon, the dashboards, 44helper and the
    watchdog timer. Radio, Asterisk, Allmon3, SSH and Wi-Fi stay up.</span>
  </div>
</div>

<div class="hdr">Backup &amp; Export</div>  <!-- [PHASE 3] -->
<div class="card">
  <div class="row">
    <button id="backup-btn" style="background:var(--grn);color:#070b10;border-color:var(--grn)">Download Full Backup (ZIP)</button>
    <span class="small muted">Archive all files in the library directory.</span>
  </div>
</div>

<div class="hdr">System &amp; Comms</div>
<div class="card danger-card">
  <div class="row">
    <button class="b-comms" data-action="comms_restart">Comms SERV Restart</button>
    <span class="small muted">Full stop, 3s pause, then start: Asterisk, Analog_Bridge, MMDVM_Bridge, STFU, Allmon3.</span>
  </div>
  <div class="row" style="margin-top:.5rem">
    <button class="b-danger" data-action="reboot">Reboot Pi</button>
    <button class="b-danger" data-action="shutdown">Shutdown Pi</button>
    <span class="small muted">Affects the whole node, not just instmon -- this page (and every other service on it) goes unreachable until it's back up. Shutdown needs physical/console access (or a smart PDU) to power back on.</span>
  </div>
</div>

<div class="hdr">Execution Log</div>
<div id="log">{log_html}</div>

</div>

<div id="toast-container"></div>

<!-- Editor Overlay (Stage 8/9, Library Card Rework Plan) -- replaces
     the old centered-dialog editor with the full-screen uf-overlay/
     uf-box pattern; see the CSS block above for what was adapted vs.
     dropped from sysmon's version. -->
<div id="uf-overlay" onclick="ufOverlayClick(event)">
  <div id="uf-box">
    <div id="uf-hdr">
      <span id="uf-title">Edit</span>
      <div id="uf-hdr-right">
        <button id="uf-save-btn" style="background:var(--cyn);color:#070b10;border-color:var(--cyn)" onclick="ufSave()">Save</button>
        <button id="uf-copy-btn" onclick="ufCopy()">&#9111; Copy</button>
        <span id="uf-close" onclick="closeEditor()">&times;</span>
      </div>
    </div>
    <div id="uf-toolbar">
      <span id="uf-path">&mdash;</span>
      <span id="uf-status"></span>
    </div>
    <textarea id="uf-textarea" spellcheck="false"></textarea>
  </div>
</div>

<script>
{script}</script>
</body>
</html>
"""


_ACTION_HANDLERS ={
"install":lambda self ,body :self ._action_install (body ),
"uninstall":lambda self ,body :self ._action_uninstall (body ),
"stop":lambda self ,body :self ._action_stop (body ),
"install_config":lambda self ,body :self ._action_install_config (body ),
"delete":lambda self ,body :self ._action_delete (body ),
"run_script":lambda self ,body :self ._action_run_script (body ),
"save_alternate":lambda self ,body :self ._action_save_alternate (),
"journal":lambda self ,body :self ._action_journal (body ),
"comms_restart":lambda self ,body :self ._action_comms_restart (body ),
"reboot":lambda self ,body :self ._action_reboot (body ),
"shutdown":lambda self ,body :self ._action_shutdown (body ),
"quiet":lambda self ,body :self ._action_quiet (body ),
"restore":lambda self ,body :self ._action_restore (body ),
"check_updates":lambda self ,body :self ._action_check_updates (body ),
"full_update":lambda self ,body :self ._action_full_update (body ),
"update_dismiss":lambda self ,body :self ._action_update_dismiss (body ),
}

# Read-only actions still allowed while Full Update runs.
_ACTIONS_DURING_UPDATE ={"journal","update_dismiss"}


_GET_ROUTES ={
"/":lambda self :self ._route_index (),
"/index.html":lambda self :self ._route_index (),
"/api/status":lambda self :self ._route_status (),
"/api/log":lambda self :self ._route_log (),
"/api/file":lambda self :self ._route_file (),
"/api/download":lambda self :self .handle_download (),
"/api/backup":lambda self :self .handle_backup (),
}

_POST_ROUTES ={
"/api/upload":lambda self :self .handle_upload (),
"/api/action":lambda self :self .handle_action (),
"/api/file":lambda self :self .handle_file_write (),
}


class InstmonHandler (http .server .BaseHTTPRequestHandler ):
    server_version =f"instmon/{VERSION }"


    def _send_json (self ,status ,payload ):
        body =json .dumps (payload ).encode ("utf-8")
        self .send_response (status )
        self .send_header ("Content-Type","application/json; charset=utf-8")
        self .send_header ("Content-Length",str (len (body )))
        self .end_headers ()
        self .wfile .write (body )

    def _send_html (self ,status ,html ):
        body =html .encode ("utf-8")
        self .send_response (status )
        self .send_header ("Content-Type","text/html; charset=utf-8")
        self .send_header ("Content-Length",str (len (body )))
        self .end_headers ()
        self .wfile .write (body )

    def _error_json (self ,status ,message ):
        log_event (f"HTTP {status }: {message } ({self .command } {self .path })","err")
        self ._send_json (status ,{"error":message })

    def _check_auth (self ):

        if not AUTH_ENABLED :
            return True 
        header =self .headers .get ("Authorization","")
        if not header .startswith ("Basic "):
            return False 
        try :
            decoded =base64 .b64decode (header [6 :]).decode ("utf-8",errors ="replace")
        except (ValueError ,UnicodeDecodeError ):
            return False 
        user ,_ ,pw =decoded .partition (":")
        return hmac .compare_digest (user ,AUTH_USER )and hmac .compare_digest (pw ,AUTH_PASS )

    def _require_auth (self ):
        body =b"Authorization required"
        self .send_response (401 )
        self .send_header ("WWW-Authenticate",'Basic realm="instmon"')
        self .send_header ("Content-Type","text/plain; charset=utf-8")
        self .send_header ("Content-Length",str (len (body )))
        self .end_headers ()
        self .wfile .write (body )


    def _update_busy (self ):
        if not update_running ():
            return False 
        self ._send_json (409 ,{
        "error":"Full Update is running",
        "message":"Full Update is running -- wait for it to finish.",
        "level":"warn",
        })
        return True 


    def _find_library_file (self ,filename ,category =None ):
        if category and category in LIB_SUBDIRS :
            candidate =safe_join (LIB_SUBDIRS [category ],filename )
            return candidate if candidate and os .path .isfile (candidate )else None 
        for dir_path in LIB_SUBDIRS .values ():
            candidate =safe_join (dir_path ,filename )
            if candidate and os .path .isfile (candidate ):
                return candidate 
        return None 


    def _route_index (self ):
        self ._send_html (200 ,render_page ())

    def _route_status (self ):
        status =build_status ()
        self ._send_json (200 ,{
        "components_html":render_components_html (status ["components"]),
        "library_html":render_library_html (status ["library"]),
        "quiet":status ["quiet"],
        "update":status ["update"],
        })

    def _route_log (self ):
        since =0 
        if "?"in self .path :
            m =re .search (r"since=(\d+)",self .path )
            if m :
                since =int (m .group (1 ))
        with _log_lock :
            entries =[e for e in _log if e ["id"]>since ]
        self ._send_json (200 ,{"entries":entries })

    def _route_file (self ):
        query =urllib .parse .parse_qs (urllib .parse .urlparse (self .path ).query )
        file_names =query .get ("file",[])
        if not file_names :
            self ._error_json (400 ,"Missing 'file' parameter")
            return 
        filename =file_names [0 ]
        category =query .get ("category",[None ])[0 ]
        target =self ._find_library_file (filename ,category )
        if target is None :
            self ._error_json (404 ,f"File '{filename }' not found in library")
            return 
        try :
            with open (target ,"r",encoding ="utf-8")as f :
                content =f .read ()
            self .send_response (200 )
            self .send_header ("Content-Type","text/plain; charset=utf-8")
            self .send_header ("Content-Length",str (len (content .encode ("utf-8"))))
            self .end_headers ()
            self .wfile .write (content .encode ("utf-8"))
        except Exception as exc :
            self ._error_json (500 ,f"Error reading file: {exc }")

    def do_GET (self ):
        if not self ._check_auth ():
            self ._require_auth ()
            return 
        parsed_path =self .path .split ("?",1 )[0 ]
        handler_fn =_GET_ROUTES .get (parsed_path )
        if handler_fn is None :
            self ._error_json (404 ,"Not found")
            return 
        handler_fn (self )


    def do_POST (self ):
        if not self ._check_auth ():
            self ._require_auth ()
            return 
        handler_fn =_POST_ROUTES .get (self .path )
        if handler_fn is None :
            self ._error_json (404 ,"Not found")
            return 
        handler_fn (self )


    def handle_download (self ):
        query =urllib .parse .parse_qs (urllib .parse .urlparse (self .path ).query )
        file_names =query .get ("file",[])
        if not file_names :
            self ._error_json (400 ,"Missing 'file' parameter")
            return 
        filename =file_names [0 ]
        category =query .get ("category",[None ])[0 ]
        target =self ._find_library_file (filename ,category )
        if target is None :
            self ._error_json (404 ,f"File '{filename }' not found in library")
            return 
        try :
            self .send_response (200 )
            ext =os .path .splitext (filename )[1 ].lower ()
            ctype ="application/octet-stream"
            if ext ==".py":
                ctype ="text/x-python"
            elif ext ==".sh":
                ctype ="text/x-sh"
            elif ext ==".conf":
                ctype ="text/plain"
            self .send_header ("Content-Type",ctype )
            self .send_header ("Content-Disposition",f"attachment; filename=\"{filename }\"")
            self .end_headers ()
            with open (target ,"rb")as f :
                shutil .copyfileobj (f ,self .wfile )
            log_event (f"Downloaded file: {filename }","info")
        except Exception as exc :
            self ._error_json (500 ,f"Error downloading file: {exc }")


    def handle_backup (self ):
        try :

            tmp_file =tempfile .NamedTemporaryFile (prefix ="instmon_backup_",suffix =".zip",delete =False )
            tmp_path =tmp_file .name 
            tmp_file .close ()


            with zipfile .ZipFile (tmp_path ,'w',zipfile .ZIP_DEFLATED )as zf :
                for root ,dirs ,files in os .walk (LIBRARY_DIR ):
                    for file in files :
                        full_path =os .path .join (root ,file )
                        rel_path =os .path .relpath (full_path ,LIBRARY_DIR )
                        zf .write (full_path ,arcname =rel_path )

            stamp =datetime .now ().strftime ("%Y%m%d_%H%M%S")
            self .send_response (200 )
            self .send_header ("Content-Type","application/zip")
            self .send_header ("Content-Disposition",f"attachment; filename=\"instmon_backup_{stamp }.zip\"")
            self .send_header ("Content-Length",str (os .path .getsize (tmp_path )))
            self .end_headers ()

            with open (tmp_path ,"rb")as f :
                shutil .copyfileobj (f ,self .wfile )

            os .unlink (tmp_path )
            log_event (f"Full backup downloaded ({stamp })","ok")
        except Exception as exc :
            self ._error_json (500 ,f"Error creating backup: {exc }")


    def handle_file_write (self ):
        if self ._update_busy ():
            return 
        length =int (self .headers .get ("Content-Length",0 ))
        try :
            body =json .loads (self .rfile .read (length )or b"{}")
        except json .JSONDecodeError :
            self ._error_json (400 ,"Malformed JSON body")
            return 

        filename =body .get ("file")
        content =body .get ("content")
        category =body .get ("category")
        if not filename or content is None :
            self ._error_json (400 ,"Missing 'file' or 'content'")
            return 

        target =self ._find_library_file (filename ,category )
        if target is None :
            self ._error_json (404 ,f"File '{filename }' not found in library")
            return 

        try :
            with open (target ,"r",encoding ="utf-8")as f :
                existing =f .read ()
            if existing ==content :
                self ._send_json (200 ,{"wrote":False ,"reason":"unchanged (skipped write)"})
                return 

            tmp_path =target +".tmp"
            with open (tmp_path ,"w",encoding ="utf-8")as f :
                f .write (content )
            os .replace (tmp_path ,target )

            log_event (f"Edited file: {filename } in library","ok")
            self ._send_json (200 ,{"wrote":True ,"reason":"written"})
        except Exception as exc :
            self ._error_json (500 ,f"Error writing file: {exc }")


    def handle_upload (self ):
        if self ._update_busy ():
            return 
        content_type =self .headers .get ("Content-Type","")
        m =re .search (r'boundary=([^;]+)',content_type )
        if not m or "multipart/form-data"not in content_type :
            self ._error_json (400 ,"Expected multipart/form-data upload")
            return 
        boundary =m .group (1 ).strip ('"')
        length =int (self .headers .get ("Content-Length",0 ))
        if length <=0 or length >50 *1024 *1024 :
            self ._error_json (400 ,"Upload missing or too large")
            return 
        raw =self .rfile .read (length )
        fields =parse_multipart (raw ,boundary )

        category =fields .get ("category",(None ,b""))[1 ].decode (errors ="replace")
        filename ,filedata =fields .get ("file",(None ,None ))
        force =fields .get ("force",(None ,b""))[1 ].decode (errors ="replace")=="1"
        if category not in LIB_SUBDIRS :
            self ._error_json (400 ,f"Unknown category '{category }'")
            return 
        if not filename or filedata is None :
            self ._error_json (400 ,"No file provided")
            return 
        filename =os .path .basename (filename )
        if _is_retired_file (filename ):
            self ._error_json (400 ,f"'{filename }' is retired (asl_dvs_watchdog) -- the dashboard's own systemd watchdog covers it")
            return 
        ext =os .path .splitext (filename )[1 ].lower ()
        if ext not in ALLOWED_EXT [category ]:
            self ._error_json (400 ,f"'{ext }' not allowed for category '{category }' (expected {ALLOWED_EXT [category ]})")
            return 

        # Extension alone doesn't distinguish, say, svx_dashboard.py from
        # asl_dvs_m17_44helper.py -- both are just ".py". Reuse the same
        # naming patterns HOME_SCAN_PATTERN_MAP already trusts for the
        # automatic home-dir sweep, so a wrong-file-into-wrong-card upload
        # (silently accepted before this check existed) gets caught here
        # too, at selection time, instead of surfacing later as a broken
        # component. `force=1` is the deliberate escape hatch for the rare
        # legitimate mismatch (e.g. a renamed dev build) -- default stays
        # protective, override is explicit and logged.
        expected_patterns =dict (HOME_SCAN_PATTERN_MAP ).get (category ,[])
        name_matches =any (fnmatch .fnmatch (filename .lower (),g .lower ())for g in expected_patterns )
        if expected_patterns and not name_matches and not force :
            self ._send_json (400 ,{
            "error":f"'{filename }' doesn't look like a {category } file -- expected a name matching {' / '.join (expected_patterns )}.",
            "mismatch":True ,
            "expected":expected_patterns ,
            })
            return 
        if expected_patterns and not name_matches and force :
            log_event (f"Uploaded {filename } to {category } library despite naming mismatch (forced)","warn")

        ensure_dirs ()
        dest =safe_join (LIB_SUBDIRS [category ],filename )
        if dest is None :
            self ._error_json (400 ,"Invalid filename")
            return 
        wrote ,reason =compare_before_write (dest ,filedata )
        log_event (f"Uploaded {filename } to {category } library ({reason })","ok")
        message =f"Staged {filename } in the {category } library."if wrote else f"{filename } already staged (unchanged)."
        self ._send_json (200 ,{"name":filename ,"wrote":wrote ,"reason":reason ,"message":message ,"level":"ok"if wrote else "info"})


    def handle_action (self ):
        length =int (self .headers .get ("Content-Length",0 ))
        try :
            body =json .loads (self .rfile .read (length )or b"{}")
        except json .JSONDecodeError :
            self ._error_json (400 ,"Malformed JSON body")
            return 

        action =body .get ("action")
        if action not in _ACTIONS_DURING_UPDATE and self ._update_busy ():
            return 
        handler_fn =_ACTION_HANDLERS .get (action )
        if handler_fn is None :
            self ._error_json (400 ,f"Unknown action '{action }'")
            return 
        handler_fn (self ,body )


    def _action_install (self ,body ):

        category =body .get ("category")
        name =body .get ("name")
        comp =next ((c for c in COMPONENTS if c ["category"]==category ),None )
        if comp is None :
            self ._error_json (400 ,f"No installable component for category '{category }'")
            return 
        src =safe_join (LIB_SUBDIRS [category ],name or "")
        if src is None or not os .path .isfile (src ):
            self ._error_json (404 ,f"Library file not found: {name }")
            return 

        with _running_installs_lock :
            if comp ["service"]in _running_installs :
                self ._send_json (409 ,{
                "error":f"An install for {comp ['name']} is already in progress",
                "message":f"Another install for {comp ['name']} is already in progress -- wait for it to finish.",
                "level":"warn",
                })
                return 
            _running_installs .add (comp ["service"])


        if not script_has_self_install (src ):
            with _running_installs_lock :
                _running_installs .discard (comp ["service"])
            msg =f"{name } doesn't support self-install (--install / install_service() not found in the file) -- Install stopped. Nothing was run."
            log_event (msg ,"err")
            self ._send_json (400 ,{"error":msg ,"message":msg ,"level":"err"})
            return 

        syntax_err =check_script_syntax (src )
        if syntax_err :
            with _running_installs_lock :
                _running_installs .discard (comp ["service"])
            log_event (f"Install blocked: syntax error in {name }: {syntax_err }","err")
            self ._send_json (400 ,{
            "error":f"Syntax error in {name } -- install blocked",
            "detail":syntax_err ,
            "message":f"Install blocked: {name } has a syntax error. Nothing was run.",
            "level":"err",
            })
            return 

        thread =threading .Thread (
        target =run_self_install_bg ,args =(src ,name ,comp ),daemon =True ,
        )
        thread .start ()
        self ._send_json (200 ,{
        "started":name ,
        "message":f"Installing {name } -- {comp ['name']} will restart itself once its own --install finishes. Watch the log below for output.",
        "level":"info",
        })


    def _action_uninstall (self ,body ):

        category =body .get ("category")
        comp =next ((c for c in COMPONENTS if c ["category"]==category ),None )
        if comp is None :
            self ._error_json (400 ,f"No installable component for category '{category }'")
            return 

        target =resolve_installed_target (comp )
        if not os .path .isfile (target ):
            self ._error_json (400 ,f"{comp ['name']} is not currently installed -- nothing to uninstall.")
            return 

        if not script_has_self_uninstall (target ):
            msg =f"{comp ['name']}'s installed file doesn't support self-uninstall (--uninstall / uninstall_service() not found) -- Uninstall stopped. Nothing was run."
            log_event (msg ,"err")
            self ._send_json (400 ,{"error":msg ,"message":msg ,"level":"err"})
            return 


        with _running_installs_lock :
            if comp ["service"]in _running_installs :
                self ._send_json (409 ,{
                "error":f"An install/uninstall for {comp ['name']} is already in progress",
                "message":f"Another install/uninstall for {comp ['name']} is already in progress -- wait for it to finish.",
                "level":"warn",
                })
                return 
            _running_installs .add (comp ["service"])


        staged ,staged_name ,stage_note ,stage_err =stage_installed_copy_if_missing (comp )
        if stage_err :
            with _running_installs_lock :
                _running_installs .discard (comp ["service"])
            log_event (f"Uninstall blocked for {comp ['name']}: {stage_err }","err")
            self ._send_json (500 ,{
            "error":stage_err ,
            "message":f"Uninstall blocked: {stage_err }. Nothing was uninstalled.",
            "level":"err",
            })
            return 

        thread =threading .Thread (
        target =run_self_uninstall_bg ,args =(comp ,),daemon =True ,
        )
        thread .start ()
        self ._send_json (200 ,{
        "started":comp ["service"],
        "message":f"Uninstalling {comp ['name']} ({stage_note }) -- watch the log below for output.",
        "level":"info",
        })


    def _action_stop (self ,body ):

        service =body .get ("service","")
        comp =next ((c for c in COMPONENTS if c ["service"]==service ),None )
        if comp is None :
            self ._error_json (400 ,f"Unknown service '{service }'")
            return 
        try :
            subprocess .run (["systemctl","stop",service ],capture_output =True ,text =True ,timeout =10 )
        except (FileNotFoundError ,subprocess .TimeoutExpired )as exc :
            self ._error_json (500 ,f"Could not stop {comp ['name']}: {exc }")
            return 
        time .sleep (0.5 )
        state =systemctl_is_active (service )
        log_event (f"Stopped {comp ['name']} (now {state })","warn"if state =="active"else "info")
        self ._send_json (200 ,{
        "service":service ,
        "state":state ,
        "message":f"{comp ['name']} stopped (now {state }).",
        "level":"info",
        })


    def _action_install_config (self ,body ):
        name =body .get ("name")
        src =safe_join (LIB_SUBDIRS ["config"],name or "")
        if src is None or not os .path .isfile (src ):
            self ._error_json (404 ,f"Library config not found: {name }")
            return 
        try :
            with open (src ,"rb")as f :
                data =f .read ()
        except OSError as exc :
            self ._error_json (500 ,f"Could not read {name }: {exc }")
            return 

        dest =os .path .join (CONFIG_DIR ,CONFIG_NAME )
        with _running_installs_lock :
            if dest in _running_installs :
                self ._send_json (409 ,{
                "error":f"An install to {dest } is already in progress",
                "message":"Another config install is already in progress -- wait for it to finish.",
                "level":"warn",
                })
                return 
            _running_installs .add (dest )

        try :


            _dash_comp =next ((c for c in COMPONENTS if c ["category"]=="dashboard"),None )
            _m17_comp =next ((c for c in COMPONENTS if c ["category"]=="m17_dashboard"),None )
            comp =None 
            if _dash_comp and os .path .isfile (resolve_installed_target (_dash_comp )):
                comp =_dash_comp 
            elif _m17_comp and os .path .isfile (resolve_installed_target (_m17_comp )):
                comp =_m17_comp 
            if comp is None :
                try :
                    wrote ,reason =compare_before_write (dest ,data )
                except OSError as exc :
                    self ._error_json (500 ,f"Install failed writing {dest }: {exc }")
                    return 
                log_event (f"Install config {name } -> {dest } ({reason })","ok"if wrote else "info")
                message =(f"Config {name } installed as {CONFIG_NAME }. Neither Dashboard nor M17 Dashboard is currently installed -- apply it manually."
                if wrote else f"{name } is already the active config (unchanged).")
                self ._send_json (200 ,{"wrote":wrote ,"reason":reason ,"message":message ,"level":"warn"if wrote else "info"})
                return 

            result =install_file_with_verification (data ,dest ,comp )
            if result ["reason"]=="error":
                self ._error_json (500 ,result ["message"])
                return 

            log_event (f"Install config {name } -> {dest } ({result ['reason']})","ok"if result ["wrote"]else "info")
            if result ["wrote"]:
                result ["message"]=f"Config {name } installed as {CONFIG_NAME }. {result ['message']}"
            else :
                result ["message"]=f"{name } is already the active config (unchanged) -- no restart needed."
            self ._send_json (200 ,result )
        finally :
            with _running_installs_lock :
                _running_installs .discard (dest )


    def _action_delete (self ,body ):
        category =body .get ("category")
        name =body .get ("name")
        if category not in LIB_SUBDIRS :
            self ._error_json (400 ,f"Unknown category '{category }'")
            return 
        target =safe_join (LIB_SUBDIRS [category ],name or "")
        if target is None or not os .path .isfile (target ):
            self ._error_json (404 ,f"Library file not found: {name }")
            return 
        os .remove (target )
        log_event (f"Deleted {name } from {category } library","warn")
        self ._send_json (200 ,{"deleted":name ,"message":f"Deleted {name } from the library.","level":"warn"})


    def _action_run_script (self ,body ):
        name =body .get ("name")
        target =safe_join (LIB_SUBDIRS ["scripts"],name or "")
        if target is None or not os .path .isfile (target ):
            self ._error_json (404 ,f"Script not found: {name }")
            return 


        with _running_scripts_lock :
            if name in _running_scripts :
                self ._send_json (409 ,{
                "error":f"{name } is already running",
                "message":f"{name } is already running -- wait for it to finish before running it again.",
                "level":"warn",
                })
                return 
            _running_scripts .add (name )


        env_overrides ={}
        for field ,envvar in (
        ("auto_callsign","AUTO_CALLSIGN"),
        ("auto_node","AUTO_NODE"),
        ("auto_label","AUTO_LABEL"),
        ):
            val =body .get (field )
            if val :
                env_overrides [envvar ]=str (val )

        thread =threading .Thread (
        target =run_script_bg ,args =(target ,name ,env_overrides or None ),daemon =True ,
        )
        thread .start ()
        self ._send_json (200 ,{"started":name ,"message":f"Running {name } -- watch the log below for output.","level":"info"})


    def _action_save_alternate (self ):
        live_cfg =os .path .join (CONFIG_DIR ,CONFIG_NAME )
        if not os .path .isfile (live_cfg ):
            self ._error_json (404 ,f"No active config at {live_cfg }")
            return 
        stamp =datetime .now ().strftime ("%Y%m%d_%H%M%S")
        base ,ext =os .path .splitext (CONFIG_NAME )
        alt_name =f"{base }_{stamp }{ext }"
        ensure_dirs ()
        dest =os .path .join (LIB_SUBDIRS ["config"],alt_name )
        shutil .copy2 (live_cfg ,dest )
        log_event (f"Saved active config as alternate: {alt_name }","ok")
        self ._send_json (200 ,{"name":alt_name ,"message":f"Saved active config as {alt_name }.","level":"ok"})


    def _action_journal (self ,body ):
        service =body .get ("service","")
        if not re .fullmatch (r"[A-Za-z0-9_.@-]+",service or ""):
            self ._error_json (400 ,"Invalid service name")
            return 
        try :
            result =subprocess .run (
            ["journalctl","-u",service ,"-n","40","--no-pager"],
            capture_output =True ,text =True ,timeout =5 ,
            )
            output =result .stdout or result .stderr or "(no output)"
        except (FileNotFoundError ,subprocess .TimeoutExpired )as exc :
            output =f"journalctl unavailable: {exc }"
        for line in output .splitlines ()[-40 :]:
            log_event (line ,"info")
        self ._send_json (200 ,{"service":service ,"message":f"Fetched last 40 lines from {service } -- see log below.","level":"info"})


    def _action_comms_restart (self ,body ):
        
        
        
        
        
        
        
        stop_results =[]
        for label ,unit in COMMS_RESTART_SERVICES :
            try :
                r =subprocess .run (["systemctl","stop",unit ],capture_output =True ,text =True ,timeout =15 )
                stop_ok =r .returncode ==0 
            except (FileNotFoundError ,subprocess .TimeoutExpired )as exc :
                stop_ok =False 
                log_event (f"Comms restart: {label } ({unit }) stop errored: {exc }","err")
            else :
                log_event (f"Comms restart: {label } ({unit }) stopped"if stop_ok 
                else f"Comms restart: {label } ({unit }) stop FAILED (rc={r .returncode })",
                "info"if stop_ok else "err")
            stop_results .append ((label ,unit ,stop_ok ))

        log_event (f"Comms restart: pausing {COMMS_RESTART_PAUSE_SEC }s before bringing services back up...","info")
        time .sleep (COMMS_RESTART_PAUSE_SEC )

        results =[]
        for label ,unit ,stop_ok in stop_results :
            try :
                r =subprocess .run (["systemctl","start",unit ],capture_output =True ,text =True ,timeout =15 )
                start_ok =r .returncode ==0 
            except (FileNotFoundError ,subprocess .TimeoutExpired )as exc :
                log_event (f"Comms restart: {label } ({unit }) start errored: {exc }","err")
                results .append ((label ,False ,str (exc )))
                continue 
            state =systemctl_is_active (unit )
            ok =start_ok and state =="active"
            results .append ((label ,ok ,state ))
            log_event (f"Comms restart: {label } ({unit }) -> {'started'if ok else 'FAILED to start'} (now {state })",
            "ok"if ok else "err")

        failed =[label for label ,ok ,_ in results if not ok ]
        summary =", ".join (f"{label } {'ok'if ok else 'FAILED'}"for label ,ok ,_ in results )
        verb =f"full stop -> {COMMS_RESTART_PAUSE_SEC }s pause -> start"
        if failed :
            message =f"Comms SERV Restart ({verb }): {summary }. Check the log below for {', '.join (failed )}."
            level ="err"
        else :
            message =f"Comms SERV Restart ({verb }): all clear -- {summary }."
            level ="ok"
        self ._send_json (200 if not failed else 207 ,{
        "results":[{"service":label ,"ok":ok ,"state":state }for label ,ok ,state in results ],
        "message":message ,
        "level":level ,
        })


    def _action_quiet (self ,body ):
        res =quiet_on ("Quiet button")
        if res ["already"]:
            self ._send_json (200 ,{"message":"The system is already quiet.","level":"info"})
            return 
        names =", ".join (res ["stopped"])or "nothing was running"
        if res ["failed"]:
            self ._send_json (207 ,{"message":f"Quiet: stopped {names}; did not stop {', '.join(res['failed'])}.","level":"err"})
            return 
        self ._send_json (200 ,{"message":f"System quiet: stopped {names}. Press Restore when you're done "
        f"(auto-restore in {QUIET_AUTO_RESTORE_SEC // 60} min).","level":"ok"})

    def _action_restore (self ,body ):
        res =quiet_restore ("Restore button")
        if res ["already"]:
            self ._send_json (200 ,{"message":"The system isn't quiet -- nothing to restore.","level":"info"})
            return 
        if res ["failed"]:
            self ._send_json (207 ,{"message":f"Restore: {', '.join(res['failed'])} did not start -- see the log.","level":"err"})
            return 
        self ._send_json (200 ,{"message":f"Restored: {', '.join(res['started']) or 'nothing was stopped'}.","level":"ok"})

    def _action_check_updates (self ,body ):
        try :
            res =update_check ()
        except Exception as exc :
            log_event (f"Check for updates failed: {exc}","err")
            self ._send_json (502 ,{"error":str (exc ),"message":f"Couldn't read GitHub: {exc}","level":"err"})
            return 
        n ,ns =res ["updates"],res ["new_scripts"]
        if n or ns :
            msg =f"{n} component update(s), {ns} new script(s) on GitHub."
        else :
            msg ="Everything is current with GitHub."
        log_event (f"Check for updates: {msg}","ok"if not (n or ns )else "info")
        self ._send_json (200 ,{"result":res ,"message":msg ,"level":"info"if (n or ns )else "ok"})

    def _action_full_update (self ,body ):
        with _update_lock :
            if _update ["running"]:
                self ._send_json (409 ,{"error":"Full Update is already running","message":"Full Update is already running.","level":"warn"})
                return 
            _update .update (running =True ,phase ="starting",current ="",started =time .time (),finished =0.0 ,
            error ="",updated =[],skipped =[],attention =[],scripts =[],unchanged =[],
            banner =False ,instmon_pending =None )
        with _running_installs_lock :
            busy =sorted (_running_installs )
        with _running_scripts_lock :
            busy +=sorted (_running_scripts )
        if busy :
            _update_set (running =False ,phase ="")
            self ._send_json (409 ,{"error":"busy","message":f"Wait for {', '.join(busy)} to finish first.","level":"warn"})
            return 
        log_event ("Full Update started","info")
        threading .Thread (target =run_full_update_bg ,daemon =True ).start ()
        self ._send_json (200 ,{"message":"Full Update started -- progress shows on the Updates card and in the log.","level":"info"})

    def _action_update_dismiss (self ,body ):
        update_dismiss ()
        self ._send_json (200 ,{"message":"","level":"info"})


    def _action_reboot (self ,body ):
        log_event ("System reboot requested from instmon UI","warn")
        try :
            
            
            
            
            
            
            
            
            subprocess .run ([
            "systemd-run","--quiet","--collect","--on-active=2",
            "--unit=instmon-reboot","systemctl","reboot",
            ],check =True ,timeout =10 )
        except (FileNotFoundError ,subprocess .TimeoutExpired ,subprocess .CalledProcessError )as exc :
            log_event (f"Reboot request failed: {exc }","err")
            self ._error_json (500 ,f"Could not schedule reboot: {exc }")
            return 
        self ._send_json (200 ,{
        "message":"Rebooting in ~2s. This page (and everything else on the node) will be unreachable until it comes back up.",
        "level":"warn",
        })


    def _action_shutdown (self ,body ):
        log_event ("System shutdown requested from instmon UI","warn")
        try :
            subprocess .run ([
            "systemd-run","--quiet","--collect","--on-active=2",
            "--unit=instmon-shutdown","systemctl","poweroff",
            ],check =True ,timeout =10 )
        except (FileNotFoundError ,subprocess .TimeoutExpired ,subprocess .CalledProcessError )as exc :
            log_event (f"Shutdown request failed: {exc }","err")
            self ._error_json (500 ,f"Could not schedule shutdown: {exc }")
            return 
        self ._send_json (200 ,{
        "message":"Shutting down in ~2s. You'll need physical/console access (or a smart PDU) to power it back on.",
        "level":"warn",
        })


    def log_message (self ,format ,*args ):
        return 


def parse_multipart (raw ,boundary ):
    boundary_bytes =("--"+boundary ).encode ()
    parts =raw .split (boundary_bytes )
    result ={}
    # v1.27.8: strip exactly the multipart framing -- the CRLF after the
    # boundary line and the CRLF before the next one.  The old
    # part.strip(b"\r\n") also ate the file's own trailing newline(s), so a
    # staged copy differed from the uploaded file.
    for part in parts [1 :]:
        if part .startswith (b"--"):
            break 
        if part .startswith (b"\r\n"):
            part =part [2 :]
        if part .endswith (b"\r\n"):
            part =part [:-2 ]
        if b"\r\n\r\n"not in part :
            continue 
        header_blob ,value =part .split (b"\r\n\r\n",1 )
        headers =header_blob .decode (errors ="replace")
        name_match =re .search (r'name="([^"]+)"',headers )
        if not name_match :
            continue 
        filename_match =re .search (r'filename="([^"]*)"',headers )
        field_name =name_match .group (1 )
        filename =filename_match .group (1 )if filename_match else None 
        result [field_name ]=(filename ,value )
    return result 


def install_service ()->None :
    if os .geteuid ()!=0 :
        print ("Error: Installation requires root privileges. Run with 'sudo'.")
        sys .exit (1 )

    current_script =os .path .abspath (__file__ )

    print ("Installing instmon...")

    if current_script !=INSTALL_BIN_PATH :
        shutil .copy2 (current_script ,INSTALL_BIN_PATH )
        print (f"  [+] Copied script to {INSTALL_BIN_PATH }")
    os .chmod (INSTALL_BIN_PATH ,0o755 )

    with open (SYSTEMD_SERVICE_PATH ,"w")as f :
        f .write (SYSTEMD_SERVICE_CONTENT )
    print (f"  [+] Created service file at {SYSTEMD_SERVICE_PATH }")

    subprocess .run (["systemctl","daemon-reload"],check =True )
    subprocess .run (["systemctl","enable","instmon.service"],check =True )
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    subprocess .run ([
    "systemd-run","--quiet","--collect","--on-active=2",
    "--unit=instmon-selfrestart",
    "systemctl","restart","instmon.service",
    ],check =True )
    print ("  [+] Enabled instmon.service; restart scheduled in ~2s")
    print (f"\nInstallation complete! instmon will be listening on port {PORT } shortly.")
    print ("View logs anytime using:")
    print ("  journalctl -u instmon -f")


def uninstall_service ()->None :
    if os .geteuid ()!=0 :
        print ("Error: Uninstallation requires root privileges. Run with 'sudo'.")
        sys .exit (1 )

    print ("Uninstalling instmon...")

    subprocess .run (["systemctl","disable","--now","instmon.service"],stderr =subprocess .DEVNULL )
    print ("  [-] Stopped and disabled instmon.service")

    if os .path .exists (SYSTEMD_SERVICE_PATH ):
        os .remove (SYSTEMD_SERVICE_PATH )
        print (f"  [-] Removed {SYSTEMD_SERVICE_PATH }")

    subprocess .run (["systemctl","daemon-reload"],stderr =subprocess .DEVNULL )

    if os .path .exists (INSTALL_BIN_PATH ):
        os .remove (INSTALL_BIN_PATH )
        print (f"  [-] Removed {INSTALL_BIN_PATH }")

    print ("\nUninstallation complete.")
    print ("Note: the library/config/install directories under "
    f"{LIBRARY_DIR } were left in place -- remove manually if desired.")


class InstmonServer (http .server .ThreadingHTTPServer ):
    allow_reuse_address =True 
    daemon_threads =True 


def run ():
    ensure_dirs ()
    log_event (f"instmon v{VERSION } starting on port {PORT }","info")
    quiet_resume_at_startup ()
    update_resume_at_startup ()

    if HOME_SCAN_ENABLED :
        moved =scan_home_for_new_code ()
        if moved :
            log_event (f"Home-dir scan: staged {len (moved )} new file(s) from {HOME_SCAN_DIR }","ok")
        else :
            log_event (f"Home-dir scan: nothing new in {HOME_SCAN_DIR }","info")

    server_address =("",PORT )
    httpd =InstmonServer (server_address ,InstmonHandler )
    print (f"Starting instmon web installer v{VERSION } on port {PORT }...")
    try :
        httpd .serve_forever ()
    except KeyboardInterrupt :
        print ("\nShutting down instmon server.")
        httpd .server_close ()
        sys .exit (0 )


if __name__ =="__main__":
    parser =argparse .ArgumentParser (description ="instmon - KD8PGK Web Installer & Component Manager")
    parser .add_argument ("--install",action ="store_true",help ="Install instmon as a systemd service & start")
    parser .add_argument ("--uninstall",action ="store_true",help ="Stop & remove instmon systemd service")
    args =parser .parse_args ()

    if args .install :
        install_service ()
    elif args .uninstall :
        uninstall_service ()
    else :
        run ()