# Node Controller Mobile changelog

Current version: `0.1.0`. The app is in `android-controller/`; its version is `appVersion` in `android-controller/app/build.gradle.kts`. Newest entries first.

## 0.1.0 (2026-11-04)

- **First release.** An Android app that opens a node's Node Controller Dashboard (port 8989) in its own window. It is a client only: Node Controller runs on the node, and the phone shows its page.
- **Nodes.** Add, edit and remove nodes on the phone. Each has an optional name and an address: a host (`192.168.1.20`), a host with a port (`192.168.1.20:8989`), or a full `http://` or `https://` address. Port 8989 is used when none is given; `https://` without a port uses 443.
- **Log in as on the web.** The Dashboard asks for the node's root password in its own page. The app does not store the password. Its session cookie is kept by the WebView on the phone.
- **Forget login** clears the Dashboard's cookies on this phone only; the next open asks for the password again.
- **Stays on the Dashboard.** Links to other sites open in the phone's browser. Back goes back through the Dashboard's own pages, then to the node list.
- **Reload** reloads the page. If the page stops, Retry reopens it.
- **Stored on the phone only.** The node list is kept in the app's private storage and is not included in Android backups.
- **Network.** Plain `http://` is allowed, because the Dashboard serves plain HTTP on the LAN. HTTPS uses the system certificates (a tunnel such as Cloudflare). No certificate pinning in this version: the Dashboard has no HTTPS of its own.
- Unit tests for the address parser (`NodeAddressTest`, 10 tests), run in CI before the APK is built.
- Works with any Node Controller Dashboard. The app needs no change for the Dashboard's own updates.
