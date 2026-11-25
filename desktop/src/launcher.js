const fs = require('node:fs');
const path = require('node:path');

const APP_ID = 'nodecontroller';
const WM_CLASS = 'nodecontroller';

function desktopDirFrom(home, userDirsText) {
  const m = /^\s*XDG_DESKTOP_DIR\s*=\s*"([^"\n]*)"/m.exec(String(userDirsText || ''));
  if (m) {
    const v = m[1].replace(/^\$HOME(?=\/|$)/, home);
    if (path.isAbsolute(v) && path.resolve(v) !== path.resolve(home)) return v;
  }
  return path.join(home, 'Desktop');
}

function launcherPaths(home, desktopDir) {
  const share = path.join(home, '.local', 'share');
  return {
    appDir: path.join(share, 'node-controller'),
    app: path.join(share, 'node-controller', 'NodeController.AppImage'),
    version: path.join(share, 'node-controller', 'version'),
    menu: path.join(share, 'applications', `${APP_ID}.desktop`),
    icon: path.join(share, 'icons', 'hicolor', '256x256', 'apps', `${APP_ID}.png`),
    shortcut: desktopDir ? path.join(desktopDir, `${APP_ID}.desktop`) : '',
  };
}

function execQuote(file) {
  const p = String(file);
  if (!p || /["`$\\\n\r]/.test(p)) return '';
  return `"${p.replace(/%/g, '%%')}"`;
}

function desktopEntry({ exec, version }) {
  const cmd = execQuote(exec);
  if (!cmd) return '';
  return [
    '[Desktop Entry]',
    'Type=Application',
    'Name=Node Controller Desktop',
    'Comment=Node Controller, Node Talker and the other node pages in one window',
    `Exec=${cmd}`,
    `TryExec=${String(exec).replace(/%/g, '%%')}`,
    `Icon=${APP_ID}`,
    'Terminal=false',
    'Categories=Network;HamRadio;',
    `StartupWMClass=${WM_CLASS}`,
    `X-NodeController-Version=${version}`,
    '',
  ].join('\n');
}

function readText(file) {
  try {
    return fs.readFileSync(file, 'utf8').trim();
  } catch {
    return '';
  }
}

function launcherStatus(paths, running, version) {
  const installed = fs.existsSync(paths.app) && fs.existsSync(paths.menu);
  const installedVersion = installed ? readText(paths.version) : '';
  return {
    available: Boolean(running),
    installed,
    installedVersion,
    fromInstalled: Boolean(running) && path.resolve(running) === path.resolve(paths.app),
    newer: installed && installedVersion !== '' && installedVersion !== version,
    shortcut: Boolean(paths.shortcut) && fs.existsSync(paths.shortcut),
  };
}

function writeAtomic(file, data, mode) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, data);
  if (mode) fs.chmodSync(tmp, mode);
  fs.renameSync(tmp, file);
}

function installLauncher({ paths, running, iconPng, version, desktop = true }) {
  if (!running || !fs.existsSync(running)) return { error: 'This copy is not running from an AppImage, so there is nothing to add.' };
  const entry = desktopEntry({ exec: paths.app, version });
  if (!entry) return { error: 'The home folder path has characters a launcher cannot hold.' };
  fs.mkdirSync(paths.appDir, { recursive: true });
  if (path.resolve(running) !== path.resolve(paths.app)) {
    const tmp = `${paths.app}.tmp`;
    fs.copyFileSync(running, tmp);
    fs.chmodSync(tmp, 0o755);
    fs.renameSync(tmp, paths.app);
  }
  writeAtomic(paths.version, `${version}\n`);
  if (iconPng) writeAtomic(paths.icon, iconPng);
  writeAtomic(paths.menu, entry, 0o644);
  let shortcut = '';
  if (desktop && paths.shortcut && fs.existsSync(path.dirname(paths.shortcut))) {
    writeAtomic(paths.shortcut, entry, 0o755);
    shortcut = paths.shortcut;
  }
  return { ok: true, shortcut };
}

function removeLauncher({ paths }) {
  for (const f of [paths.shortcut, paths.menu, paths.icon, paths.version, paths.app]) {
    if (!f) continue;
    try {
      fs.unlinkSync(f);
    } catch {
      continue;
    }
  }
  try {
    fs.rmdirSync(paths.appDir);
  } catch {
    return { ok: true };
  }
  return { ok: true };
}

function launcherEnv({ packaged, env, home }) {
  const runningAppImage = () => (packaged ? env.APPIMAGE || '' : env.NODECONTROLLER_TEST_APPIMAGE || '');
  const homeDir = () => (!packaged && env.NODECONTROLLER_TEST_HOME ? env.NODECONTROLLER_TEST_HOME : home);
  const desktopDir = () => {
    const h = homeDir();
    const conf = env.XDG_CONFIG_HOME && path.isAbsolute(env.XDG_CONFIG_HOME) ? env.XDG_CONFIG_HOME : path.join(h, '.config');
    let text = '';
    try {
      text = fs.readFileSync(path.join(conf, 'user-dirs.dirs'), 'utf8');
    } catch {
      text = '';
    }
    return desktopDirFrom(h, text);
  };
  return { runningAppImage, homeDir, desktopDir, launcherPaths: () => launcherPaths(homeDir(), desktopDir()) };
}

module.exports = { launcherEnv, APP_ID, WM_CLASS, desktopDirFrom, launcherPaths, execQuote, desktopEntry, launcherStatus, installLauncher, removeLauncher };
