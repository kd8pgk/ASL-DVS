# Null Browser changelog

Current version: `0.20.0`. The app is in `nullbrowser/`; its version is `version` in `nullbrowser/package.json`. Newest entries first.

## 0.20.0 (2026-11-27)

**View**: pictures only, with boxes to turn more of the page back on. PNG and GIF join the downloadable types.

- **Asked at each start**, next to the downloads question: **Pictures only**, **Full page** or **Choose…**. Nothing is saved; the answer lasts until Null Browser closes. Until you answer, pages show in full as before.
- **View** (toolbar) opens four boxes. Each one turns more back on and ticks the ones above it; unticking one unticks the ones below it. Changing a box reloads the page.
  - **Pictures only** (nothing ticked): one single column of pictures on a dark page, with no text, links or anything else.
  - **Text**: headings, paragraphs and captions come back, in page order between the pictures. Menus, footers, side bars and forms stay out.
  - **Links**: links in the text, and pictures that link to another page, work again; leaving the site still asks first.
  - **The page's own layout, video and audio**: the real page with its styles, but still no scripts.
  - **Scripts**: the full page.
- **Scripts never run below the full page.** The page's own security policy and report addresses are replaced by a strict one while a picture view is on (no scripts, no frames, no fonts, no media, pictures only from the browser itself), so the page's pictures are not fetched twice and ads, trackers and pop-ups never start. The block list from 0.19.0 still applies when scripts are on.
- **How the pictures are found.** The page's HTML and styles load; the browser reads `img`, `srcset`, `picture`, lazy `data-src`, video posters and large CSS backgrounds in page order, uses the bigger picture when a thumbnail links to one, and drops duplicates and anything under 120 pixels. It then replaces the page with the gallery in place, so the address bar, back button and history work as usual.
- **How they are fetched.** One at a time as you scroll, by the browser itself with no cookies and no referer. A file must start like a JPG, PNG, GIF, WebP or AVIF; anything else (SVG included) is dropped. Limits: 400 pictures, 25 MB each, 300 MB in all per page. **Images: Off** in the Line row still wins.
- **Click a picture** to see it larger; the arrow keys move to the next one, Esc closes it. With Links on, a linked picture shows an **Open link** button.
- **PNG and GIF** can now be listed and downloaded like the other types, with structure checks (PNG: signature, header, data, exact end; GIF: header, size, trailer).
- **Fewer false refusals on pictures.** Hidden-code checks for `#!/` and program headers now look only at the first and last kilobyte of a JPG, PNG, GIF or WebP, because those bytes turn up by chance deep inside compressed data and large pictures were refused for it. Every other type is scanned all the way through, as before.
- Not covered: the Download list has nothing to list in the picture views (the pictures come from the browser itself); a page that needs scripts to show anything is empty until you tick **Scripts**.

## 0.19.0 (2026-11-27)

Pop-ups: find them, and block them with a list that lasts one run.

- **Pop-ups** button (toolbar) opens a panel with three parts.
  - **Tried this run.** Every pop-up window a page tried to open, and every jump to another site, with the site it came from and the host it pointed at (`dropped`, `blocked`, `opened` or `asked`). Each line has **Block host**. Nothing was shown about the target before; the old bar only named the site that tried.
  - **On this page.** **Find on this page** looks in every frame, including ads from other sites, for elements fixed over the page that cover a large part of it, sit on a high layer, or are cross-site frames. Each row names the element (an id or class where there is one), the frame's host and the hosts inside it, with **Show** (outlines it on the page for two seconds), **Hide** and **Block <host>**. **Pick** lets you click the pop-up on the page itself (Esc cancels), which finds fake dialogs and click traps the scan misses.
  - **Block list.** The rules you made, with how many requests each blocked host stopped, and **✕** to remove one. **Import list…** adds hosts and element rules from a text file: plain hosts, hosts-file lines, `||host^`, and `site##selector`; other lines are skipped (up to 5 MB and 20,000 rules).
