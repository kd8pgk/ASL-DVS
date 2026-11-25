const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const LN = require('../src/launcher');

function home() {
  const h = fs.mkdtempSync(path.join(os.tmpdir(), 'nchome-'));
  fs.mkdirSync(path.join(h, 'Desktop'));
  const img = path.join(h, 'Downloads', 'NodeController-1.0.0.AppImage');
  fs.mkdirSync(path.dirname(img));
  fs.writeFileSync(img, 'fake appimage');
  return { h, img, paths: LN.launcherPaths(h, path.join(h, 'Desktop')) };
}

test('the launcher files go in the standard user folders', () => {
  const p = LN.launcherPaths('/home/jim', '/home/jim/Desktop');
  assert.equal(p.menu, '/home/jim/.local/share/applications/nodecontroller.desktop');
  assert.equal(p.icon, '/home/jim/.local/share/icons/hicolor/256x256/apps/nodecontroller.png');
  assert.equal(p.app, '/home/jim/.local/share/node-controller/NodeController.AppImage');
  assert.equal(p.shortcut, '/home/jim/Desktop/nodecontroller.desktop');
  assert.equal(LN.launcherPaths('/h', '').shortcut, '');
});

test('the desktop entry quotes the path and names the window class', () => {
  const t = LN.desktopEntry({ exec: '/home/jim smith/.local/share/node-controller/NodeController.AppImage', version: '0.12.0' });
  assert.match(t, /^\[Desktop Entry\]\n/);
  assert.match(t, /\nExec="\/home\/jim smith\/\.local\/share\/node-controller\/NodeController\.AppImage"\n/);
  assert.match(t, /\nName=Node Controller Desktop\n/);
  assert.match(t, /\nIcon=nodecontroller\n/);
  assert.match(t, /\nStartupWMClass=nodecontroller\n/);
  assert.match(t, /\nTerminal=false\n/);
  assert.match(t, /\nX-NodeController-Version=0\.12\.0\n/);
  assert.equal(LN.execQuote('/a/100%/x'), '"/a/100%%/x"');
  for (const bad of ['/a/"b', '/a/`b`', '/a/$HOME', '/a\\b', '/a\nb', '']) assert.equal(LN.desktopEntry({ exec: bad, version: '1' }), '', bad);
});

test('install copies the AppImage, writes the menu entry, icon and desktop shortcut; remove takes them away', () => {
  const { img, paths } = home();
  let st = LN.launcherStatus(paths, img, '1.0.0');
  assert.deepEqual([st.available, st.installed, st.fromInstalled], [true, false, false]);
  const r = LN.installLauncher({ paths, running: img, iconPng: Buffer.from('png'), version: '1.0.0' });
  assert.equal(r.ok, true);
  assert.equal(fs.readFileSync(paths.app, 'utf8'), 'fake appimage');
  assert.equal(fs.statSync(paths.app).mode & 0o777, 0o755);
  assert.equal(fs.statSync(paths.shortcut).mode & 0o777, 0o755);
  assert.match(fs.readFileSync(paths.menu, 'utf8'), new RegExp(`Exec="${paths.app.replace(/[.]/g, '\\.')}"`));
  assert.equal(fs.readFileSync(paths.icon, 'utf8'), 'png');
  st = LN.launcherStatus(paths, img, '1.0.0');
  assert.deepEqual([st.installed, st.installedVersion, st.newer, st.shortcut], [true, '1.0.0', false, true]);
  st = LN.launcherStatus(paths, img, '1.1.0');
  assert.equal(st.newer, true);
  assert.equal(LN.launcherStatus(paths, paths.app, '1.0.0').fromInstalled, true);
  LN.removeLauncher({ paths });
  for (const f of [paths.app, paths.menu, paths.icon, paths.shortcut, paths.version, paths.appDir]) assert.equal(fs.existsSync(f), false, f);
});

test('installing from the installed copy keeps it, and no desktop folder means no shortcut', () => {
  const { h, img } = home();
  const paths = LN.launcherPaths(h, path.join(h, 'NoDesktop'));
  LN.installLauncher({ paths, running: img, iconPng: null, version: '1.0.0' });
  const r = LN.installLauncher({ paths, running: paths.app, iconPng: null, version: '1.0.1' });
  assert.deepEqual(r, { ok: true, shortcut: '' });
  assert.equal(fs.readFileSync(paths.app, 'utf8'), 'fake appimage');
  assert.equal(fs.readFileSync(paths.version, 'utf8').trim(), '1.0.1');
});

test('install refuses when not running from an AppImage', () => {
  const { paths } = home();
  assert.match(LN.installLauncher({ paths, running: '', version: '1' }).error, /not running from an AppImage/);
  assert.equal(LN.launcherStatus(paths, '', '1').available, false);
});

test('the desktop folder comes from user-dirs.dirs, like xdg-user-dir, without running anything', () => {
  assert.equal(LN.desktopDirFrom('/home/jim', 'XDG_DESKTOP_DIR="$HOME/Bureau"\nXDG_MUSIC_DIR="$HOME/Music"\n'), '/home/jim/Bureau');
  assert.equal(LN.desktopDirFrom('/home/jim', '# comment\n  XDG_DESKTOP_DIR="/data/desk"\n'), '/data/desk');
  assert.equal(LN.desktopDirFrom('/home/jim', 'XDG_DESKTOP_DIR="$HOME/"\n'), '/home/jim/Desktop');
  assert.equal(LN.desktopDirFrom('/home/jim', 'XDG_DESKTOP_DIR="relative"\n'), '/home/jim/Desktop');
  assert.equal(LN.desktopDirFrom('/home/jim', ''), '/home/jim/Desktop');
});

test('the launcher environment: packaged uses APPIMAGE and the real home, tests use their own', () => {
  const h = fs.mkdtempSync(path.join(os.tmpdir(), 'ncenv-'));
  fs.mkdirSync(path.join(h, '.config'));
  fs.writeFileSync(path.join(h, '.config', 'user-dirs.dirs'), 'XDG_DESKTOP_DIR="$HOME/Skrivbord"\n');
  const real = LN.launcherEnv({ packaged: true, env: { APPIMAGE: '/a/x.AppImage', NODECONTROLLER_TEST_HOME: '/nope', NODECONTROLLER_TEST_APPIMAGE: '/nope' }, home: h });
  assert.equal(real.runningAppImage(), '/a/x.AppImage');
  assert.equal(real.homeDir(), h);
  assert.equal(real.desktopDir(), path.join(h, 'Skrivbord'));
  assert.equal(real.launcherPaths().shortcut, path.join(h, 'Skrivbord', 'nodecontroller.desktop'));
  const dev = LN.launcherEnv({ packaged: false, env: { APPIMAGE: '/a/x.AppImage', NODECONTROLLER_TEST_HOME: h, NODECONTROLLER_TEST_APPIMAGE: '/t/y.AppImage' }, home: '/home/other' });
  assert.equal(dev.runningAppImage(), '/t/y.AppImage');
  assert.equal(dev.homeDir(), h);
  assert.equal(LN.launcherEnv({ packaged: false, env: {}, home: h }).runningAppImage(), '');
});
