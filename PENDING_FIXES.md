# Pending fixes for later builds

Found during the 2026-10-04 error check of sysmon v6.13.65 and dashboard
v9.3.69. Neither file has a functional error; these are small fixes to
fold into the next build of each.

## sysmon (found in v6.13.65)

1. `_ts_dash_version_of()` (about line 26217): `[\d.]+` also matches a
   trailing dot, so a version written like `"9.3."` reads as `9.3.`.
   `_ts_vnum()` then returns `()`, which sorts below `9.3.69`, and
   "Dashboard file check" warns that the dashboard is out of date when
   it isn't. Change both patterns to `\d+(?:\.\d+)*`:

   ```python
   m = re.search(r'VERSION\s*=\s*"(\d+(?:\.\d+)*)"', head) or re.search(r"asl_dvs_dashboard\.py\s+\S+\s+v(\d+(?:\.\d+)*)", head)
   ```

2. `_ts_dash_paths()` (about line 26210): `except OSError` around
   `_run([...systemctl...])` never runs, because `_run()` already catches
   every exception and returns `""`. It does no harm. Drop the
   try/except and call `_run()` directly.

## Dashboard (found in v9.3.69) -- done in v9.3.70

All four items are fixed in `asl_dvs_dashboard_v9.3.70_2026-10-04.py`.
See BUILD_PLAN_dashboard_v9.3.70.md. Item 4 is fixed differently than
first proposed: the page's Content-Security-Policy blocks `data:` images,
so the server now answers `/favicon.ico` with 204 No Content instead.
