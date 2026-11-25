const { contextBridge } = require('electron');

contextBridge.executeInMainWorld({
  func: () => {
    const lock = (obj, name, value) => {
      try {
        Object.defineProperty(obj, name, { value, writable: false, configurable: false });
      } catch {}
    };
    const exec = Document.prototype.execCommand;
    lock(Document.prototype, 'execCommand', function execCommand(cmd, ...rest) {
      if (/^(copy|cut|paste)$/i.test(String(cmd))) return false;
      return exec.call(this, cmd, ...rest);
    });
    const query = Document.prototype.queryCommandSupported;
    lock(Document.prototype, 'queryCommandSupported', function queryCommandSupported(cmd) {
      if (/^(copy|cut|paste)$/i.test(String(cmd))) return false;
      return query.call(this, cmd);
    });
    if (typeof Clipboard === 'function') {
      for (const m of ['read', 'readText', 'write', 'writeText']) {
        lock(Clipboard.prototype, m, function denied() {
          return Promise.reject(new DOMException('The clipboard is off in Null Browser.', 'NotAllowedError'));
        });
      }
    }
    for (const type of ['copy', 'cut', 'paste']) {
      window.addEventListener(type, (ev) => {
        ev.preventDefault();
        ev.stopImmediatePropagation();
      }, true);
    }
  },
});
