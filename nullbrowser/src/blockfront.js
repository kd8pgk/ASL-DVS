const { ipcRenderer } = require('electron');

try {
  const host = location.hostname;
  if (host && /^https?:$/.test(location.protocol)) {
    const css = ipcRenderer.sendSync('nb-block-css', host);
    if (css) {
      const put = () => {
        const s = document.createElement('style');
        s.setAttribute('data-nb-block', '1');
        s.textContent = css;
        (document.head || document.documentElement).appendChild(s);
      };
      if (document.documentElement) {
        put();
      } else {
        const mo = new MutationObserver(() => {
          if (document.documentElement) {
            mo.disconnect();
            put();
          }
        });
        mo.observe(document, { childList: true });
      }
    }
  }
} catch {}
