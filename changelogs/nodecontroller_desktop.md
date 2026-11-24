# Node Controller Desktop changelog

Current version: `0.1.0`. The app is in `desktop/`; its version is `version` in `desktop/package.json`. Newest entries first.

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