- **Host rules** cancel every request to the host and its subdomains (frames, scripts, images, anything but the page you navigated to), drop a pop-up window aimed at it before a window is made, and stop a jump to it without asking. A site's own host cannot be blocked from the panel, so a click cannot lock you out of a page.
- **Element rules** hide matching elements on a host and its subdomains. They are applied by a small frame script as each page and frame loads (from a list built once, not rebuilt per page) and at once on the page you are looking at. Selectors are checked first: no braces, semicolons, `@`, `url(` or the whole page (`body`, `html`, `*`).
- **Run-long.** The list, the log and the counts live in memory only and are gone when Null Browser closes; the ✕ button clears the log but keeps the list, like bookmarks. Nothing is exported or written. What a page reports about an element is cleaned and length-limited before it is shown, and a rule is only made from the list the browser itself built.
- Not covered: JavaScript `alert()` loops (still held back by the safe-dialog setting) and server redirects of the page itself to a listed host.

## 0.18.0 (2026-11-27)

**Add to menu**, the same install as Node Controller Desktop.

- A toolbar button, shown only when Null Browser runs from an AppImage. **Add to menu** copies the AppImage to `~/.local/share/null-browser/`, writes the menu entry `~/.local/share/applications/nullbrowser.desktop` (name Null Browser, category Network and Web Browser), the icon under `~/.local/share/icons/hicolor/256x256/apps/` and the same entry on your Desktop folder (taken from your `user-dirs.dirs`, so a renamed Desktop folder works). The entry is then in Caja and Thunar menus, and the desktop icon starts the copy.
- The button then reads **Remove from menu**, which deletes all of those files. If you run a newer AppImage than the menu copy, it reads **Update menu copy**.
- **Written only when you press the button**, a third deliberate exception next to the screenshot and downloads. It writes to your real home folder (never the RAM folder, which it refuses), with the usual atomic writes. Nothing is written at start-up, and a run that is not an AppImage shows no button.
- The window class is `nullbrowser`, so docks group the window with the menu entry.

## 0.17.2 (2026-11-27)

A **RAM folder** button in the toolbar.

- **RAM folder** opens this run's RAM folder (`/dev/shm/null-browser-…`) in your default file manager (Caja, Thunar and others), and a notice shows its path. It holds the run's cache and session data, screenshots waiting in `quarantine/`, and files being checked.
- **Nothing is written by the browser.** It only hands the folder to the system, the way Open hands a PDF on. A file manager may keep the path in its own history. The folder is still removed when Null Browser closes.

## 0.17.1 (2026-11-27)

Screenshots and downloads reach your real Downloads folder again, the JIT button restarts properly, and the download list is no longer hidden behind the page.

- **Screenshots and downloads saved into the RAM folder.** The AppImage launcher points `HOME` at the RAM folder before the app starts, and the app took "your home" from `HOME`, so Save and the download queue wrote to `Downloads` inside the RAM folder, which is deleted when Null Browser closes. The launcher now passes the real home folder (`NULLBROWSER_REAL_HOME`) and the app uses it. A source run was never affected, which is why the tests missed it. Pressing Save still asks nothing more: the bar is the question, and the file goes to Downloads with a "Saved … to your Downloads folder" notice.
- **JIT: Off / On restarts as asked.** The restart ran the program from inside the AppImage's temporary mount, with the old RAM folder, `HOME` and `TMPDIR` still set, and could not come back as a clean new run. It now starts the AppImage itself (or the launcher script of an unpacked build), with the old RAM folder left out of its environment, so the new run builds its own RAM folder and starts with the other JIT setting. The browser still closes and reopens as one step; nothing else is kept.
- **The download list, queue and bookmarks panels are visible.** They sit in the toolbar window and the page was drawn over them. The page now moves down below an open panel and back up when it closes.
- The smoke test now runs a launcher-style start (home pointing at the RAM folder), saves a screenshot to the real Downloads folder and follows a JIT restart through a stand-in AppImage; the package check looks for the real-home line in the launcher.

## 0.17.0 (2026-11-27)

The Download list finds more files, and says when it could not read a page.

