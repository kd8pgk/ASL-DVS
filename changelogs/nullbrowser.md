# Null Browser changelog

Current version: `0.1.0`. The app is in `nullbrowser/`; its version is `version` in `nullbrowser/package.json`. Newest entries first.

## 0.1.0 (2026-11-25)

The first build: a private browser that keeps nothing.

- **One window, one page.** Back, forward, reload (stop while loading), a blank-page button and an address bar. It starts on a blank page. There is no search box: type a web address (a bare name gets `https://`).
- **Nothing kept.** The page's cookies, cache, logins and site storage are in memory only and gone when the window closes. Chromium's own files, and the home, config, cache and temporary folders it would use, are in a RAM folder (`/dev/shm/null-browser-…`) that is removed when the browser quits, and at the next start if a crash left one. No log file, crash reports, telemetry, updater, history or saved settings.
- **Blocked.** Downloads are off (a notice says so). Camera, microphone, location, notifications and every USB, serial, HID or Bluetooth device are denied without asking. Only http and https pages open; file, chrome and other built-in addresses are refused.
- **https first.** A public `http://` address is tried as `https://` first. If the site has no secure version, a page says so, with **Open anyway (not secure)**; the address bar marks plain http as **Not secure** and https as **Secure**. Addresses on your own network stay as typed.
- **Certificates.** A certificate error on a public site is refused with no way past it. A device on your own network (router, NAS, node) shows its fingerprint with **Trust for this session**, which lasts until the browser closes.
- **Third-party cookies accepted, then dropped.** A site on another domain can set its cookie without an error, but it is never kept or sent back, so it cannot follow you from page to page. First-party cookies work normally, in memory.
- **Pop-ups.** A pop-up opened by a script gets nothing. A link you click that would open a new tab opens in the same page instead.
- **Harder to attack, and nothing on disk from the graphics driver.** JavaScript runs without the JIT compiler (`--jitless`), which closes off a whole class of browser exploits, at some cost in speed; WebAssembly does not run. GPU acceleration is off, so pages are drawn in software and no graphics driver writes a shader cache to your home folder.
- **Honest.** The user agent is plain Chromium (the Electron and app names are taken out); nothing else is disguised. It is a private browser, not an anonymity tool: websites, your internet provider and your network still see your address and traffic.
- **Tests.** The address, https-first, private-network, third-party, cookie, scheme and switch rules and the RAM folder as unit tests; in a real window: the blank start, first-party cookies kept and third-party cookies dropped, permissions refused, a script pop-up refused, a clicked new-tab link opening in place, a download refused, a bad public certificate refused after the https upgrade, a site with no https opened anyway, a device on the local network trusted for the session, JIT off, and after quitting nothing left in the RAM folder or the real home folder.
