# Node Controller Desktop changelog

Current version: `0.12.1`. The app is in `desktop/`; its version is `version` in `desktop/package.json`. Newest entries first.

## 0.12.1 (2026-11-25)

Running without the sandbox is written to the log.

- **Warning in diagnostics.log.** The AppImage's start script (from electron-builder) adds `--no-sandbox` by itself when the system does not allow unprivileged user namespaces (some Ubuntu setups; Debian and its derivatives allow them, so the sandbox stays on there). The app still starts in that case, as chosen, and now writes a WARNING line to diagnostics.log each time, saying the pages are less isolated from the computer than they should be. Starting it with `--no-sandbox` by hand does the same.
- **Tests.** Spotting the flag as a unit test, and in the real window the warning reaching diagnostics.log (the test run uses `--no-sandbox`).

## 0.12.0 (2026-11-25)

Start from the app menu or a desktop icon.

- **Add to menu.** When the app runs from an AppImage, the sidebar shows **Add to menu**. One click copies the AppImage to `~/.local/share/node-controller/` (so the icon keeps working if the download is moved or deleted), adds **Node Controller Desktop** to the app menu (`~/.local/share/applications/nodecontroller.desktop`), installs its icon, and puts the same launcher on the desktop (the folder named in `~/.config/user-dirs.dirs`, normally `~/Desktop`), marked executable. Nothing is written until the button is clicked.
- **Update and remove.** Run a different AppImage and the button says **Update menu copy**, which replaces the copy the menu starts. Started from the menu copy it says **Remove from menu**, which takes the copy, the menu entry, the icon and the desktop launcher away.
- **One icon in the dock.** The launcher names the app's window class, `nodecontroller` (and the app's `desktopName` is `nodecontroller.desktop` on Wayland), so MATE, KDE, XFCE and GNOME group the window with the menu entry instead of showing a second icon.
- **Desktops.** MATE (Caja) and KDE trust a launcher that is executable. GNOME and XFCE ask once, the first time it is opened, whether to trust it. The app runs no other program to set this (the lockdown still forbids it).
- **An app icon.** The app's own icon (a small picture of its layout, amber on dark) replaces Electron's default in the menu, the dock and the window.
- **No sandbox switch in the AppImage's own entry.** The desktop entry inside the AppImage no longer carries `--no-sandbox` (electron-builder adds it by default).
- **Tests.** The launcher on its own (paths, the entry text with spaces and refused characters, the desktop folder from user-dirs.dirs, install, update, remove, no desktop folder, not an AppImage) and, in the real window, Add to menu into a test home folder and Remove from menu from the installed copy.

## 0.11.20 (2026-11-25)

Node pages and Last Heard share one setup.

