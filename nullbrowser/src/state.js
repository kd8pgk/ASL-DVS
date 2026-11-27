const { createBlocklist } = require('./blocklist');

const crypto = require('node:crypto');

const st = {
  win: null, view: null, ses: null, lastInput: 0, commits: 0,
  leaving: 0, unsticking: null, notice: '', error: null, pendingCert: null,
  allowHttp: new Set(), upgraded: new Set(), trusted: new Set(),
  allowedSites: new Set(), litterbugIds: new Set(), blockedSite: '', nextPopup: '',
  pendingFile: null, pendingShot: null, dlAllowed: false, dlAsking: true,
  dlList: [], dlKnown: [], dlCands: [], dlProbed: new Map(), dlListFor: '', dlSeq: 0, dlScanSeq: 0, dlTotal: 0, dlSkipped: 0, dlProbing: 0, dlScanError: '',
  panelSpace: 0, dlWarn: false, dlPanelOpen: false, dlQueueOpen: false,
  shotSeq: 0, fileSeq: 0, bookmarks: [], bookmarkSeq: 0, pendingJs: null,
  pendingLeave: null, leaveSeq: 0,
  block: createBlocklist(), popLog: [], popFound: [], popSeq: 0, popFoundSeq: 0, popOpen: false, popPicking: false, popToken: '', popNote: '', blockHits: new Map(),
  viewTier: 4, viewAsking: true, viewNonce: crypto.randomBytes(16).toString('hex'), viewFetch: new Map(), viewBytes: 0, viewApplied: 0,
  watchdog: null,
};

module.exports = { st };
