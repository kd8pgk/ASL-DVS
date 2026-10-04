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

## Dashboard (found in v9.3.69)

1. The startup banner in `main()` is out of line. The box is 48
   characters wide, but:
   - The ASL node and bridge lines are 1 character short.
   - The Local line is 1 character too long.
   - The Network line pads by port length only, ignoring the IP's
     length, so it is short or long depending on the IP (41 characters
     with `192.0.2.2`).

   Corrected padding, tested with 1-7 digit nodes, 2-5 digit ports and
   7-15 character IPs:

   ```python
   pad = " " * max(0, 32 - len(_cfg.asl_node))
   lpad = " " * max(0, 15 - len(str(_cfg.port)))
   npad = " " * max(0, 24 - len(ip) - len(str(_cfg.port)))
   ...
       _bpad = " " * max(0, 32 - len(_val))
   ...
   ║  Network   : http://{ip}:{_cfg.port}{npad}║
   ```
   (Also remove the two spaces before `║` at the end of the Network line.)

2. Line 1902: `f"exten => _011.,1,NoOp(international)"` has no
   placeholders, so the `f` prefix can go (pyflakes F541).

3. `_phone_call_state()` (line 2472): `chan` is unpacked from each
   channel row but never used (pyflakes F841). Change it to `_`, or drop
   it from the unpack.

4. The page has no favicon. Every browser load asks for `/favicon.ico`,
   gets a 404 and logs it in the browser console. Optional: add
   `<link rel="icon" href="data:,">` to `<head>` to silence it.
