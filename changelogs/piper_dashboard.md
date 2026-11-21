# Pi-Piper TTS changelog

Current file: `piper_dashboard_v0_4_0_20261121.py`.

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
