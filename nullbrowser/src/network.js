const crypto = require('node:crypto');
const { app, BrowserWindow, WebContentsView, Menu, ipcMain, session, screen, shell, dialog, net, protocol } = require('electron');
const P = require('./policy');
const { st } = require('./state');
const shared = require('./ctx');

function topUrlOf(details) {
  try {
    if (details.frame && details.frame.top && details.frame.top.url) return details.frame.top.url;
  } catch {
    return shared.pageUrl();
  }
  return shared.pageUrl();
}

function litterbugRequest(details) {
  return st.litterbugIds.has(details.webContentsId);
}

function thirdParty(details) {
  if (details.resourceType === 'mainFrame') return false;
  const top = topUrlOf(details);
  if (st.allowedSites.has(P.siteOf(P.hostOf(top)))) return false;
  return P.isThirdParty(details.url, top);
}

let langCache = '';

function pageLang() {
  if (!langCache) langCache = P.firstLanguage(app.getPreferredSystemLanguages ? app.getPreferredSystemLanguages() : [], app.getLocale());
  return langCache;
}

function hardenShell(s) {
  s.setPermissionRequestHandler((wc, permission, callback) => callback(false));
  s.setPermissionCheckHandler(() => false);
  s.setDevicePermissionHandler(() => false);
  s.setSpellCheckerEnabled(false);
  s.setSpellCheckerLanguages([]);
  s.webRequest.onBeforeRequest((details, callback) => callback({ cancel: !/^(file|data):/i.test(details.url) }));
}

function fingerprint(cert) {
  const body = String((cert && cert.data) || '').replace(/-----[A-Z ]+-----/g, '').replace(/\s+/g, '');
  const der = Buffer.from(body, 'base64');
  return der.length ? crypto.createHash('sha256').update(der).digest('hex') : '';
}

function showFingerprint(hex) {
  return (hex.toUpperCase().match(/.{1,2}/g) || []).join(':');
}

module.exports = { topUrlOf, litterbugRequest, thirdParty, pageLang, hardenShell, fingerprint, showFingerprint };
