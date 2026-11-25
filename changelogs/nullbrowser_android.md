# Null Browser Mobile changelog

Current version: `0.2.0`. The app is in `nullbrowser-android/`; its version is `appVersion` in `nullbrowser-android/app/build.gradle.kts`. Newest entries first.

## 0.2.0 (2026-11-25)

An audit for errors and efficiency; no new features.

- **The back gesture now goes back a page instead of closing the app.** With Android 16 (the app targets it), the system no longer calls the old back handler for the back gesture, so a swipe back closed the app and, since closing wipes everything, lost the whole session. Back now uses Android's own back-gesture dispatcher (Android 13 and later; the old handler is kept for older phones): it leaves full-screen video first, then goes back through the page history, and only closes the app when there is nothing to go back to.
- **Data is wiped when the app starts, not only when it closes.** Android does not promise to run the close step when you swipe an app away or the phone ends it for memory, so cookies and storage could survive into the next run. They are now cleared at start too.
- **Full-screen video works.** A video's full-screen button used to do nothing; it now fills the screen (system bars hidden), and back leaves it.
- **A typed `http://` address is upgraded to https too.** Before, only links tapped inside a page were; an address typed or retried in the address bar went out as plain http. The "no secure version" page is now matched by host, so it shows reliably instead of a generic error when the address had a trailing slash added.
- **A certificate error on one image or script no longer replaces the whole page** with the "certificate is not valid" screen. That resource is still refused; the screen appears only when the page itself fails.
- **A crashed page recovers.** After the page's process died, the old WebView was left in place and could not be used again; the app now starts over cleanly (and wipes, as on any restart).
- **Files without the right extension open in the right app.** A PDF, song or video served under a name like `download` is given the matching extension, and the viewer is told the type, so Android picks the right app instead of none.
- **Downloads follow redirects** (up to five; never from https down to http) and refuse a file the server already says is over 512 MB before fetching any of it. The content check reads the first 64 bytes reliably even when they arrive in pieces, and it runs off the main thread.
- **Leaks closed.** The throwaway WebView used to catch a tapped new-window link is destroyed after use, the main WebView is destroyed on close, and nothing touches the screen after the app has closed.
- **Smaller costs.** Regular expressions are built once, not on every navigation or keystroke.
- **Tests.** The extension rule as a unit test.

## 0.1.0 (2026-11-25)

A separate, scoped-down Android sibling of the desktop Null Browser, built on Android's WebView rather than Chromium directly, so it keeps what WebView lets an app control and drops what it doesn't.

- **One screen, one WebView.** Address bar, back/forward/reload, a blank start page, no tabs, no history, no saved settings. Everything (cookies, storage, cache, the downloads folder) is cleared when the app closes.
- **Third-party cookies dropped.** `CookieManager.setAcceptThirdPartyCookies(false)`. Camera, microphone, location and every other permission request is denied without asking.
- **https tried first.** A public `http://` address is tried as `https://` first; if that fails, a page offers **Open anyway (not secure)**, remembered only for that host until the app closes. A certificate error is refused outright, with no way past it (no trust-for-session yet).
- **No downloads except a PDF, audio or video file, content-sniffed, handed to your own app after you say Open.** The file is fetched into the app's private cache only after **Open**; its first bytes are checked against what it claims to be, the same checks as the desktop build. Everything else is refused.
- **Pop-ups.** A script opening a pop-up without a real tap is refused outright, with a notice. A link you tap that opens a new window loads in the same page instead.
- **No logging, no telemetry, no library beyond the Kotlin standard library and JUnit for tests** — Node Talker Mobile's own rules, carried over.

**Known gaps against the desktop build, by design, not oversight:** WebView gives an app no way to disable the JIT compiler, pass Chromium command-line switches, or read a separate sandboxed process's CPU usage — so there is no Faster-JavaScript-style toggle, no DNS-over-HTTPS or spell-check-dictionary-fetch hardening, and no CPU-pinned-while-idle watchdog signal. The RAM-folder machinery the desktop build needs (the launcher, `rammaid*`) doesn't apply either: Android already gives every app its own private, sandboxed storage, so there is no shared `$HOME` to leak into in the first place. Bookmarks import, per-site leave-and-clear storage, pop-ups accepted-but-starved instead of refused outright, and the watchdog's other four signals are planned for later versions, not dropped.