- **WebP added.** The list and the download checks now cover WebP as well: PDF, MP3, WebM, MP4, JPG, WAV, MPEG and WebP. A WebP must have a RIFF/WEBP header, image data and a size that fits the file.
- **Long pages work.** The page scan used to stop after 300 elements of any kind, so a page with a menu and many pictures never reached its files further down. Now only likely files are collected, up to 1,000 links, 600 media addresses and 400 other links per frame. The list still shows at most 200 files and now says "Showing the first 200 of N files".
- **More ways to name a file.** Links are listed when the path ends in a file type, when the link's `download` name or `type` names one, or when a query value does (`?file=song.mp3`). Pictures, audio and video on the page are read from `src`, `srcset`, `poster`, `object` and `embed` too.
- **Links with no file type** (a CDN address, `/get?id=42`). When you open the list, each of these gets one check: a request for its first 512 bytes, with no cookies and no referer, 4 at a time, 5 seconds each, at most 100 links per scan (links to a sibling host such as `cdn.` first, then links on the same host, then loose pictures and media, then links to other sites). A link is listed only when its first bytes are one of the eight types and any `Content-Type` agrees. Web pages, errors and links whose type and bytes disagree are dropped. Nothing is checked until you open the list, and checks stop when you close it or leave the page. Links to other sites are checked too, so opening the list contacts those sites; a page can also point a link at a private-network address.
- **Thumbnails stay out.** A picture inside a link is that link's thumbnail and is not listed; the link behind it is checked instead, so the full file is listed. Pictures that are not inside a link are still listed.
- **Embedded frames are listed**, including frames from other sites. The list refreshes a moment after a frame finishes loading while it is open.
- **Errors are shown.** If the page cannot be read the panel says "Could not read this page" with **Scan again**; if some frames cannot be read it says how many. "No files found" appears only when the scan worked and no check is still running. Each frame has a 3-second limit.
- **No stale list.** The list, the checks and the scan result are cleared when you start a new page and by the ✕ button. An older scan can no longer replace a newer one, and a download can only be started from the list of the page you are on.
- Not changed: the checks before saving, the queue, and the rule that downloads are off until you allow them each run.

## 0.16.1 (2026-11-26)

Code reorganised into modules; nothing you see changes.

- The app's code is split into smaller files: the shared page state (`src/state.js`), downloads (`src/downloads.js`), screenshots (`src/screenshot.js`), network helpers (`src/network.js`) and the slow line (`src/slowline.js`). The main file keeps the window, the toolbar and the wiring.
- Nothing a page or a user can do is different. The unit tests and the smoke test pass unchanged.

## 0.16.0 (2026-11-26)

Links that leave the page ask first.

- **Leaving the page asks.** A link, a tapped new-tab link, or a page's own move to another site now opens a bar: **Leave example.com for other.org?** with **Go** and **Stay**. Stay keeps the page as it is. Go opens the link; the site you leave has its cookies and storage cleared, as before, unless you allowed it.
- **Same-site links do not ask.** Moving within one site (including between its subdomains) works as it did.
- **Nothing is stored.** The question lives only while the bar is open; it is dropped when the page changes, the page is cleared, or Null Browser closes.

## 0.15.0 (2026-11-26)

Downloads, off unless you turn them on for the run.

- **Off by default, asked each run.** A bar asks **Allow downloads this run?** at every start. Nothing is stored: the answer lasts until the browser closes. Until you say yes, the **Download** button only asks again.
- **Download** (in the toolbar) opens a list of the page's own links to PDF, MP3, WebM, MP4, JPG, WAV and MPEG files. Each line shows the file name, the path and the host. Links inside embedded frames are not listed.
- **Download all** is at the top of the list. It opens a warning (how many files, the one-at-a-time rule, the 200-file and 2 GB limits, and that a check cannot prove a file is safe). Only **Download all N files** queues them.
- **One at a time.** Files queue in path order. The queue bar shows progress and offers **Cancel queue**; the queue panel shows each file's state and lets you cancel, retry or remove it.
- **Cookies only when needed, and never kept.** The first request sends no cookies. A 401 or 403 answer offers **Retry with sign-in** for that one file, sending that site's cookies in memory for that one request only.
- **Checked before saving.** Each file goes to the RAM folder first. It must match its type (structure: PDF pages, MP4 boxes, WebM header, MP3 frames, WAV size, JPG markers, MPEG start codes) and contain no hidden code: no Windows or Linux program, no script, no web page markup, and no PDF action that runs code. Its SHA-256 is checked again before saving. These checks catch disguises and hidden code; they cannot prove a file is safe.
- **Atomic save.** The file is written to a `.nb-partial-` name in Downloads, synced to disk, checked again, then linked to its final name. An existing file is never replaced; a second copy gets a number. A failed save leaves nothing under the real name.
- **Names come from the server**, with the path removed and the right extension added. The names the page lists are never used for saving.
- **Dropped lines** resume from the byte they stopped at (up to five tries). Redirects are followed up to five hops and never from https to http.
- **The ✕ button** also cancels the queue and clears the list; saved files stay in Downloads, because they are yours.
- **Tests.** Unit tests for each type's check, each hidden-code rule, the list, the queue (order, one at a time, refusals, cancel, cookies not kept) and the names. The smoke test downloads real files from a local page: a good PDF and picture are saved; a PDF with a script action, an HTML page named as MP4, and a file type that is not allowed are refused and never saved; a sign-in file is refused, then saved only through the retry; the warning can be cancelled; a batch saves the good files and keeps the first copy.

