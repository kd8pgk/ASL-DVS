# Node Controller Desktop changelog

Current version: `0.6.0`. The app is in `desktop/`; its version is `version` in `desktop/package.json`. Newest entries first.

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
