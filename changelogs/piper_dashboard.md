# Pi-Piper TTS changelog

Current file: `piper_dashboard_v0_8_0_20261121.py`.

## 0.8.0 (2026-11-21)

Progress bar, legacy installs, and a longer log. This is a release: the Run card has a progress bar, the engine card can hide, and the installer reuses an existing Piper.

- **Progress bar.** The Run card shows how many sentences of the run are done. It counts sentences, so it is an estimate, and it fills completely when the run finishes. Run and Stream both report it (`/api/progress`).
- **Existing installs.** Before installing, the engine looks in the usual places (`/root/piper/venv`, `/home/*/piper/venv`, `/opt/piper/venv` and others) for a venv that already has `piper-tts`, and uses it instead of reinstalling. The same check runs at startup. An old `piper` command-line program alone is not enough, because this dashboard needs the Python package, so the engine card stays visible in that case.
- **Engine card.** The Engine card is hidden once the engine is installed or found in an existing install.
- **Terminal output.** The install log keeps 180 lines (was 60) and its box is three times as tall.
- **Tests.** The export test's expected size follows the run's output (the engine's streaming output, not the one-second fixture).

## 0.7.0 (2026-11-21)

Settings tab, and saving output to a Pibrary drive. This is a release: the page has a second tab, and generated WAV files can go to Pibrary.

- **Settings tab.** Bind address, port, GPU, preload voice, voice catalog URL, play on node (node numbers, sounds directory, longest clip, Asterisk command). Saving validates every field on the server and writes `/etc/asl_dvs/piper_dashboard.conf` atomically. Changes take effect on the next restart (Restart service to apply).
- **Play on node.** Turning it on (node numbers set while blank) asks for confirmation on the page and again on the server (409 until confirmed). Nothing transmits from the Settings tab.
- **Save output to Pibrary.** When the Pibrary service is running, the drive list is Pibrary's own library root and extra roots (read from `/etc/pibrary/pibrary.conf`, no Pibrary change). Generated WAV files go to `<drive>/audio/TTS`. If Pibrary is stopped, the drive is missing or not writable, the file goes to the local output folder and the Run page says why.
- **Config format.** Adds a `[pibrary] root` key. Other keys are unchanged.

## 0.6.0 (2026-11-21)

Installs like the rest of the suite, and self-update is removed. This is a release: the install layout, the config file and the unit changed.

- **Install layout.** The program is `/usr/local/lib/piper_dashboard/piper_dashboard.py`, linked from `/usr/local/bin/piper_dashboard.py`. The unit starts it through the shared launcher (`/usr/local/bin/asl_dvs_launch.py`, identical in every tool), as Node Monitor does. `--install` and `--uninstall` are the suite's commands; `--purge`, `--run-as`, `--destdir` and `--apply-staged`/`--rollback` are gone.
- **Config.** `/etc/asl_dvs/piper_dashboard.conf` (was `/etc/piper_dashboard.ini`). Default bind is `0.0.0.0` (the sign-in protects every page). Data stays in `/srv/piper_dashboard`, and the engine venv is `/srv/piper_dashboard/venv`.
- **Firewall.** `--install` opens the port with the suite's firewall helper; `--uninstall` closes it. Shared code from `shared/confio.py`.
- **Self-update removed.** The service runs as root, so an uploaded update would run as root. Updates come through instmon instead.
- **Launcher.** The unit uses the shared launcher text, so the test that checks it passes and the unit runs under the suite's launcher.

## 0.5.0 (2026-11-21)

Login, security headers and the root password check. This is a release: the service now runs as root (as Pibrary does) and every page and API route needs a sign-in, except the page itself and the status line.

- **Sign-in.** The root password, checked through PAM when the `pam` module is present and otherwise against `/etc/shadow` (crypt). Shared session and lockout code from `shared/confio.py` (standard tier: 12 h idle, cookie refreshed about hourly, 5 s doubling to 300 s lockout after 5 wrong tries).
- **Sign out ends every session.** A new session is the only way back in after a sign-out.
- **Password change ends sessions.** The session is tied to the root shadow hash.
- **Requests.** Every POST needs the `X-Requested-With: XMLHttpRequest` header (403 otherwise). The update route keeps its own token.
- **Headers.** `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff` and a Content-Security-Policy on every reply.
- **Status line.** Without a sign-in `/api/status` returns only the version and engine state (the watchdog probe uses it).
- **Service user.** Defaults to root. `--run-as` still accepts another user, but a non-root user cannot read the shadow file, so sign-in will not work for it.

## 0.4.0 (2026-11-21)

First version in the repo: a web dashboard for a Piper TTS install (piper-tts pip package) on a node.

- **Voices.** Pick a voice and browse the Hugging Face voice catalog (md5 and size checked, `.part` files, atomic rename).
- **Text.** Run from a file or pasted text. Save a WAV, or stream raw PCM with a prebuffer and Stop.
- **Export.** 8 kHz ulaw, sln or 8 kHz WAV from a saved WAV.
- **Play on node.** Off by default. Needs `[radio] nodes` and `sounds_dir`; checks the node list, the 8 kHz file and the clip length.
- **Self-update.** Off by default. Needs `[update] enabled` and a token. An upload is checked, not run, and staged. A root step copies it into a new version.
- **Install.** `--install`, `--uninstall [--purge]`, `--destdir`, `--apply-staged`, `--rollback`, `--selftest`.
- **Root step is a snapshot.** The unit's root `ExecStartPre` runs `/opt/piper_dashboard/root/piper_dashboard.py`, a copy made by the installer. Updates change only `lib/` and `current`, which the service user cannot write.
- **Purge is exact.** The installer records the service user and whether it created it in `/etc/piper_dashboard.user`. Purge removes that user's venv, and the user itself only if the installer created it.
- **Validation.** A non-finite length, noise or W scale falls back to the default.
- **Restart.** A failed restart in the installer prints the status line and the journal hint instead of a traceback.