## 0.14.0 (2026-11-26)

A clear-everything button, in the same place as the Android build's X.

- **The ✕ button** (far right of the toolbar, after JIT) wipes this run: every page and its cookies, storage, cache and sign-ins; the allowed sites and trusted certificates; the image and read-ahead queues; the watchdog's counts; and any file waiting for an answer, plus the downloaded files in the RAM folder. The page goes back to the blank start page.
- **What it keeps:** your bookmarks (in memory, until the browser closes) and anything in the `quarantine` folder, such as a screenshot waiting for Save. The toolbar settings (Slow, Images, Save-Data, Read ahead, JIT, Include toolbar) are not browsing data, so they stay too.
- **Tests.** The smoke test sets a cookie on the test site, makes a screenshot, presses ✕, and checks the cookie is gone while the screenshot is still waiting.

## 0.13.0 (2026-11-26)

A screenshot, saved only when you say so.

- **Screenshot** (in the **Line** row). Makes a PDF of the whole web page, including the parts above and below the screen. Electron prints the page itself, so there is no debugger and no new library. Tick **Include toolbar** first (off by default) to make the PDF of the whole window instead.
- **Checked before anything is saved.** The PDF is written to a `quarantine` folder inside the RAM folder, then checked: it must start with `%PDF-` and end with `%%EOF`, have a readable page, be under 64 MB, and match the hash recorded when it was made. A file that fails is deleted and a notice says why.
- **Saved only on Save.** A bar asks before anything is written. Save copies the PDF to your Downloads folder (read from `~/.config/user-dirs.dirs`, falling back to `~/Downloads`) as `Null-Browser-YYYY-MM-DD-HHMMSS.pdf`. The name has no site name in it, and an existing file is never overwritten. Cancel deletes the PDF.
- **This is the one written exception.** Null Browser still writes nothing else to disk, and nothing is saved unless you press Save.
- **Tests.** Unit tests for the checks, the Downloads lookup and the file name; the smoke test makes, cancels and saves a screenshot, checks it is a PDF in Downloads, and checks that nothing else was written to the home folder.

## 0.12.0 (2026-11-25)

Tell sites less, and never anything false. Sites behind a "checking your connection" page (Cloudflare, as 4chan uses) compare what a browser says about itself, so nothing is faked; things are only left out.

- **The user agent was giving Null Browser away.** It carried `NullBrowser/0.11.0` and the full Chrome version on every request, which picks you out of a crowd. It is now the plain Chromium form with the short version Chrome itself sends (`Chrome/152.0.0.0`), for pages and Null Browser's own fetches.
- **One language.** Only your first language is sent (`Accept-Language`, and `navigator.languages`), not the whole list.
- **No detailed hints.** A site that asks for the operating system version, CPU type, device model, full version list, line speed or memory (`Accept-CH`, `Critical-CH`) is not answered: the ask is dropped and any such header is removed. A script asking for the same (`getHighEntropyValues`) gets only the basic brand, mobile and platform values. (Electron sends no client-hint headers at all by default; that is unchanged.)
- **Line speed, memory, CPU cores and battery** are no longer readable by page scripts (`navigator.connection`, `deviceMemory`, `hardwareConcurrency` and `getBattery` are not there, as in browsers that never had them). Chromium answered a battery-level request without asking before.
- **Referer.** Going to another site sends only the site name (`https://example.com/`), never the page address, whatever the page's own policy says; going from https to http sends nothing. Within one site it is unchanged.
- **Known limits.** Background workers a page starts can still read the core count and memory size (the page script cannot reach them). Screen size, time zone and fonts are left as they are: changing them would be faking.
- **Tests.** Unit tests for each trim; the smoke test checks the user agent, one language, no detailed hints after a site asks, and the script readouts. The attack lab adds a fingerprint page (`attacklab/fplab.js`, `run-fp.js`) that records what reaches it, headers and script values; it passes.

## 0.11.0 (2026-11-25)

