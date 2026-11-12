# Bootstrap (bootstrap.sh) changelog

Current file: `bootstrap.sh`. Newest entries first. The file name never changes (the one-line install points at it), so a new version only moves the title line.

## 1.0.0 (2026-11-12)

First version. The one-line install:

```
curl -fsSL https://raw.githubusercontent.com/kd8pgk/ASL-DVS/main/bootstrap.sh | sudo bash
```

- **Finds the installer.** On the stable channel (the default) it takes the installer named in `channels/stable.json`, at that commit, and checks the file against the list's blob. While the stable installer is older than 7.6.0 (the first that installs the whole suite on a fresh node), or with `ASL_DVS_CHANNEL=testing`, it takes the newest `install_all_v*.sh` named in the README on `main`.
- **Checks it before running it:** a shebang, the installer's title line and `bash -n`. A file that fails is not run.
- **Keeps a copy** in instmon's Scripts library (`/etc/asl_dvs/instmon_library/scripts/`).
- **Runs the installer on your terminal,** so its questions work even though the script came down a pipe. Options after `bash -s --` are passed on (`| sudo bash -s -- --with-termon`).
- Needs only bash and curl or wget; git and the rest are the installer's business. `ASL_DVS_REPO` sets another repo.

Tests: nine in `ci/test_installers.py` (a local folder stands in for GitHub).