- **One place for page views.** The setup every page view needs (the locked-down view itself, its window, the WebRTC rule, the keyboard shortcuts, focus tracking, the "loaded" and "stopped working" handling) was written out twice, once for node pages and once for Last Heard, and the copies had drifted (0.11.3's trace went into only one of them). It is now one helper both use; what differs (the session, where links may go, certificates, scheme switching) stays separate. No change in what the app does.
- **Scheme rule tightened.** An address that has loaded in this session now keeps its scheme whatever the error (0.11.13 still switched on an SSL error, which a node reset can also cause mid-handshake), and a switch that fails again within 30 s always goes back, whatever the second error is (before, only a wrong-scheme error went back, so a page could be left on the wrong scheme). CI hit this: the reset test failed there with the reset arriving as an SSL error.
- **Tests.** The scheme rule as a unit test with those cases; the real-window tests, which open node pages and Last Heard and reset a working https page, pass.

## 0.11.19 (2026-11-25)

A drop on a slot that does not exist opens nothing.

- **Slot checked first.** A drop names the page and the slot. For a page that was not open, the page was added to the layout before the slot name was checked, so a drop with an unknown slot left the page open but shown nowhere (and saved that way). The slot is now checked first, and a bad drop changes nothing.
- **Tests.** In the real window: a drop for an unknown node and one on a slot that does not exist are refused and open nothing.

## 0.11.18 (2026-11-25)

A node delete that fails says so.

- **Delete errors show.** Deleting a node always closed the dialog and said "Node deleted.", even when the app refused. The error now shows in the dialog, which stays open, and the node stays in the list.
- **Tests.** In the real window: a refused delete shows its message and keeps the dialog open and the node saved; the next delete works.

## 0.11.17 (2026-11-25)

A node export that cannot be written says so.

- **Export errors show.** Exporting the node list to a folder that cannot be written (read-only, full, or a folder picked as the file) threw inside the app and nothing appeared. It now says "The node list could not be written there. Pick another folder." and the reason goes in diagnostics.log.
- **Tests.** In the real window: an export that works (the file has the node), and one that cannot be written (the message shows). Export had no test before.

## 0.11.16 (2026-11-24)

The sidebar is rebuilt only when it changes.

- **Less work while dragging.** Every layout update rebuilt the whole sidebar (slots, pages, Install Monitor, saved splits), about 60 times a second while the divider was dragged, and again on every focus or status change. It is now rebuilt only when something it shows changes: the slots, the pages and their state, the saved splits, the view or the nodes. The title bar and panes still update every time.
- **Tests.** The real-window tests (drag and drop between slots and the sidebar, the menu, saved splits) pass unchanged.

## 0.11.15 (2026-11-24)

A quieter log that keeps its history.

- **No more step-by-step trace.** The page trace added in 0.11.3 to find the SysMon crash (found: Electron 45, 0.11.6) is gone; it wrote about a dozen lines for every page load and two for every permission check. The log keeps what helps: pages that fail to load (now Last Heard too), scheme changes, helper processes that crash, and each refused permission once per run.
- **A full log is kept, not wiped.** At 200 KB `diagnostics.log` becomes `diagnostics.log.1` and a new one starts, so the lines just before a crash are not lost. The folder is made once instead of on every line.
- **Tests.** The log on its own: time stamps and the folder, keeping the old log at the limit, and an unwritable log never throwing.

## 0.11.14 (2026-11-24)

A page is no longer closed from inside its own event.

- **Closing waits a moment.** When a page switched scheme, the app closed that page's view from inside the page's own "failed to load" event, and Ctrl+W and Ctrl+R did the same from inside the page's own key event. Destroying a page while Electron is still handing it an event is a known way to crash Electron. All three now act a moment later, once the event is finished.
- **The app's shortcuts are always the app's.** Ctrl+1, Ctrl+2, Ctrl+W, Ctrl+R, Ctrl+plus, Ctrl+minus, Ctrl+0 and Ctrl+Tab are always taken by the app now. Before, with no page open, Ctrl+R reloaded the app's own sidebar and Ctrl+plus or minus could reach Chromium's page zoom (which a host shares).
- **Tests.** The real-window tests drive every shortcut and the scheme switch, unchanged, and pass.

## 0.11.13 (2026-11-24)

A page keeps the scheme it loaded on.

- **No flip-back after a reset.** When a page failed on the wrong scheme the app tried the other one and remembered it, and if the other one also failed within 30 s it went back. That window stayed open after the page had loaded, so a node restart (a connection reset or an empty reply) in the next 30 s put the wrong scheme back. A successful load now closes the window.
- **A page that loaded keeps its scheme through a reset.** A connection reset or an empty reply on an address that has already loaded in this session no longer switches its scheme; the page shows "Could not open" and Try again. A wrong-scheme error (for example SSL protocol error) still switches, and a page moved to another port is learned again.
- **Tests.** The decision rule as a unit test, and in the real window a working https page whose connection is reset: it keeps https and loads again on Try again (this check fails on 0.11.12).

## 0.11.12 (2026-11-24)

A page on plain http added while the app runs asks for a restart.

- **Restart banner.** Pages on plain http are treated as secure (so Node Talker can use the microphone and pages can write to the clipboard) only for the addresses known when the app starts; Chromium cannot add more later. A node added or edited while the app runs, a node list imported, or a page whose scheme is learned as http, used to lose the microphone and clipboard until the next start, with no sign why. An amber banner in the sidebar now says so, with **Restart now**, which reopens the app (the same AppImage, with the same options) so the new address is included. The log notes it once.
- **Tests.** In the real window: the banner appears when a plain-http node is added and is gone after a restart.

## 0.11.11 (2026-11-24)

Trusting one tool's certificate no longer fails after another tool's was refused.

- **Refused certificates are kept per host and port.** Each tool on a node has its own self-signed certificate. The app remembered only one refused certificate per host name, so opening SysMon after Node Talker replaced Talker's; clicking "Trust this certificate" on Talker's panel then said "That certificate was not the one refused", and a page's panel could show another tool's fingerprint. Each tool's port now has its own entry.
- **Tests.** A unit test for the key (host and port, default port, IPv6, a bad address) and, in the real window, two untrusted tools on one host: the second is refused with its own fingerprint, the first still shows its own, and trusting it works (this check fails on 0.11.10).

## 0.11.10 (2026-11-24)

The window fits the screen.

- **Opens inside the screen.** The window opened at 1280 by 800 on every screen, so on a laptop screen (1366 by 768, less the panel) the bottom was cut off. It now opens at the screen's usable size, never bigger than 1280 by 800, centred, and maximized when the screen is smaller than that.
- **Maximize works on small screens.** The smallest window was 1100 by 700; on XFCE (Peppermint) the window manager will not maximize a window whose minimum size does not fit the screen. The minimum is now 900 by 560, or the screen size if that is smaller.
- **Sidebar at least 176 px.** On a narrow window the sidebar stays 176 px wide so the logo, slots and page names still read; from about 1170 px wide it is 15% as before.
- **Tests.** The window-size rules (large screen, 1366 by 768, 1024 by 600, a tiny screen, no screen) and the sidebar floor.

## 0.11.9 (2026-11-24)

Faster start.

- **Lighter compression.** The AppImage was packed at maximum compression (xz), so every start unpacked about 97 MB again; on a slow disk or CPU the window stayed black for several seconds. It is now packed at normal compression: about 123 MB to download (+26%), and unpacking the whole image takes 1.5 s instead of 10.5 s on the build machine, about seven times faster.
- **Electron stays on 44.x.** `CLAUDE.md` now says so: Electron 45.4.1 crashed when SysMon opened on a Debian machine (0.11.0 to 0.11.5), and 44.11.5 does not (0.11.6).

## 0.11.8 (2026-11-24)

A narrower sidebar.

- **Sidebar 15% of the width** (was 20%, 3 of 15 units, now 2.25): 192 px at 1280 wide, 288 px at 1920, 165 px at the 1100 px minimum. The pages get the width back.
- **Logo on two lines.** "Node Controller Desktop" wraps to two lines in the 44 px block; the version moved to the bottom of the sidebar, under Install Monitor.

## 0.11.7 (2026-11-24)

A thinner title bar.

- **Title bar 44 px.** The bar above the pages (and the logo block above the sidebar) was one grid unit tall, a fifteenth of the window width: 85 px at 1280 wide, 128 px at 1920. It is now a fixed 44 px at every width, so the pages get that height back. The sidebar keeps its 3 of 15 units.
- **Logo on one line.** "Node Controller Desktop" now fits on a single line in the thinner block, with the version under it.
- **Still on Electron 44.11.5.** 0.11.6 confirmed the SysMon crash was a bug in Electron 45.4.1: with 44.11.5 SysMon opens on the Debian machine that crashed.

## 0.11.6 (2026-11-24)

A test build on Electron 44.11.5, the newest release before 45.

- **Electron 44.11.5** (was 45.4.1). On one Debian machine the app segfaults inside Electron (a text pointer that was never set, read on the main thread) right after SysMon finishes loading. The crash is not in the app's own code, and nothing tried so far stops it: not the certificate, the keyring, the GPU, the sandbox, the icon, the permission checks or the input method. It does not happen on the test machines. This build checks whether it is an Electron 45 bug. Nothing else changes; the fuses, the lockdown and every test are the same.

## 0.11.5 (2026-11-24)

Pages no longer fetch the node's default icon.

- **No favicon requests.** A page that declares no icon makes the browser engine ask the node for `/favicon.ico`. On one Debian machine, Electron crashed right after SysMon loaded, at exactly that step (the log's last line was the icon update). The app never shows page icons, so requests for `/favicon.ico` are now refused before they connect, like any other request outside the allow-list. The policy test lists the new refusal.

## 0.11.4 (2026-11-24)

The page trace now covers every page, and permission checks no longer read the media details unless they are about the microphone.

- **Trace fixed.** In 0.11.3 the loading-step trace was only on the Last Heard page. It is now on every node page too.
- **Permission details.** A permission check or request for anything other than the microphone no longer reads the media type from Electron's details. A page asking about something else (such as `background-sync`, which SysMon asks about as it opens) now gets its answer without touching that field. Each answer is also written to the log.

## 0.11.3 (2026-11-24)

A trace of what a page does as it opens, to find a crash.

- **diagnostics.log** now also records, in order, each page's loading steps (start, navigation, DOM ready, finished, title and icon changes) and each permission a page asks for or checks. If the app dies while a page opens, the last line says what it was doing. Only the names of the steps and permissions are written, never addresses or page content.

## 0.11.2 (2026-11-24)

A page that fails to load says why in the log.

- **diagnostics.log** now records each page that fails to load (the page, the error, the address and scheme tried) and each scheme change it makes or undoes, so a page that will not open can be traced.
- A failed first load no longer prints an "Failed to load URL" warning in the terminal; the page's own failure message covers it.

## 0.11.1 (2026-11-24)

A stuck quit can no longer hang.

- **Quit signals end the app.** Ctrl+C, a terminal closing or a plain `kill` ask the app to quit cleanly; if that has not finished after 3 seconds the app now exits anyway, so a signal that arrives while the app is still starting cannot leave it hanging.
- **Package check.** The packaged-app check kills the apps it starts with SIGKILL when they run over their time, so a stuck app can no longer hold the check (the 0.11.0 run of it hung until the workflow timed out and the release was not published).

## 0.11.0 (2026-11-24)

After a crash the app starts clean.

- **A crash resets what was open.** The app notes when it starts and clears the note when it quits normally. If the note is still there at the next start, the last run did not exit cleanly (it crashed, was killed or the machine lost power), so the open pages, the slots, the view and the sizes are **not** restored: it starts with nothing open, so a page that was misbehaving cannot take it down again straight away. A message in the sidebar says so. Nodes, saved splits, trusted certificates and remembered schemes are kept.
- **After a normal exit nothing changes:** everything comes back as it was, as before.
- **Closing from the terminal counts as a normal exit.** Ctrl+C, the terminal closing and a plain `kill` all quit cleanly, so they do not trigger the reset.
- **One copy at a time.** Starting a second copy now brings the first one to the front and the second quits, so two copies cannot overwrite each other's saved layout or be mistaken for a crash.
- **diagnostics.log** records "the last run did not exit cleanly" when the reset happens.
- **Tests.** The marker (first run, clean exit, left behind, ending twice, an unwritable folder) and, in the real window: a second copy handing over, the app killed hard with six pages open, then the restart with nothing open, the message, nodes and saved splits kept, a saved split still opening, and a clean exit restoring everything.

## 0.10.0 (2026-11-24)

Pages scale to fit their pane.

- **Scaled to fit.** In a small pane (the two top panes and the lower third of the three page layout, or each pane of two pages) the page is no longer cut off: it is laid out as if the window were bigger and drawn smaller, so more of it shows. The scale is the pane's size against 800 by 500 (never above 100% and never below 50%). At 1280 pixels wide, a one page view stays at 100%; the top panes of three pages come out at about 64%, and the lower third at about 65%. It follows the divider and the window size.
- **Your own size.** In a pane's strip, **−** and **+** change the size of that page by a tenth (40% to 160%), and the percentage between them shows it. A size you set is kept for that page (and saved with the layout) until you click the percentage, or press Ctrl+0, to fit the pane again. Ctrl+plus and Ctrl+minus do the same from the keyboard for the focused page, in a single page view too. In the title bar a small percentage appears when the focused page is not at 100%; clicking it fits the pane again.
- **Each pane has its own.** Chromium ties page zoom to the host name, so two panes showing the same node would have shared one zoom; the scaling here is done on each pane separately, so the Left, Right and Lower pages can each have their own size. Clicks and typing land where they should in a scaled pane (tested).
- **Tests.** The scaling rules (the sizes, the limits, steps, Fit, saving and restoring, closing a page) and, in the real window, the size each page actually sees in the three page layout, a click on a button in a scaled pane, the + and − buttons, the percentage, the keyboard and the title bar chip.

## 0.9.1 (2026-11-24)

Crashes leave a trace and no longer take the app down. Added after a report that the app closed after logging in to Node Talker and Node Monitor on a real node (cause not yet known).

- **A page that crashes is shown as stopped, not lost.** If a page's process dies, its pane says "The page stopped working (reason)" with **Try again**, its sidebar entry is marked failed, and nothing else in the app is affected.
- **If the window's own page crashes** it is reloaded.
- **Everything that dies is written down.** A page process, a helper process (graphics, audio, network), an error in the main process, a window closing and the app quitting each add a line to `diagnostics.log` in the data folder (`~/.config/Node Controller/`) and to the terminal's error output. The file keeps its last 200 KB. Nothing is sent anywhere.
- **Errors in the main process no longer end the app silently.** They are written down and the app keeps running.
- **Tests.** In the real window a page's process is killed on purpose: the app stays up, the pane and entry say so, the line is in `diagnostics.log`, and Try again brings the page back.

## 0.9.0 (2026-11-24)

The sidebar is the whole menu. The title bar tabs are gone; every page is listed in the sidebar as a single page; what is stopped is hidden; Install Monitor stays at the bottom.

- **No title bar tabs.** The title bar now shows what you are looking at (the focused page, with a dot for its state and "(away)" or "(LAN address)") and the Single, Slots, Save split and Reload buttons. Pi-Piper and Pibrary, which were tabs there, are entries in the sidebar like the rest (marked with an arrow; they still open your web browser).
- **Everything is in the sidebar, as single pages, by default.** Under the three slots, **Single pages** lists every page of every node (one group for each node, with its Edit button), with no need to open anything first. Click one to show it by itself; drag it into a slot. A page you have open is marked (a dashed outline, a solid amber one while it is on screen) and has a **×** that closes it. Last Heard appears in its own group while it is open. A page in a slot is listed in that slot, not twice.
- **Stopped pages are hidden.** The app looks at each page's port on every node every 15 seconds (a plain connection, nothing is sent). A page whose tool is stopped or not installed is not listed. A page you have open stays listed, in italics and dimmed, while its tool is stopped, and normal again when it runs. A node with nothing running says so. Pages show at once before the first look.
- **Install Monitor is always at the bottom** of the sidebar, on its own line for each node, and cannot be hidden: it is always there, even when it is stopped (then dimmed, so you can see it is down) and it has no ×. It is a single page like 44helper; its right-click menu can close it.
- **Closing pages.** With no tabs, a page is closed with the × on its entry (a page in a slot: first take it out with its ×, then close it), or from the right-click menu.
- **Each page learns its own scheme (found on a real node).** The node tools do not all speak the same: Node Controller serves plain http, while Node Talker, SysMon, Node Monitor and the others serve https with a certificate of their own. One "Use https" setting for the whole node loaded Node Controller as https and got `ERR_SSL_PROTOCOL_ERROR`. Now a page that fails the way a wrong scheme fails (a TLS error on a plain port, or a reset or empty answer from a TLS port) is tried once on the other scheme; if that answers, the app remembers it for that page (and tells you in the sidebar). If the second try fails as well, the first scheme is put back and the error is shown. Pages without a remembered scheme use the node's setting. The Edit window shows what is remembered, with **Forget**. A link between a node's pages is recognised on either scheme. A page remembered as http needs the app restarted before it can use the microphone (the browser reads that list at start).
- **Bug fixes.** The Edit window's "Trusted certificates" row showed even when empty (a style rule beat the hidden attribute everywhere; one rule now makes hidden win). And the Edit window now reads the node's current settings each time it opens, so saving can no longer write back an old copy over something the app learned on its own.
- **Tests.** The monitor (up, down, change, LAN and away addresses, a node that goes, overlapping looks, the timer) and, in the smoke test, the sidebar-first layout in the real window: every running page listed, stopped pages gone and back, an open stopped page kept, Install Monitor pinned and unhideable, and all the earlier slot, split, drag, saved split, restart and certificate flows; the per-page schemes (page, node, link matching) and, in the real window, a plain page on an https node, a TLS page on an http node, and the Remembered row with Forget.

## 0.8.0 (2026-11-24)

The shared Node Control look, and the title "Node Controller Desktop".

- **The shared look.** The window now uses the same style sheet as the node tools: the embedded Readex Pro font (the same weights 400 and 700 the tools embed, as two files in the app), the same colours, text sizes and mono font, the dark surface and border colours, the gradient header with the amber underline and the glowing amber logo, uppercase bold tabs and buttons (the focused tab glows amber), amber for the selected page and the focused slot, green for the main action and red for dangers, and dim text `#aab8cc`. The light theme is gone: the tools have none.
- **Title.** The window, the page and the logo say **Node Controller Desktop**; the logo's second line shows the version. The sidebar's top block is as tall as the title bar, so the amber line runs across the whole window. The launcher name in the package is Node Controller Desktop too. Your nodes and layout stay where they were (`~/.config/Node Controller`).
- **Kept to the look by a check.** `ci/check_repo.py` fails if `desktop/ui/style.css` loses a line of the shared look (the font-face, the `--sans` and `--mono` variables, the text sizes, the amber pair and the mono rule) as it does for the tools, with a test; the window's policy allows the two font files from its own folder and nothing else.
- Nothing else changes: the same pages, slots, splits and rules.

## 0.7.1 (2026-11-24)

Fix: the packaged app (the AppImage) opened a window with a title and nothing inside it. 0.5.0 to 0.7.0 are affected when run as the AppImage; running from the source was fine, which is why the tests missed it.

- **Cause.** The hardening switched off Electron's file protocol privileges fuse. With it off, the app cannot read its own page out of its archive, so the window loaded nothing (`ERR_FILE_NOT_FOUND` for `app.asar/ui/index.html`).
- **Fix.** The fuse is on again. The window's page is the only one that uses the file protocol; its content security policy allows nothing but its own script and style, and the request policy for that window allows only its own files, so it still cannot fetch anything.
- **A broken window now fails loudly.** If the window's page cannot load, the app says so on its error output and exits with code 3 instead of leaving a blank window.
- **The package check now loads the window.** `npm run check-package` starts the packaged app and waits for the window to report that its page ran (`shell-ready`); it fails if it does not, or if a load failure is reported. The fuse list it checks is updated. It was checked against the broken build: it fails there.
- Nothing else changes.

## 0.7.0 (2026-11-24)

Four more pages (two single-only, two that open in the web browser), several trusted certificates for a node, and a sidebar whose slots stay in view.

- **Install Monitor (8990) and Terminal Monitor (7878)** open in the app as single pages only, like 44helper: no slot, no drag, and their menu has only Show alone. Terminal Monitor is the root shell page; it only opens when you click it.
- **Pi-Piper (8765) and Pibrary (9000)** have a tab in the title bar for each node and a button (marked ↗) in the page list, but clicking one opens the page in your default web browser, not in the app, using the node's home address (or its LAN address when that answers). They are never loaded in the app, have no pane and take no part in the slots. A page of the app that links to them also hands the link to the browser. The notice in the sidebar says what was opened.
- **Several trusted certificates per node.** Each tool can have its own self-signed certificate (Terminal Monitor keeps its own folder), so trusting one used to push out the one before. A node now keeps up to eight (the oldest goes first); Trust this certificate adds one, and the Edit window shows them with Forget all. A node saved with one certificate keeps it.
- **The sidebar no longer scrolls the slots away.** The slots and Single pages stay at the top (scrolling by themselves only when they grow past about half the height); Open a page and Saved splits scroll underneath. Before, clicking a page near the bottom of the list could scroll the slots out of reach of a drag.
- **Edit window.** The page ports now cover all eleven pages.
- **Tests.** Page table, link matching for the new ports, single-only and browser-only pages, several certificates, and, in the smoke test with the real window, the browser launches (logged through a test hook that does nothing in the packaged app), single-only pages, and trusting two different certificates on one node.

## 0.6.0 (2026-11-24)

Slots. The sidebar has a Left, a Right and a Lower slot, each a stacked list of pages; what is in the slots is what the page area shows. Node Recorder, WifiMon and 44helper join the pages.

- **Three slots.** Each slot holds a stack of pages, in any order, and any page can go in any slot. One page of each slot is selected and shown. A page is in one slot at most. The layout appears as the slots fill: a lone slot is a one page view; Left and Right are 6 and 6; adding Lower makes two over a full-width third with equal rows. A slot that is empty takes no room; a Lower slot with only one of Left or Right is one over one. The divider between Left and Right still drags (double-click centres it).
- **Putting a page in a slot.** Drag it (from a tab, the Single pages list, a slot, or the Open a page list) onto the slot in the sidebar, or onto Left, Right or Lower on the page area (zones show while you drag). Or right-click it and pick Put in Left, Right or Lower slot, or Ctrl+click it to put it in the next empty slot, then in the focused slot. A page dropped in a slot becomes its selected page. **×** on a slot's page, or dropping it on the Single pages list, takes it out again.
- **Clicking a page in a slot** selects it, focuses its slot and shows all the slots. A page that is in no slot shows alone, and the slots stay as they are; **Slots** (Ctrl+2) or any slot page returns to them. **Single** (Ctrl+1) shows the focused page alone.
- **Single pages.** Every page opens by itself first and sits in the Single pages list under the slots, with Last Heard and any page not in a slot. Closing the page shown alone goes back to the slots.
- **Pane strips.** When two or more panes show, each has a strip: its slot name, the slot's stacked pages as buttons when it holds more than one (click one to select it), **Alone** and **Out** (take it out of its slot).
- **44helper is always a single page.** It cannot go in a slot, has no drag, and its menu has only Show alone.
- **More pages.** Node Recorder (8995), WifiMon (8991) and 44helper (9997). The Edit window has seven ports; nodes saved before get the defaults. The lockdown covers them like the others.
- **Saved splits** now save the slots: the pages of each slot, which one is selected, and the divider. Splits saved in 0.5.0 read as Left, Right and Lower. A split with Last Heard in a slot cannot be saved (the Save split button says why).
- **Layout file.** 0.5.0's layout file is read and converted.
- **Shorter labels with one node.** With a single node, tabs and list entries drop the repeated node name ("Node Talker", not "Shack Node · Node Talker"), so seven open pages fit the header in two rows. With two or more nodes the full names return.
- **Idle pages.** Unchanged: a page that is not on screen is idle (slowed and muted), Node Talker never.
- **Removed.** The 1, 2 and 3 page buttons and Ctrl+3: the slots decide how many pages show. Ctrl+1 and Ctrl+2 switch between Single and Slots.
- **Tests.** The layout tests cover the slots (growing, any page in any slot, your example layout of Controller and SysMon, Talker, Recorder and WifiMon, and Node Monitor), the one page view, selecting, taking out, closing, 44helper, Ctrl+click, the rectangles for every mix of slots, the drop zones, saving and restoring and reading 0.5.0 files; the saved splits have their own tests; the smoke test does it in the real window with real mouse drags between the sidebar lists and onto the page area.

## 0.5.0 (2026-11-24)

Every page is a single-page tab; you stack tabs into a split. SysMon and Node Monitor join the pages. Last Heard is a single page too. Pages that are not on screen are idle.

- **More pages.** SysMon (port 9999) and Node Monitor (port 7777) are hardwired pages next to Node Controller and Node Talker. The node's Edit window has a port for each; nodes saved before get the defaults. The lockdown covers them like the others (their node's addresses only; no away address).
- **Tabs are single pages.** Opening a page, from the node list or a tab, shows that page by itself. A split is an arrangement of tabs you already have open.
- **Making a split.** Drag a tab, or a page from the node list, onto the page area. Zones show where it goes, always left to right, then down, never more than three: from one page, the right half adds a page beside it; from two pages, the bottom third adds the lower third; over a pane, it replaces that pane (or swaps it, if the page is already showing). The other ways: right-click a tab or page for the same choices in a menu, Ctrl+click to add it to the next free place (right, then below, then the bottom), or the 2 pages and 3 pages buttons (Ctrl+2, Ctrl+3). In a split each pane has a strip with its page's name, **Alone** (show it by itself) and **Remove** (take it out of the split).
- **Clicking a page that is in the split** brings back the whole split with focus on that page, the same for a tab. Clicking one that is not in it shows that page alone. **Back to split** (or any page that is in the split) returns to it. The 1 page button does the same as Alone for the focused pane and keeps the split to come back to. Closing a page shrinks the split; a pair left alone becomes one page.
- **Last Heard** (Node Talker's LH and Node Controller's) opens as a new single-page tab, the same tab each time, replacing the 0.4.0 rule that put it beside or below the page. It can be stacked into a split like any tab, but a split that holds it cannot be saved.
- **Saved splits.** **Save split** names the arrangement on screen (two or three pages, with the divider position); it is kept in `splits.json`, listed in the sidebar, and a click opens any missing tabs and shows it. Up to 20; a name that exists is replaced. Deleting a node deletes the splits that use it.
- **Idle pages.** A page that is not on screen is idle: Chromium slows it down and its sound is muted. A page that is on screen is never slowed, even when the app window is behind others. **Node Talker is never idle**, on screen or not, so it keeps listening in a hidden tab. A tab shows a hollow dot while its page is idle. This replaces 0.4.0's "hidden pages are not slowed down" for every page except Node Talker. Not yet tried on a real node.
- **Layout.** The grid is unchanged (sidebar 3, header 1, pages 12; rows equal). In a split, each pane's strip takes 28 pixels from the top of its pane.
- **Tests.** The layout tests cover dropping, replacing, swapping, the order of places, never more than three panes, clicking a page in and out of the split, Back to split, Last Heard as a single page, closing, restoring and the drop zones; the new splits file has its own tests; the smoke test does it all in the real window: real mouse drag and drop onto the zones, the menu, Ctrl+click, the strips, idle and active pages, Back to split, saved splits, a restart, the shortcuts and deleting a node.

## 0.4.0 (2026-11-24)

Fixes from reading the pages' own code: hidden pages keep running, Node Controller's Last Heard works, and links between a node's pages stay in the app.

- **Hidden pages are not slowed down.** Chromium normally slows a page you cannot see. Node pages are now exempt, so Node Talker's audio and timers keep their pace in a tab behind another. Last Heard is not exempt. Not yet heard on a real node.
- **Node Controller's Last Heard.** Its LH button (`asl_dvs_lh`) now opens the Last Heard tile like Node Talker's (`nt_lh`), with the same rules. Placement is left to right, then down: beside a single page, below two pages, in place of the bottom pane of three. There is never a fourth pane.
- **Links between the two pages stay in the app.** A link or window from one page to the other page of a node (for example Node Controller's Listen link to Node Talker), on the node's home, LAN or away address, now opens or focuses that tab instead of the system browser, so the login is shared. Links to anything else (other tools, other hosts) still open in the system browser. The path in such a link is dropped: the page opens at its start.
- **Tests.** Link matching, the Last Heard window names, the placement rule (one page, two pages, three pages, four tabs) and, in the smoke test against the real window, Last Heard from Node Controller on the right of a single page, Controller linking to Talker, and hidden pages not being slowed.
- **Repo.** `CLAUDE.md` has a section for `desktop/`. `ci/check_repo.py` fails a comment in the `.js`, `.css` or `.html` files of `desktop/` (with tests).

## 0.3.0 (2026-11-24)

The 3 : 12 / 3 : 6 : 6 layout, three page layouts and the Last Heard tile. Rows mode is gone.

- **Grid.** The window is 15 units wide. The sidebar is 3 units, the header is 1 unit tall, and the page area is the other 12. At 1280 pixels wide that is a 256 pixel sidebar, an 85 pixel header and 1024 pixels of pages. The main process works the sizes out and the page follows them, so they always agree. The smallest window is now 1100 by 700.
- **1 page, 2 pages, 3 pages.** Three buttons (Ctrl+1, Ctrl+2, Ctrl+3). One page fills the 12 units. Two pages are 6 and 6 side by side. Three pages are two side by side over a third that takes the full 12, with the two rows the same height. Any tab can go in any pane, and tabs open in the pane you last used. A mode needs that many tabs open.
- **Divider.** The line between the two top panes drags and double-clicks back to 6 : 6. The line between the rows is fixed at equal height.
- **Last Heard tile.** The LH button in Node Talker opens its page as a tab called Last Heard, in the bottom pane of three pages (beside the page that asked, or as the third page when two are showing). A second LH click reuses the tab. It is not saved across restarts. It runs in its own session that is never kept, with every permission refused, and it may load from the public internet but not from private addresses (10.x, 172.16-31.x, 192.168.x, 127.x, 169.254.x, localhost, `.local` and single-word names), unless the address is one of your saved nodes. An address that is not plain http or https, has a login in it, or is on a private network that is not your node is refused with a message. Links inside the tile stay in it under the same rules; windows it opens go to the system browser.
- **Header.** Tabs wrap onto a second row when there are many, instead of shrinking.
- **Tests.** The layout tests cover the grid at several widths, the three modes and how they change, the Last Heard rules and the pane sizes; the policy tests cover the private-address and Last Heard rules; the smoke test checks the real window against the ratios in every mode, the Last Heard tile, its refusal and its blocking.

## 0.2.0 (2026-11-24)

Tabs, a split view, a locked-down Chromium and a one-file Linux package. Still only the Node Controller and Node Talker pages.

- **Tabs.** Each page you open from the node list becomes a tab beside the others, and stays loaded when you switch away (Node Talker keeps running). Close a tab with its ×, Ctrl+W or Reload with Ctrl+R. Ctrl+Tab and Ctrl+Shift+Tab step through the tabs. A dot on each tab shows loading, loaded or failed. A tab says "(away)" or "(LAN address)" when it did not use the home address.
- **Split view.** Single, Columns (side by side) or Rows (stacked), from the buttons or Ctrl+1, Ctrl+2 and Ctrl+3. A new split shows the tab you were on beside the next one, in tab order. Clicking a page, or pressing a tab, goes into the pane you last used. The divider drags; double-click it to centre. Each pane keeps at least 240 pixels. A page that fails to load shows its message and buttons in its own pane.
- **Remembered layout.** The open tabs, the split and the divider position come back after a restart. Pages load again when shown; a tab you are not looking at loads when you first open it.
- **Edits that matter reload.** Changing a node's address, ports, certificate, LAN or away address reloads its tabs; renaming a node does not. Deleting a node closes its tabs.
- **Locked down.** Pages get the microphone (audio only), choosing the speaker, and copying to the clipboard, and only from the node's own addresses. Camera, location, notifications, MIDI, USB, Bluetooth, serial, HID, screen capture, reading the clipboard and everything else are refused. A page can send requests only to its own node (home, LAN or away address): anything else, including WebSockets and images, is blocked. The app window loads only its own files. WebRTC address leaks, spell checking, translation, sync, component updates, the media router and the browser's background network calls are switched off, and there is no crash reporter, updater, telemetry or developer tools.
- **No back doors.** The packaged app refuses debugging and weakening switches (`--remote-debugging-port`, `--inspect`, `--js-flags`, `--proxy-server`, `--user-data-dir`, `--ignore-certificate-errors`, `--disable-web-security` and more), `ELECTRON_RUN_AS_NODE` and `NODE_OPTIONS` do nothing, and it loads code only from its own archive, which is integrity-checked when it starts. The package check fails if any of that changes.
- **One file.** `npm run dist` in `desktop/` builds `NodeController-0.2.0.AppImage` (about 99 MB), x64 Linux, English only, unsigned. No icon yet. The app archive holds only the app's own files. An idle packaged app was seen making no outside connections and listening on no port.
- **Sandbox.** The Chromium sandbox stays on. An AppImage cannot set up the setuid helper, so it needs unprivileged user namespaces, which some systems restrict (for example Ubuntu 24.04 until an AppArmor profile or `kernel.apparmor_restrict_unprivileged_userns=0` allows it). Nothing in the app turns the sandbox off.
- **Tests.** Unit tests for the layout rules, the lockdown policy and the source (no unsafe setting, only the route probe opens a socket), the smoke test now covers tabs, the split, dragging, shortcuts, restart, closing and what a page may do, and `npm run check-package` checks the AppImage's fuses, archive, locale, switches and silence.

## 0.1.0 (2026-11-24)

First build: the Linux desktop client's skeleton, node list and connection handling. It shows only the Node Controller and Node Talker pages of a node you add. It is not on the stable/testing channels and has no installer yet.

- **Electron shell.** One window with a node list on the left and one page on the right. Pages load in their own sandboxed view with no preload script and no Node.js access. A link that leaves the node's address opens in the system browser.
- **Fresh node list.** Add, edit and delete nodes (name, address, https, a port for each page, an away address and a LAN address). Saved as `nodes.json` in the app's data folder. Import and Export move the list as a JSON file.
- **Two pages, fixed.** Node Controller (port 8989) and Node Talker (port 8993). There is no address bar and no other page can be opened.
- **Own login for each node.** Each node has its own session, so cookies never mix. Deleting a node clears its session.
- **Trusted certificate.** An https node with a certificate Chromium does not trust is refused and its SHA-256 fingerprint is shown. Trust this certificate saves it as the node's pin; only that exact certificate is accepted afterwards, on the host name and on the LAN address. The away address must have a normal certificate.
- **Home, LAN, away.** Each page tries the home address for 1.5 seconds, then the LAN address, then the away address (Node Talker only). The answer is kept for 30 seconds and forgotten when a load fails, on Reload, and when the node is edited. An https LAN address is used only when the node has a pinned certificate. The addresses are typed in; learning them from the node comes later.
- **Plain http nodes** are treated as secure origins, so the microphone can be used on them. The list is read when the app starts, so restart the app after adding an http node.
- **Tests.** Unit tests for address parsing, node checks, route choice and timing, certificate pinning and the node file (`npm test` in `desktop/`), and a smoke test that runs the real app against stub nodes, including the certificate trust steps (`npm run smoke`, needs a display such as `xvfb-run`).
