# Node Controller Desktop changelog

Current version: `0.3.0`. The app is in `desktop/`; its version is `version` in `desktop/package.json`. Newest entries first.

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