Made for dial-up: a slow line, a web comic, a line that drops.

- **Slow mode** (the new **Line** button, then **Slow: Auto / On / Off**). Auto turns it on when pages arrive at under about 16 KB/s or the first byte takes over 3 seconds, and off again above about 48 KB/s. Nothing is saved: every start is Auto.
- **Images in viewing order, one at a time.** In slow mode the page text, style and scripts load first; images wait and are fetched one after another, in the order you read them: what is on screen top to bottom, then down the page, then anything above. Scrolling moves what you are looking at to the front. Small images (icons, buttons) and images beside the main column (side ads) wait until the rest is done. A status row shows "image 3 of 14, in viewing order" and the line speed, with **Stop images**.
- **A dropped line costs nothing already received.** In slow mode Null Browser fetches the images itself and, when the line drops, asks again from the byte it stopped at (up to five tries, waiting 2 to 32 seconds); a panel that still fails is tried once more at the end. The finished image is handed to the page from memory. File downloads already resume in Chromium.
- **Less to wait for.** In slow mode, web fonts (the system font is used), link prefetch, tracking pings and video or audio preloading are skipped.
- **Images: On / Off**, for text only, slow or not. Off fetches no image at all; turning it back on loads the page's images.
- **Save-Data** (off by default): asks sites for lighter pages. Sites can see it.
- **Read ahead** (off by default): when a page is done and the line is idle, the next page (its `rel="next"` or Next link, same site only) and its images are fetched into memory, so Next opens without waiting for its images. Sites can see it. The read-ahead is dropped when you go to another site.
- **Tests.** Unit tests for the line meter, the viewing order, the page image rule, resuming and the next-page link; the smoke test loads a three-panel comic in slow mode (one at a time, in order, with a cut-off panel resumed) and a text-only page. The attack lab adds slowlab (`attacklab/run-slow.js`): a throttled comic with a side ad, a cut-off panel, a scroll test, a web font and prefetch, a text-only page and a two-page read-ahead; all six pass.

## 0.10.0 (2026-11-25)

The clipboard is off, everywhere.

- **Pages cannot use the clipboard.** A small script runs in every page and every frame before the page's own code and turns off `execCommand` copy, cut and paste, the Clipboard API (`navigator.clipboard`, already refused by permission) and the copy, cut and paste events, so a page can neither put text on your clipboard (the ClickFix trick, the lab's one known gap, is closed) nor read from it. It cannot be undone by the page.
- **You cannot copy or paste either.** Ctrl+C, Ctrl+X, Ctrl+V, Ctrl+Insert, Shift+Insert and Shift+Delete do nothing in pages, allowed pop-ups and the address bar; middle-click paste and dropped text do nothing either. There is no right-click menu. Type addresses by hand.
- **Tests.** The smoke test tries every way a page can write or read the clipboard (including from another frame and with a fresh copy of `execCommand` from a new frame) and every clipboard key in a page and in the address bar, and checks that the clipboard is unchanged and nothing is pasted. The attack lab's ClickFix test now counts a copy as a failure, not a known gap.

## 0.9.0 (2026-11-25)

