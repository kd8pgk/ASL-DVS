const { ipcRenderer } = require('electron');

if (window.top === window) {
  let active = false;
  let timer = null;
  let observer = null;

  const report = (withLinks) => {
    const items = [];
    const imgs = document.images || [];
    for (let i = 0; i < imgs.length && items.length < 500; i += 1) {
      const img = imgs[i];
      const src = img.currentSrc || img.src;
      if (!src) continue;
      const r = img.getBoundingClientRect();
      items.push({ src: String(src), top: Math.round(r.top), x: Math.round(r.left), w: Math.round(r.width), h: Math.round(r.height) });
    }
    const out = { vh: window.innerHeight, vw: window.innerWidth, items };
    if (withLinks) {
      const links = [];
      const nodes = document.querySelectorAll('a[href], link[rel][href]');
      for (let i = 0; i < nodes.length && links.length < 300; i += 1) {
        const n = nodes[i];
        links.push({ rel: String(n.getAttribute('rel') || ''), href: String(n.href || ''), text: String(n.textContent || n.getAttribute('aria-label') || n.getAttribute('title') || '').trim().slice(0, 40) });
      }
      out.links = links;
    }
    return out;
  };

  const send = (withLinks) => {
    try {
      ipcRenderer.send('nb-report', report(withLinks));
    } catch {}
  };

  const soon = () => {
    if (!active || timer) return;
    timer = setTimeout(() => {
      timer = null;
      send(false);
    }, 250);
  };

  const quiet = (el) => {
    if (!el || (el.tagName !== 'VIDEO' && el.tagName !== 'AUDIO')) return;
    if (el.dataset.nbQuiet) return;
    el.dataset.nbQuiet = '1';
    el.preload = 'none';
    el.autoplay = false;
    el.removeAttribute('autoplay');
  };

  const quietAll = () => {
    const list = document.querySelectorAll('video, audio');
    for (let i = 0; i < list.length; i += 1) quiet(list[i]);
  };

  const start = () => {
    quietAll();
    if (observer) return;
    observer = new MutationObserver((records) => {
      for (const r of records) {
        for (const n of r.addedNodes) {
          if (n.nodeType !== 1) continue;
          quiet(n);
          if (n.querySelectorAll) for (const m of n.querySelectorAll('video, audio')) quiet(m);
        }
      }
      soon();
    });
    observer.observe(document, { childList: true, subtree: true });
  };

  ipcRenderer.on('nb-line', (e, msg) => {
    active = Boolean(msg && msg.active);
    if (active) {
      if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
      else start();
    }
    if (msg && msg.reloadImages) {
      const imgs = document.images || [];
      for (let i = 0; i < imgs.length; i += 1) {
        const img = imgs[i];
        if (img.complete && img.naturalWidth > 0) continue;
        const srcset = img.getAttribute('srcset');
        const src = img.getAttribute('src');
        if (srcset !== null) img.setAttribute('srcset', srcset);
        if (src !== null) {
          img.removeAttribute('src');
          img.setAttribute('src', src);
        }
      }
    }
    if (msg && msg.report) send(Boolean(msg.links));
  });

  try {
    const now = ipcRenderer.sendSync('nb-line-now');
    if (now && now.active) {
      active = true;
      start();
    }
  } catch {}

  window.addEventListener('scroll', soon, { passive: true, capture: true });
  window.addEventListener('resize', soon, { passive: true });
}
