# Null Browser Mobile changelog

Current version: `0.8.0`. The app is in `nullbrowser-android/`; its version is `appVersion` in `nullbrowser-android/app/build.gradle.kts`. Newest entries first.

## 0.8.0 (2026-11-28)

**View**: pictures only, with boxes to turn more of the page back on, as in the desktop build (0.20.0).

- **Asked at each start**: **Pictures only**, **Full page** or **Choose…**. Nothing is saved; the answer lasts until the app closes. If you dismiss the question, pages show in full.
- **Tools → View** opens four tiered boxes: **Text**, **Links**, **The page's own layout, video and audio (still no scripts)** and **Scripts (the full page)**. Ticking one ticks the ones above it; unticking one unticks the ones below it. Changing a box reloads the page.
- **Pictures only, Pictures and text, Pictures, text and links.** The page's scripts never run in these three. Null Browser fetches the page's HTML itself (with the site's cookies, as the page view would), reads it with its own small scanner, and hands the page view a plain gallery in its place: one single column on a dark page, then, when ticked, headings, paragraphs and captions in page order, and links. The address bar, back and reload work as usual, because the gallery answers the page's own address.
- **What is read.** `img`, `srcset`, `picture`, lazy `data-src`, video posters, and text blocks; menus, footers, side bars, forms and hidden elements are skipped; a thumbnail inside a link to a bigger picture is replaced by the bigger one; duplicates and pictures under 120 pixels are dropped.
- **How the pictures are fetched.** By the app itself, as they come into view, with no cookies and no referer; each must start like a JPG, PNG, GIF, WebP or AVIF (SVG and anything else is dropped); at most 400 pictures, 25 MB each and 300 MB in all per page. **Images: Off** still wins. Tap a picture to see it larger; the arrows move to the next one.
- **Page layout and media, no scripts** turns off JavaScript in the page view and loads the real page.
- **A strict policy on the gallery**: no frames, no fonts, no media, scripts only the gallery's own, pictures only from the app itself.
- **Known limits.** Android's page view has no way to read computed styles without running the page, so hidden-by-stylesheet elements and CSS background pictures are not seen in the gallery, which the desktop build does see. A file that is not a page (PDF, audio, video, picture) passes straight to the page view; anything else that is not HTML (an SVG, for example) is refused. The block list's **Find** and **Pick** need scripts, so they do nothing in the layout level.
- **Tests.** Unit tests for the tiers, the picture check, the HTML scanner and the cleaning of what it finds (hidden, navigation, lazy and `picture` pictures, entities, relative and bad addresses) and the gallery page (everything a site gave is escaped). The fetching and the page wiring are compiled by CI but not yet run on a phone.

## 0.7.0 (2026-11-28)

Pop-ups: see where they point and block them for one run, as in the desktop build (0.19.0).

- **Tools → Pop-ups** opens a full-screen sheet. The old **Line** button is now **Tools**, because the row holds more than the line settings.
- **Tried this run.** Every pop-up window a page tried to open and every jump to another site, with the site it came from and the address it pointed at (`dropped`, `blocked`, `went` or `tapped`). Each line has **Block <host>**. A pop-up without a tap used to be refused with no trace of where it pointed; it is now taken into a small window that has no scripts and can load nothing, its address is recorded, and it is destroyed after 3 seconds (at most 3 at once).
- **On this page.** **Find on this page** lists elements fixed over the page that cover a large part of it or sit on a high layer, and frames from other sites, with **Show** (outlines it on the page), **Hide** and **Block <host>**. **Pick** closes the sheet so you can tap the pop-up on the page; the sheet comes back with it listed. A pop-up inside a frame from another site can be listed (by its address) but not picked from inside, because Android's page view gives an app no way into another site's frame.
- **Block list.** Host rules cancel every request to the host and its subdomains (everything except the page itself), refuse a jump to it, and drop a pop-up window aimed at it. Element rules hide matching elements on a site with injected CSS. **Import list…** adds hosts, hosts-file lines, `||host^` and `site##selector` from a text file you pick (up to 5 MB and 20,000 rules). A page's own site cannot be blocked from the sheet.
- **One run only.** The list, the log and the counts are in memory and are gone when the app closes. ✕ clears the log and what the page found, and keeps the list. Nothing is written.
- **Safety.** What a page reports about an element is cleaned and length-limited before it is shown; a rule is only made from that stored list, never from a string a page sends; selectors may not hold braces, semicolons, `@`, `url(` or the whole page (`body`, `html`, `*`).
- **Known limits.** Element rules reach the page and not frames of other sites (use a host rule for those). Android's page view has no way to run a script before the page's own scripts, so a rule shows its effect a moment after the page starts, not before.
- **Tests.** Unit tests for the JSON reader, the block list, the cleaning of what a page reports and the quoting of injected script. The sheet and the page wiring are compiled by CI but not yet run on a phone.

## 0.6.0 (2026-11-26)

A screenshot, saved only when you say so, as in the desktop build (0.13.0).

- **The ✕ button clears everything.** It used to go to the blank page only. Now it wipes this run the way the desktop ✕ does (0.14.0): pages, cookies, storage, cache, form data, history, sign-ins, allowed sites, queued images and downloads, then goes to the blank page. A screenshot waiting in quarantine is kept. Closing the app still clears the quarantine too.
- **Screenshot** (in the **Line** row). Makes a PDF of the whole web page, including the parts above and below the screen, using Android's own print path, with no print dialog shown. Tick **Include toolbar** first (off by default) to make a PDF of the screen as it is now, toolbar included; that option captures what is on screen, not the page's hidden parts.
- **Checked before anything is saved.** The PDF is written to the app's private cache (a `quarantine` folder), then checked: it must start with `%PDF-` and end with `%%EOF`, have a readable page, be under 64 MB, and match the SHA-256 recorded when it was made. A file that fails is deleted and a notice says why.
- **Saved only on Save.** A bar asks before anything is written. Save copies the PDF to your Downloads folder as `Null-Browser-YYYY-MM-DD-HHMMSS.pdf`, with no site name. Android 10 and later use the Downloads collection (MediaStore), which needs no permission. Android 8 and 9 ask for storage permission the first time you save; if you refuse, the screenshot is discarded. Cancel deletes it.
- **Size.** No library is added (framework classes only). The APK size change is measured by the build and recorded in the pull request.
- **Tests.** Unit tests for the checks and the file names. The print and screen-copy paths are compiled by CI but not yet run on a phone.

## 0.5.0 (2026-11-25)

Tell sites less, and never anything false, as in the desktop build (0.12.0).

- **The phone's model and build number are no longer in the user agent.** Android's page view sent them (for example `Pixel 7 Build/UQ1A.240205.004`) on every request. Now only Linux, the Android version and the page-view marker are kept, with the short Chrome version Chrome itself sends. Null Browser's own fetches use the same.
- **Line speed, memory, CPU cores and battery** are no longer readable by page scripts, and a script asking for the detailed browser hints gets only the basic brand, mobile and platform values (the same page script as the desktop build, injected when a page starts and finishes loading).
- **Known limits.** Android's page view gives an app no way to choose the languages it sends, to trim the Referer, or to refuse the detailed hint headers without an extra library, so those follow the page view's own rules (the Referer across sites is the site name only unless the page asks for more).
- **Tests.** The user-agent trim as unit tests.

## 0.4.0 (2026-11-25)

Made for dial-up, as in the desktop build (0.11.0).

- **Slow mode** (the new **Line** button: **Slow: Auto / On / Off**). Auto turns it on when a page takes over 3 seconds to show or images arrive at under about 16 KB/s. Nothing is saved: every start is Auto.
- **Images in viewing order, one at a time.** In slow mode the page view's own image loading is held back while the text and layout arrive; Null Browser then fetches the page's pictures itself, one after another, in the order you read them (on screen top to bottom, then down the page, then above, small images and side ads last), and puts each in place as it lands. Scrolling moves what you are looking at to the front. When the pictures are done, anything left (backgrounds) loads normally. A status row shows the progress and line speed, with **Stop images**.
- **A dropped line costs nothing already received.** Pictures and PDF, audio or video files resume from the byte they stopped at (up to five tries, waiting 2 to 32 seconds).
- **Less to wait for.** In slow mode web fonts, link prefetch and link pings are answered empty, and video and audio are not preloaded.
- **Images: On / Off** for text only, **Save-Data** (off by default; added to page loads and Null Browser's own fetches) and **Read ahead** (off by default: when a page is done, the next page's pictures are fetched into memory so they show at once).
- **Known limits.** Android's page view cannot be told to hold one image and let another go, so in slow mode all picture loading goes through Null Browser's own fetcher; a site whose rules forbid in-page (`data:`) images gets its pictures the normal way once the queue is done. Save-Data cannot be added to the page view's own requests for pictures and scripts.
- **Tests.** Unit tests for the line meter, the viewing order, resuming, the next-page link and the page's picture list.

## 0.3.0 (2026-11-25)

The clipboard is off, as in the desktop build.

- **No copy, cut, paste or share.** Long-pressing text in a page or in the address bar no longer opens the copy and paste menu; the keyboard's own paste, cut and copy commands and a hardware keyboard's Ctrl+C/X/V, Ctrl+Insert, Shift+Insert and Shift+Delete do nothing; pasted images and dropped text are refused. Type addresses by hand.
- **Pages cannot use the clipboard.** The same small script as the desktop build turns off `execCommand` copy, cut and paste, the Clipboard API and the copy, cut and paste events in the page.
- **A backstop.** Android's WebView gives an app no supported way to run that script before a page's own code, or in every frame, without an extra library, so anything a page still manages to put on the clipboard while Null Browser is open is cleared the moment it lands.
- **Known limit.** A keyboard app's own clipboard history (for example Gboard's clipboard suggestions) types the text in like typing, and an app cannot tell the two apart.
- **Tests.** The clipboard keys as a unit test.

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
