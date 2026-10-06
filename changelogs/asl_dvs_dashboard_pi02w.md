# Dashboard, Pi Zero 2 W build changelog

Current file: `asl_dvs_dashboard_pi02w_v9_3_71_2_20261006.py`. Newest entries first.

## 9.3.71.2-pi02w (2026-10-06)

- Launcher version 2 (`/usr/local/bin/asl_dvs_launch.py`, the same file every ASL-DVS `--install` writes) adds three memory savers, each with an off switch. Create the file and restart the service to turn one off; delete it and restart to turn it back on.
  - `python3 -OO`: drops docstrings from the loaded code. Off: `/etc/asl_dvs/launch_no_optimize`
  - `MALLOC_ARENA_MAX=2`: at most 2 malloc pools instead of up to 8 per CPU core. Off: `/etc/asl_dvs/launch_no_arena_cap`
  - `malloc_trim`: 1 minute after start, then every 5 minutes, freed memory is handed back to Linux. Off: `/etc/asl_dvs/launch_no_trim`
  
  The service files are unchanged: the launcher starts Python once more with `-OO` and `MALLOC_ARENA_MAX` (same PID, so systemd notify and watchdog are not affected). The launcher itself is comment-stripped too.

- Repo copy is comment-stripped. The change history that was in the file's comments now lives in this changelog.


## Earlier history

Carried over unchanged from the comments of the files below.

### asl_dvs_dashboard_pi02w_v9_3_71_2_20261006.py (header comments)

```text
ASL-DVS Node Control  —  asl_dvs_dashboard.py  —  v9.3.71.2-pi02w  —  2026-10-06
KD8PGK / Claude AI (Anthropic)  —  CC BY-NC 4.0
Build: Pi Zero 2 W fork of v9.3.71

Same tabs and features as v9.3.71 (Phone
and every digital mode); lighter on memory and CPU for a 512 MB Pi:
  - ASL node search reads /var/lib/asterisk/astdb.txt from disk on each
    search instead of holding ~40,000 nodes in memory (was ~16 MB, 32 MB
    while the file was re-read).  One pass per file version records the
    node count, repeated nodes and lines with control characters, so a
    search only fully parses lines that could match (~30 ms here).
  - EchoLink station search: the `echolink dbdump` list is written to
    /run/asl_dvs_dashboard/echodb.txt (about 300 KB for 20,000 stations)
    and searched the same way, instead of a 2-5 MB in-memory list rebuilt
    every 5 minutes.  Refreshed on use when older than 5 minutes; a failed
    refresh keeps the last good file.
  Results are identical to v9.3.71 (same parsing, first line for a node
  wins, same order, same counts and totals).
  - Slower polling: the link/keyed poll of Asterisk runs every 2 s (was
    1 s; bridge up/down now after 2 polls, ~4 s, was 3 polls, ~3 s); the
    page refreshes every 5 s when idle (was 3 s; 1 s while busy is
    unchanged) and checks the TX/RX light every 1 s (was 0.5 s).
  - Launcher: the service starts through /usr/local/bin/asl_dvs_launch.py
    (shared with the Pi02w sysmon), which imports this file instead of
    running it, so Python keeps the compiled copy in __pycache__ and
    reuses it: about 25 MB settled instead of 45 MB, twice as fast to
    start.  --install clears compiled copies of older versions;
    --uninstall removes this one and, when unused, the launcher.
  v9.3.71.2-pi02w: Launcher version 2 (the same file every ASL-DVS
    --install writes): three memory savers, each with an off switch --
    python3 -OO (drops docstrings from the loaded code; off:
    /etc/asl_dvs/launch_no_optimize), MALLOC_ARENA_MAX=2 (at most 2
    malloc pools instead of up to 8 per CPU core; off:
    /etc/asl_dvs/launch_no_arena_cap) and malloc_trim every 5 minutes
    (freed memory handed back to Linux; off:
    /etc/asl_dvs/launch_no_trim).  Create the file and restart the
    service to turn one off.  The service files are unchanged; the
    launcher starts Python once more with -OO and MALLOC_ARENA_MAX (same
    PID).
  v9.3.71.1-pi02w: --uninstall also removes the EchoLink cache folder
    /run/asl_dvs_dashboard, and no longer stops part-way if a compiled
    copy or the launcher is already gone.
```
