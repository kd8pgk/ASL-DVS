# Null Browser changelog

Current version: `0.3.0`. The app is in `nullbrowser/`; its version is `version` in `nullbrowser/package.json`. Newest entries first.

## 0.3.0 (2026-11-25)

Bookmark import, kept only until you close the browser.

- **A star button on the toolbar** opens a panel of bookmarks. **Import…** opens a file picker for a bookmarks export (the `.html` file Chrome, Firefox, Edge and Safari all write in the same Netscape bookmark format); every `http://` and `https://` link in it is read in, with its title. Anything else in the file (a folder name, a `javascript:` or `ftp://` link) is skipped. Clicking a bookmark opens it and closes the panel; the ✕ by each one removes it.
- **Nothing is written to disk.** The file you pick is read once and never kept; the bookmarks themselves live only in the running browser's memory, capped at 500, and are gone the moment Null Browser closes — there is no file, setting or database to import them a second time from.
- **Fixed while testing:** a pop-up test reached into the running browser by always taking the first top-level window, which is only ever right when no pop-up (blocked or real) is open at that moment; three spots now find the actual shell window instead. The flakiness this caused was already there in 0.2.0's own pop-up tests; it surfaced here because the bookmark test runs right after them.
- **Tests.** The bookmark-file parser (folders, duplicate and non-http(s) links, HTML-escaped titles, a file-size cap, a bookmark-count cap) as unit tests; in a real window: importing a bookmarks file, importing the same file again, opening a bookmark, and removing one.

## 0.2.0 (2026-11-25)

Files handed to your own apps, pop-ups sent to nowhere, and sign-ins that need a pop-up.

- **PDF, audio and video open in your own apps, after asking.** Opening a PDF, a sound file or a video shows a bar: *Open report.pdf (PDF, 2.1 MB) in your PDF viewer?* with **Open** and **Cancel**. The file is fetched into the RAM folder (never your Downloads folder), and handed to the system's default app only after **Open**; **Cancel** deletes it. Before it is handed on, its first bytes are checked: a file that says it is a PDF but is not (a web page, a program) is deleted with a notice and not opened. Up to 512 MB, one file at a time. Every other download is still refused. Null Browser has no PDF viewer or media player of its own; the file is removed with the RAM folder when Null Browser quits, so to keep it, save a copy from the other app first.
- **Pop-ups accepted, then dropped.** A pop-up opened by a script no longer gets an error a site could notice: it opens as a hidden, muted window that loads nothing (every request it makes is cancelled) and is closed after 3 seconds. A bar says a pop-up was blocked.
- **Allow for this site.** The same bar has **Allow for this site**, for sign-ins that need a pop-up ("Sign in with…"). Until Null Browser closes, that site's pop-ups open as real windows (with no menu, no further pop-ups of their own, and the same certificate and address rules) and its third-party cookies are kept, in memory, so the sign-in can finish.
- **Fixed in the test:** the third-party test cookie lacked `Secure`, so Chromium refused it on its own and the "never sent back" check could not fail. It now uses `SameSite=None; Secure`, and the check fails if the cookie rule is turned off.
- **Tests.** The file type, content check, name and question rules as unit tests; in a real window: a PDF asks, **Cancel** opens nothing, **Open** hands it on, a fake PDF is refused, an mp3 asks, a script pop-up is dropped and its request never reaches the server, **Allow for this site** opens a real pop-up and keeps a third-party sign-in cookie.

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
- **The repo's look.** The toolbar, the blank page and the messages use the shared Node Control look: the Readex Pro font (built in, so no font is fetched), the amber title bar and the same colors and sizes as the tools and Node Controller Desktop.
- **One thing it cannot redirect yet: the font index.** Chromium carries its own font library, which keeps its own index of your installed fonts in `~/.cache/fontconfig` (file names of fonts only, nothing about what you browse). It is built the first time and then reused; it can be written before the browser has moved the home folder into RAM. The packaged build (0.5.0) will set the folders before the browser starts, which closes this. The test runs the browser once to build the index, then checks that a full browsing session adds or changes nothing in the home folder.
- **Honest.** The user agent is plain Chromium (the Electron and app names are taken out); nothing else is disguised. It is a private browser, not an anonymity tool: websites, your internet provider and your network still see your address and traffic.
- **Tests.** The address, https-first, private-network, third-party, cookie, scheme and switch rules and the RAM folder as unit tests; in a real window: the blank start, first-party cookies kept and third-party cookies dropped, permissions refused, a script pop-up refused, a clicked new-tab link opening in place, a download refused, a bad public certificate refused after the https upgrade, a site with no https opened anyway, a device on the local network trusted for the session, JIT off, and after quitting nothing left in the RAM folder or the real home folder.