- **A page can no longer trap you with "Leave site?".** A page that asks to stay (a `beforeunload` handler) after one tap could stop you leaving: a typed address did nothing, and closing the window was refused, with no question shown. Null Browser now always lets the page go, in the main page and in an allowed pop-up.
- **A page stuck in the print dialog can no longer hold you.** A page that calls `print()` in a loop kept its process blocked, and a typed address, back or home did nothing (the lab's run froze for 20 minutes). Now, when you leave a page and it has not answered for 2 seconds, Null Browser ends that page's process and goes where you asked, with no error page and no watchdog strike. A page that is only slow is not touched.
- **Tests.** The smoke test checks both traps: a page that asks to stay, and a page stuck in a print loop.
- **Attack lab:** three new tests, the "Leave site?" trap, a print-dialog loop, and files a page builds itself (a program from a `data:` or `blob:` address or an `<a download>` link, and a fake and a real PDF made in the page).

## 0.8.0 (2026-11-25)

A fix found by the new attack lab (`attacklab/`).

- **A file that does not say how big it is can no longer fill memory.** The 512 MB limit was only checked against the size a server declares; a server that sent no size (a chunked stream) could keep sending, and the lab's test pushed 629 MB into the RAM folder. The download is now stopped as soon as it passes 512 MB, with the notice "… is too big to open from memory", and nothing is opened or kept.
- **Tests.** The smoke test streams an unsized file past a small cap (set for the test run only; a packaged app ignores it) and checks that it is stopped, not opened and not kept.

## 0.7.0 (2026-11-25)

A watchdog: a site that behaves like an attack gets its storage cleared on the spot.

- **Five signals, watched per site.** A site is flagged, cleared and told about it when it: crashes the page twice within a minute; sends two disguised files (claiming to be a PDF, audio or video but failing the content check) within two minutes; keeps trying to open pop-ups after hitting the pop-up cap, three times within thirty seconds; has its page contact fifteen different hosts within ten seconds; or keeps the page's process pinned above 60% of a CPU core for three samples running (fifteen seconds) while nothing is clicked or typed.
- **Clears and tells you, nothing more.** A flagged site has its cookies and storage wiped the same way leaving it for a different site already would (scoped to its own origin), with a notice naming the site and what was seen (for example *Watchdog: evil.test sent disguised files repeatedly, so it was cleared.*). The page itself is left open; you decide whether to stay.
- **An allowed site is exempt**, the same as it is already exempt from the ordinary leaving-a-site clear.
- **`src/watchdog.js`** holds the five counters as plain, clock-injectable functions, with no Electron dependency, so they're unit-tested without a browser. `main.js` wires each one to where the signal already happens: `render-process-gone`, the content-mismatch check, the pop-up cap, every subresource request, and a five-second `app.getAppMetrics()` poll (normalized by core count, since a single busy thread on a multi-core machine can read a low percentage of the whole machine while still pinning one core).
- **Tests.** All five counters, their windows and resets, as unit tests; in a real window: each of the five signals produced for real (two disguised PDF downloads, six rapid pop-up attempts, a page with fifteen unreachable subresource hosts, a genuine fifteen-second CPU-pinning busy loop, and two real renderer crashes via `forcefullyCrashRenderer()`), each ending in its own watchdog notice.

## 0.6.0 (2026-11-25)

Leaving a site for a different one now wipes what it left behind.

- **A site's cookies and storage no longer outlive your visit to it.** Navigating to a different site's address or a link to one now clears the site you are leaving — its cookies, local storage, IndexedDB, service workers and cached files — the moment the new page starts loading, not just when Null Browser closes. Staying on one site, including a multi-step sign-in that redirects through several of its own pages, is unaffected; only crossing to a different site triggers it.
- **Allow for this site also covers this.** A site you've allowed (for a pop-up sign-in) keeps its storage when you leave it too, for as long as Null Browser stays open, the same as its cookies and pop-ups already did.
- **Scoped to the site you left, nothing else.** The clearing targets that site's own origin, so it can never reach into another site's storage, allowed or not.
- **Tests.** `originOf` as a unit test; in a real window: a cookie set on one site survives a second visit to the same site, is gone after visiting a different, unallowed site and returning, and survives that same round trip once the site has been allowed.

## 0.5.0 (2026-11-25)

A packaged Linux AppImage, with a launcher that closes the one gap a source run still has.

- **Packaged.** `npm run dist` builds a single unsigned AppImage (electron-builder, normal compression, about 123 MB), the same fuses as Node Controller Desktop (no `ELECTRON_RUN_AS_NODE`, no Node options, asar integrity checked, only the asar is loaded). The `nullbrowser` workflow builds and checks it on every change, and publishes it as a pre-release `nullbrowser-vX.Y.Z` on `main`.
- **The launcher.** Running Null Browser from source still needs a one-time warm-up, because Chromium's own font index can be built before the app's JavaScript moves `HOME` into the RAM folder. The packaged build does not: a small shell script takes the place of the real program, and before it hands off to the real one, it picks a RAM folder, builds it with the same layout `ram.js` would, and points `HOME`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME` and `TMPDIR` at it — all before Chromium's own startup code runs for the first time. Null Browser itself then adopts that folder instead of making a new one, and removes it on quit exactly as before.
- **Icon.** A plain amber "no" circle on the app's own dark background, matching the toolbar's look, at 512 px (`build/icon.png`) and 256 px (`ui/icon.png`).
- **Found by `check-package` on a real runner:** with no page ever loaded, the idle app still opened several connections to Google IP addresses within seconds of starting — a background fetch this environment's own proxy had been hiding, so it was never caught here. Tracing it with Chromium's own network log (`--log-net-log`) named the request: `https://redirector.gvt1.com/edgedl/chrome/dict/en-us-10-1.bdic`, a spell-check dictionary download that `setSpellCheckerEnabled(false)` alone does not stop. Every session now also calls `setSpellCheckerLanguages([])`, which does. `DnsOverHttpsUpgrade` and `AsyncDns` are disabled and `--dns-over-https-mode=off` is passed too, closing a real if lesser-used path to the same kind of background fetch. A switch with `=value` in it is now split correctly before being handed to Electron, since the existing code only ever passed bare switch names.
- **Tests.** The RAM-folder adoption rules as unit tests, and, in a real window, that a folder the launcher already built is used as-is rather than duplicated. `check-package` (new) builds on the desktop app's packaged checks and adds its own: the real home folder stays empty from the packaged app's very first start, with no warm-up run needed, and the RAM folder is still removed when the packaged app quits.

## 0.4.0 (2026-11-25)

A "Faster JavaScript" switch, on only for the run you turn it on in.

- **A toolbar button** reads **JIT: Off**. Clicking it asks first — "Turn on faster JavaScript? Null Browser restarts now, and goes back to JIT off the next time you start it." **Restart** closes the browser and reopens it at once with the JIT compiler on (WebAssembly and heavy scripted pages run faster, at the cost of the class of exploits `--jitless` closes off); **Cancel** leaves it off. The button then reads **JIT: On**, and clicking it again asks to turn it back off, restarting again. Nothing is written to disk to remember the choice between runs: start Null Browser again, normally or after a restart for anything else, and it is `--jitless` again.
- **How it works.** The browser relaunches itself as a whole new process with (or without) a marker on its own command line; nothing else about the process changes. The RAM folder and everything in it are still removed and recreated on each relaunch, the same as any other restart.
- **Tests.** The command-line marker is added, removed or left alone without disturbing the rest of the argument list, and is never treated as one of the unsafe switches a packaged build refuses, as unit tests; in a real window: the ask-first bar's text and Cancel; and, in a second run started with the marker already on its command line, that the JIT switch is not passed and the button reads **JIT: On**.

## 0.3.0 (2026-11-25)

Bookmark import, kept only until you close the browser.

- **A star button on the toolbar** opens a panel of bookmarks. **Import…** opens a file picker for a bookmarks export (the `.html` file Chrome, Firefox, Edge and Safari all write in the same Netscape bookmark format); every `http://` and `https://` link in it is read in, with its title. Anything else in the file (a folder name, a `javascript:` or `ftp://` link) is skipped. Clicking a bookmark opens it and closes the panel; the ✕ by each one removes it.
- **Nothing is written to disk.** The file you pick is read once and never kept; the bookmarks themselves live only in the running browser's memory, capped at 500, and are gone the moment Null Browser closes — there is no file, setting or database to import them a second time from.
- **Fixed while testing:** a pop-up test reached into the running browser by always taking the first top-level window, which is only ever right when no pop-up (blocked or real) is open at that moment; three spots now find the actual shell window instead. The flakiness this caused was already there in 0.2.0's own pop-up tests; it surfaced here because the bookmark test runs right after them.
- **Tests.** The bookmark-file parser (folders, duplicate and non-http(s) links, HTML-escaped titles, a file-size cap, a bookmark-count cap) as unit tests; in a real window: importing a bookmarks file, importing the same file again, opening a bookmark, and removing one.

## 0.2.0 (2026-11-25)

Files handed to your own apps, pop-ups sent to nowhere, and sign-ins that need a pop-up.

- **PDF, audio and video open in your own apps, after asking.** Opening a PDF, a sound file or a video shows a bar: *Open report.pdf (PDF, 2.1 MB) in your PDF viewer?* with **Open** and **Cancel**. The file is fetched into the RAM folder (never your Downloads folder), and handed to the system's default app only after **Open**; **Cancel** deletes it. Before it is handed on, its first bytes are checked: a file that says it is a PDF but is not (a web page, a program) is deleted with a notice and not opened. Up to 512 MB, one file at a time. Every other download is still refused. Null Browser has no PDF viewer or media player of its own; the file is removed with the RAM folder when Null Browser quits, so to keep it, save a copy from the other app first. The content check only confirms the file really is a PDF, audio or video file, not that it is safe to open; from there the risk is the same as any browser download, and it is the app that opens it, not Null Browser, that is the last line of defense.
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
