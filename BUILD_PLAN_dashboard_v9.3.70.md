# Dashboard v9.3.70 build plan

Starts from v9.3.69 (2026-10-04) and applies the four dashboard items in
PENDING_FIXES.md. Each stage changes one thing and is checked before the
next stage starts. Nothing changes what the dashboard does on the node.

| Stage | Change | Check |
|---|---|---|
| 1 | Startup banner: fix the padding on the ASL node, bridge, Local and Network lines so every line is 48 characters wide | Start the dashboard and measure every banner line. Also test the padding with 1-7 digit nodes, 2-5 digit ports and 7-15 character IPs. |
| 2 | Pyflakes clean-up: drop the `f` from the international `NoOp` line (1902) and the unused `chan` in `_phone_call_state()` (2472) | `pyflakes` reports nothing. The generated dialplan text is byte-for-byte the same. |
| 3 | Favicon: the server answers `/favicon.ico` with 204 No Content. (A `data:` icon link would be blocked by the page's Content-Security-Policy, which allows images only from `'self'`.) | Load the page in Chromium; no 404 in the console. |
| 4 | Release: `VERSION = "9.3.70"`, header line, build date | Run the full check set again (below), then save as `asl_dvs_dashboard_v9.3.70_2026-10-04.py`. |

## Full check set (stage 4)

- `py_compile` and `pyflakes`
- sysmon v6.13.65 "Dashboard file check": version 9.3.70, nothing
  defined twice, no missing page functions
- `node --check` on the page JavaScript
- Every API route the page calls exists on the server
- Server smoke test: every GET route returns 200 when logged in, with no
  tracebacks
- Headless Chromium at phone width: no JavaScript errors and no 404s
- `diff` against v9.3.69 shows only the changes above

## Not in this build

The two sysmon items in PENDING_FIXES.md wait for the next sysmon build.
sysmon's `_TS_DASH_MIN` (9.3.69) doesn't need to change for v9.3.70.

## Result (all stages done)

- Banner: all 13 lines are 48 characters. The padding was also tested with
  1-7 digit nodes, 2-5 digit ports and 7-15 character IPs.
- `py_compile` passes and `pyflakes` reports nothing.
- The phone dialplan for all five network types, with international
  dialing on, is byte-for-byte the same as v9.3.69 (12,569 bytes).
- sysmon "Dashboard file check": "Dashboard file looks fine" (9.3.70;
  437 Python and 251 page functions, none twice; all 86 handler
  functions found).
- `node --check` on the page JS passes; all 25 page API routes exist.
- Server smoke test: 28 of 28 GET routes return 200 when logged in, with
  no tracebacks.
- Headless Chromium at phone width, clicking through 14 tab buttons: 0
  console errors, 0 HTTP errors.
- `diff` against v9.3.69 shows only these changes plus the version line.
