const fs = require('node:fs');
const path = require('node:path');
const { flipFuses, FuseV1Options, FuseVersion } = require('@electron/fuses');

const WRAPPER = `#!/bin/sh
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BIN="$DIR/nullbrowser-bin"
if [ -n "$NULLBROWSER_PRELAUNCH_DIR" ]; then
  exec "$BIN" "$@"
fi
UID_N=$(id -u)
if [ -d /dev/shm ] && [ -w /dev/shm ]; then
  BASE=/dev/shm
else
  BASE=\${TMPDIR:-/tmp}
fi
NB_DIR=$(mktemp -d "$BASE/null-browser-$UID_N-$$-XXXXXX" 2>/dev/null) || exec "$BIN" "$@"
chmod 700 "$NB_DIR"
for s in home config cache data state chromium session temp files; do
  mkdir -m 700 "$NB_DIR/$s"
done
echo $$ > "$NB_DIR/pid"
chmod 600 "$NB_DIR/pid"
export HOME="$NB_DIR/home"
export XDG_CONFIG_HOME="$NB_DIR/config"
export XDG_CACHE_HOME="$NB_DIR/cache"
export XDG_DATA_HOME="$NB_DIR/data"
export XDG_STATE_HOME="$NB_DIR/state"
export TMPDIR="$NB_DIR/temp"
export NULLBROWSER_PRELAUNCH_DIR="$NB_DIR"
exec "$BIN" "$@"
`;

module.exports = async function afterPack(context) {
  if (context.electronPlatformName !== 'linux') return;
  const name = context.packager.executableName;
  const bin = path.join(context.appOutDir, name);
  await flipFuses(bin, {
    version: FuseVersion.V1,
    [FuseV1Options.RunAsNode]: false,
    [FuseV1Options.EnableCookieEncryption]: true,
    [FuseV1Options.EnableNodeOptionsEnvironmentVariable]: false,
    [FuseV1Options.EnableNodeCliInspectArguments]: false,
    [FuseV1Options.EnableEmbeddedAsarIntegrityValidation]: true,
    [FuseV1Options.OnlyLoadAppFromAsar]: true,
    [FuseV1Options.GrantFileProtocolExtraPrivileges]: true,
  });
  const real = path.join(context.appOutDir, `${name}-bin`);
  fs.renameSync(bin, real);
  fs.writeFileSync(bin, WRAPPER, { mode: 0o755 });
};
