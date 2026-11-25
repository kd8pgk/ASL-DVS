# Null Browser Mobile changelog

Current version: `0.1.0`. The app is in `nullbrowser-android/`; its version is `appVersion` in `nullbrowser-android/app/build.gradle.kts`. Newest entries first.

## 0.1.0 (2026-11-25)

A separate, scoped-down Android sibling of the desktop Null Browser, built on Android's WebView rather than Chromium directly, so it keeps what WebView lets an app control and drops what it doesn't.

- **One screen, one WebView.** Address bar, back/forward/reload, a blank start page, no tabs, no history, no saved settings. Everything (cookies, storage, cache, the downloads folder) is cleared when the app closes.
- **Third-party cookies dropped.** `CookieManager.setAcceptThirdPartyCookies(false)`. Camera, microphone, location and every other permission request is denied without asking.
- **https tried first.** A public `http://` address is tried as `https://` first; if that fails, a page offers **Open anyway (not secure)**, remembered only for that host until the app closes. A certificate error is refused outright, with no way past it (no trust-for-session yet).
- **No downloads except a PDF, audio or video file, content-sniffed, handed to your own app after you say Open.** The file is fetched into the app's private cache only after **Open**; its first bytes are checked against what it claims to be, the same checks as the desktop build. Everything else is refused.
- **Pop-ups.** A script opening a pop-up without a real tap is refused outright, with a notice. A link you tap that opens a new window loads in the same page instead.
- **No logging, no telemetry, no library beyond the Kotlin standard library and JUnit for tests** — Node Talker Mobile's own rules, carried over.

**Known gaps against the desktop build, by design, not oversight:** WebView gives an app no way to disable the JIT compiler, pass Chromium command-line switches, or read a separate sandboxed process's CPU usage — so there is no Faster-JavaScript-style toggle, no DNS-over-HTTPS or spell-check-dictionary-fetch hardening, and no CPU-pinned-while-idle watchdog signal. The RAM-folder machinery the desktop build needs (the launcher, `rammaid*`) doesn't apply either: Android already gives every app its own private, sandboxed storage, so there is no shared `$HOME` to leak into in the first place. Bookmarks import, per-site leave-and-clear storage, pop-ups accepted-but-starved instead of refused outright, and the watchdog's other four signals are planned for later versions, not dropped.
